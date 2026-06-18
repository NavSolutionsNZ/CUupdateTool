#!/usr/bin/env python3
"""
compareengine.py -- merge-integrity oracle for CUupdate.exe output.

A standalone validation harness, fully isolated from the cuupdate/ engine
package (no engine imports). It checks whether the auto-merge produced the same
object BODY as a hand-merge, to build confidence and surface rule gaps.

Design (locked with Rich):
  - Pairing is BY OBJECT KEY (prefix-agnostic): the <Type><Number> token after
    the final '-' and before '.txt', so MyMerged-T18.txt pairs with EX-T18.txt
    regardless of self-merge naming convention.
  - The check is BODY-ONLY. CUupdate's stamped parameters are trustworthy and so
    irrelevant to integrity, and they never match a hand-merge anyway:
      * the entire OBJECT-PROPERTIES block (Date/Time/Modified/Version List) is
        stripped before comparing;
      * the entire doc-trigger (the trailing commented-out BEGIN { ... } block)
        is stripped.
    Everything between -- PROPERTIES trigger code, FIELDS, KEYS, CODE, CONTROLS
    -- is compared line-for-line (LCS, latin-1/cp1252). A difference is located
    to a C/AL section so a human can judge whether it is a real merge error.

Verdicts:
  matched            object bodies identical
  unmatched          real body difference (sections + lines reported)
  missing-candidate  gold has no candidate for the same object key
  missing-gold       candidate has no gold for the same object key
  collision          the same key appears twice in one folder (not compared)
  unkeyable          a filename has no <Type><Number> key (listed, not dropped)

Nothing here makes a merge decision; it only judges body equivalence.
"""
import os
import re
import difflib

ENCODING = 'latin-1'

# Object declaration: line 1 is `OBJECT <Type> <ID> <Name>` (NAV v14 export).
OBJTYPE = re.compile(r'^\s*OBJECT\s+([A-Za-z]+)\s+(\d+)\s*(.*?)\s*$', re.I)

# Pairing key parsed from the FILENAME: the <TypeLetter><Number> token between
# the final '-' and '.txt' (e.g. MyMerged-T18.txt -> 'T18', EX-P5205801.txt ->
# 'P5205801'). The prefix is ignored entirely, so a gold and a candidate for
# the same object pair regardless of differing self-merge naming conventions
# (MyMerged-, MySanitised-, EX-, ...). Case-insensitive; the number may be short
# or long.
OBJKEY = re.compile(r'-([A-Za-z]\d+)\.txt$', re.I)

# Doc-trigger entry: `<tag> <DD.MM.YY> <rest>`. Used only by the doc-trigger
# boundary detector to confirm a trailing brace block really is the
# documentation trigger (so it can be stripped). The tags themselves are not
# compared -- the doc-trigger is excluded from the integrity check entirely.
DOC_ENTRY = re.compile(r'^\s*([A-Za-z][\w.\-]*)\s+\d{2}\.\d{2}\.\d{2}\b')
BEGIN_BARE = re.compile(r'^\s*BEGIN\s*$')
OPEN_BRACE = re.compile(r'^\s*\{\s*$')


# ---------------------------------------------------------------------------
# File reading / identity
# ---------------------------------------------------------------------------

def read_lines(path):
    """Read a C/AL object as a list of lines (newlines stripped per line).

    latin-1 round-trips every byte, so this never raises on encoding. We keep
    line content verbatim apart from the trailing newline; line-ending style
    (CRLF vs LF) is therefore normalised away by splitlines, which suits an
    oracle comparing two finalised exports for *content* equivalence.
    """
    with open(path, 'r', encoding=ENCODING, newline='') as f:
        return f.read().splitlines()


def detect_type_id(lines):
    """Return (TYPE, ID, NAME) from body line 1, or (None, None, None).

    Type/ID are intrinsic to the object body and read here only for display in
    the summary table -- pairing itself is by filename.
    """
    if not lines:
        return (None, None, None)
    m = OBJTYPE.match(lines[0])
    if not m:
        return (None, None, None)
    return (m.group(1).upper(), m.group(2), (m.group(3) or '').strip())


def object_key(filename):
    """Return the prefix-agnostic pairing key for a filename, or None.

    The key is the <TypeLetter><Number> token after the final '-' and before
    '.txt', upper-cased so pairing is case-insensitive. Examples:
        MyMerged-T18.txt    -> 'T18'
        EX-C5025612.txt     -> 'C5025612'
        EX-P5205801.txt     -> 'P5205801'
    A filename with no such tail returns None and is reported as unkeyable
    rather than silently mispaired.
    """
    m = OBJKEY.search(filename)
    return m.group(1).upper() if m else None


# ---------------------------------------------------------------------------
# Doc-trigger boundary and tag set
# ---------------------------------------------------------------------------
# The documentation trigger is the trailing `BEGIN` / `{ ... }` block at the end
# of the CODE section (Rich: "the doc trigger is always at the end of the
# object"). It is entirely commented-out -- no compile risk -- so strict byte
# comparison STOPS at its opening brace. Within it we compare only the set of
# customer tags (whole first token of each dated entry); date and description
# are ignored as noise.

OBJPROPS_HEAD = re.compile(r'^\s*OBJECT-PROPERTIES\b', re.I)


def strip_object_properties(lines):
    """Return `lines` with the entire OBJECT-PROPERTIES block removed.

    The OBJECT-PROPERTIES block holds only tool-managed metadata (Date, Time,
    Modified, Version List) -- all stamped by CUupdate at run time and never a
    place customer code lives. For a merge-integrity check it is pure noise: a
    hand-merged gold and the tool's output will never agree on these, and a
    disagreement there is not a merge error. So we drop the block before
    comparing and judge the object body alone.

    The block is `OBJECT-PROPERTIES` followed by a brace group `{ ... }`; we
    remove from the header line through its matching close brace.
    """
    out = []
    i = 0
    n = len(lines)
    while i < n:
        if OBJPROPS_HEAD.match(lines[i]):
            # Skip the header line, then skip a brace group if present.
            j = i + 1
            # advance to the opening brace
            while j < n and lines[j].strip() != '{':
                # tolerate the rare inline form; stop if we hit another section
                if SECTION_HEAD.match(lines[j]):
                    break
                j += 1
            if j < n and lines[j].strip() == '{':
                depth = 0
                while j < n:
                    s = lines[j].strip()
                    if s == '{':
                        depth += 1
                    elif s == '}':
                        depth -= 1
                        if depth == 0:
                            j += 1
                            break
                    j += 1
                i = j
                continue
            # no brace group found; just drop the header line
            i += 1
            continue
        out.append(lines[i])
        i += 1
    return out


def doc_trigger_start(lines):
    """Index (0-based) of the opening `{` of the doc-trigger block, or None.

    Found by scanning from the end for the last bare `BEGIN` immediately
    followed by a `{`, where the block beneath contains at least one dated
    entry line. Returning the brace line means strict comparison covers
    everything strictly above it.
    """
    for i in range(len(lines) - 1, 0, -1):
        if OPEN_BRACE.match(lines[i]) and BEGIN_BARE.match(lines[i - 1]):
            # Confirm the block holds dated entries (guards against an empty or
            # non-doc brace block tripping the detector).
            for j in range(i + 1, len(lines)):
                if DOC_ENTRY.match(lines[j]):
                    return i
                if lines[j].strip() in ('}', 'END.'):
                    break
    return None


# ---------------------------------------------------------------------------
# Section attribution
# ---------------------------------------------------------------------------
# A lightweight, brace-depth-aware classifier. Walks the body tracking the
# top-level named section we are inside (OBJECT-PROPERTIES, PROPERTIES, FIELDS,
# KEYS, CODE, CONTROLS, ...) and recognises a few finer landmarks (the Version
# List line, a named trigger header, the documentation trigger). This is a
# reporting aid, not a parser: it never has to be perfect, only helpful enough
# that a human can decide "that's a property carry I missed" at a glance.

SECTION_HEAD = re.compile(
    r'^\s*(OBJECT-PROPERTIES|PROPERTIES|FIELDS|KEYS|FIELDGROUPS|CODE|CONTROLS|'
    r'ELEMENTS|REQUESTPAGE|DATASET|LABELS|RDLDATA|ACTIONS)\b', re.I)
VERSION_LINE = re.compile(r'^\s*Version\s*List\s*=', re.I)
DOC_TRIGGER = re.compile(r'^\s*\{\s*$')           # opening brace of a block
TRIGGER_HEAD = re.compile(r'^\s*(On[A-Za-z]+)\s*=', re.I)
FIELD_NODE = re.compile(r'^\s*\{\s*(\d+)\s*;')


def section_map(lines):
    """Return a list parallel to `lines`: the section label for each line.

    Labels are human-facing strings like 'Version List', 'Properties',
    'Fields (field 12)', 'Trigger OnValidate', 'Doc trigger', 'Code'. The map
    is best-effort; unknown context falls back to the nearest top-level header
    or 'Body'.
    """
    labels = [None] * len(lines)
    top = 'Header'            # before the first named section
    cur_field = None
    in_doc = False
    doc_seen_props = False

    for i, ln in enumerate(lines):
        head = SECTION_HEAD.match(ln)
        if head:
            top = head.group(1).upper()
            cur_field = None
            # The documentation trigger lives as a Documentation=> block inside
            # CODE; we detect it by its content below, not by a section head.
        if VERSION_LINE.match(ln):
            labels[i] = 'Version List'
            continue
        if top == 'OBJECT-PROPERTIES':
            labels[i] = 'Version List' if VERSION_LINE.match(ln) else 'Object properties'
            continue
        if top == 'PROPERTIES':
            labels[i] = 'Properties'
            continue
        if top == 'FIELDS':
            fm = FIELD_NODE.match(ln)
            if fm:
                cur_field = fm.group(1)
            labels[i] = f'Fields (field {cur_field})' if cur_field else 'Fields'
            continue
        if top == 'KEYS':
            labels[i] = 'Keys'
            continue
        if top in ('CONTROLS', 'ELEMENTS', 'ACTIONS', 'REQUESTPAGE', 'DATASET'):
            labels[i] = top.capitalize()
            continue
        if top == 'CODE':
            if re.search(r'Documentation\s*=', ln, re.I):
                in_doc = True
            if in_doc:
                labels[i] = 'Doc trigger'
                # crude exit: a procedure or trigger header ends the doc block
                if TRIGGER_HEAD.match(ln) or re.search(r'\bPROCEDURE\b', ln):
                    in_doc = False
                    labels[i] = 'Code'
                continue
            tm = TRIGGER_HEAD.match(ln)
            if tm:
                labels[i] = f'Trigger {tm.group(1)}'
                continue
            labels[i] = 'Code'
            continue
        labels[i] = 'Body' if top == 'Header' else top.capitalize()

    return labels


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def _norm_ws(line):
    """Normalise a line for the MATCH decision: collapse all runs of whitespace
    OUTSIDE string literals to a single space and strip the ends, while
    preserving whitespace INSIDE double-quoted strings verbatim.

    This makes the comparison indifferent to CU re-nesting and inter-token
    spacing (which only ever changes whitespace outside quotes), matching the
    engine's principle that indentation is not a structural signal -- while
    still catching a genuine change to the spacing inside a quoted string
    (a caption, message, or option value), which is real C/AL content.

    The original lines are preserved for the report; only the comparison key is
    normalised.
    """
    out = []
    in_q = False
    prev_space = False
    for ch in line:
        if ch == '"':
            in_q = not in_q
            out.append(ch)
            prev_space = False
        elif not in_q and (ch == ' ' or ch == '\t'):
            if not prev_space:
                out.append(' ')
            prev_space = True
        else:
            out.append(ch)
            prev_space = False
    return ''.join(out).strip()


def _diff_lines(gold, cand):
    """Return a list of (lineno, gold_line, cand_line) for genuine differences.

    Lines are aligned and compared on their whitespace-normalised form
    (_norm_ws: collapse whitespace outside quotes), so CU re-nesting and
    inter-token spacing are not differences. The REPORTED lines are the
    originals, so the detail still shows real content and indentation.

    Aligned by LCS (difflib.SequenceMatcher) so a pure insertion or deletion
    shows ONLY the changed lines -- not every line below the edit point. lineno
    is 1-based in the gold file for 'replace'/'delete', and the gold insertion
    point for 'insert'. A side absent at that position is reported as None.
    """
    g_norm = [_norm_ws(l) for l in gold]
    c_norm = [_norm_ws(l) for l in cand]
    out = []
    sm = difflib.SequenceMatcher(a=g_norm, b=c_norm, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            continue
        if tag == 'replace':
            span = max(i2 - i1, j2 - j1)
            for k in range(span):
                g = gold[i1 + k] if i1 + k < i2 else None
                c = cand[j1 + k] if j1 + k < j2 else None
                out.append((i1 + k + 1, g, c))
        elif tag == 'delete':
            for k in range(i1, i2):
                out.append((k + 1, gold[k], None))
        elif tag == 'insert':
            for k in range(j1, j2):
                out.append((i1 + 1, None, cand[k]))
    return out


def _label_for_cand_line(cand_line, c_map, c_body):
    """Section label for a candidate-only (inserted) line, read from the
    candidate's own section map. Falls back to 'Body' if not locatable.
    """
    try:
        idx = c_body.index(cand_line)
    except ValueError:
        return 'Body'
    return c_map[idx] if 0 <= idx < len(c_map) else 'Body'


def compare_pair(gold_path, cand_path):
    """Compare one gold/candidate pair for MERGE INTEGRITY. Return a result dict.

    The question is only: did the auto-merge produce the same object BODY as the
    hand-merge? So we compare the body alone:
      - the entire OBJECT-PROPERTIES block is stripped (Date/Time/Modified/
        Version List are tool-stamped metadata, never customer code, and never
        match a hand-merge -- irrelevant to integrity);
      - the entire doc-trigger is stripped (commented-out, tool-managed);
      - everything between -- PROPERTIES (trigger code), FIELDS, KEYS, CODE,
        CONTROLS, ... -- is compared line-for-line via LCS.

    Verdict is `matched` if the bodies are identical, else `unmatched` with the
    differing sections and lines.
    """
    gold = read_lines(gold_path)
    cand = read_lines(cand_path)
    typ, oid, name = detect_type_id(gold if gold else cand)

    base = {
        'type': typ, 'id': oid, 'name': name,
        'gold': gold_path, 'cand': cand_path,
    }

    g_body = _body_only(gold)
    c_body = _body_only(cand)

    # Match decision is whitespace-normalised (CU re-nesting is not a diff).
    if [_norm_ws(l) for l in g_body] == [_norm_ws(l) for l in c_body]:
        base['verdict'] = 'matched'
        base['sections'] = []
        base['diffs'] = []
        return base

    diffs = _diff_lines(g_body, c_body)
    if not diffs:
        # Normalised forms differ only in count/order that LCS realigns to
        # nothing reportable -- treat as matched rather than empty-unmatched.
        base['verdict'] = 'matched'
        base['sections'] = []
        base['diffs'] = []
        return base
    secs = []
    g_map = section_map(g_body)
    c_map = section_map(c_body)
    for lineno, g, c in diffs:
        if g is not None:
            idx = lineno - 1
            label = g_map[idx] if 0 <= idx < len(g_map) else 'Body'
        else:
            label = _label_for_cand_line(c, c_map, c_body)
        if label not in secs:
            secs.append(label)

    base['verdict'] = 'unmatched'
    base['sections'] = secs
    base['diffs'] = diffs
    return base


def _body_only(lines):
    """The comparable object body: OBJECT-PROPERTIES block removed and the
    doc-trigger (and everything after it) dropped.
    """
    stripped = strip_object_properties(lines)
    start = doc_trigger_start(stripped)
    return stripped[:start] if start is not None else stripped


def compare_dirs(gold_dir, cand_dir):
    """Pair files by OBJECT KEY (prefix-agnostic) across the two folders.

    The key is object_key(filename) -- the <Type><Number> token after the final
    '-' -- so MyMerged-T18.txt pairs with EX-T18.txt. Returns a dict:
        {
          'results': [compare_pair dict, ...],   # paired objects
          'missing_candidate': [(key, gold_filename), ...],
          'missing_gold':      [(key, cand_filename), ...],
          'collision':         [(key, side, [filenames]), ...],
          'unkeyable':         [(side, filename), ...],
        }
    A key appearing more than once on a side is a collision (ambiguous which
    file is authoritative) and is NOT compared. A file with no parseable key is
    unkeyable and is listed rather than silently dropped.
    """
    def index(folder, side):
        keyed = {}
        collisions = {}
        unkeyable = []
        for f in sorted(os.listdir(folder)):
            if not os.path.isfile(os.path.join(folder, f)):
                continue
            k = object_key(f)
            if k is None:
                unkeyable.append((side, f))
                continue
            if k in keyed:
                collisions.setdefault(k, [keyed[k]]).append(f)
            else:
                keyed[k] = f
        # Drop any colliding key from the clean map so it is never paired.
        for k in collisions:
            keyed.pop(k, None)
        return keyed, collisions, unkeyable

    g_keyed, g_coll, g_unkey = index(gold_dir, 'gold')
    c_keyed, c_coll, c_unkey = index(cand_dir, 'candidate')

    results = []
    for k in sorted(g_keyed.keys() & c_keyed.keys()):
        gfn, cfn = g_keyed[k], c_keyed[k]
        res = compare_pair(os.path.join(gold_dir, gfn),
                           os.path.join(cand_dir, cfn))
        # Show both filenames so a prefix-mismatch pair is legible in the report.
        res['file'] = gfn if gfn == cfn else f'{gfn} / {cfn}'
        res['key'] = k
        results.append(res)

    missing_candidate = sorted((k, g_keyed[k])
                               for k in g_keyed.keys() - c_keyed.keys())
    missing_gold = sorted((k, c_keyed[k])
                          for k in c_keyed.keys() - g_keyed.keys())

    collision = ([(k, 'gold', v) for k, v in sorted(g_coll.items())]
                 + [(k, 'candidate', v) for k, v in sorted(c_coll.items())])
    unkeyable = sorted(g_unkey + c_unkey)

    return {
        'results': results,
        'missing_candidate': missing_candidate,
        'missing_gold': missing_gold,
        'collision': collision,
        'unkeyable': unkeyable,
    }


# ---------------------------------------------------------------------------
# Report rendering (shared by the CLI runner and the GUI)
# ---------------------------------------------------------------------------

VERDICT_ORDER = {
    'unmatched': 0,
    'collision': 1,
    'unkeyable': 2,
    'missing-candidate': 3,
    'missing-gold': 4,
    'matched': 5,
}


def _fmt_row(file, typ, oid, verdict, sections, w):
    t = f'{typ or "?"} {oid or ""}'.strip()
    secs = ', '.join(sections) if sections else ''
    return (f'{file:<{w["file"]}}  {t:<{w["type"]}}  '
            f'{verdict:<{w["verdict"]}}  {secs}')


def build_report(outcome):
    """Return the full report as a single string (console, file, and GUI all
    render the identical text). `outcome` is the dict from compare_dirs.
    """
    results = outcome['results']
    rows = []
    for r in results:
        rows.append({
            'file': r['file'], 'type': r.get('type'), 'id': r.get('id'),
            'verdict': r['verdict'], 'sections': r.get('sections', []),
            'diffs': r.get('diffs', []),
        })
    for key, fn in outcome.get('missing_candidate', []):
        rows.append({'file': fn, 'type': None, 'id': key,
                     'verdict': 'missing-candidate', 'sections': [],
                     'diffs': []})
    for key, fn in outcome.get('missing_gold', []):
        rows.append({'file': fn, 'type': None, 'id': key,
                     'verdict': 'missing-gold', 'sections': [],
                     'diffs': []})
    for key, side, fns in outcome.get('collision', []):
        rows.append({'file': ', '.join(fns), 'type': None, 'id': key,
                     'verdict': 'collision', 'sections': [f'{side} side'],
                     'diffs': []})
    for side, fn in outcome.get('unkeyable', []):
        rows.append({'file': fn, 'type': None, 'id': None,
                     'verdict': 'unkeyable', 'sections': [f'{side} side'],
                     'diffs': []})

    rows.sort(key=lambda r: (VERDICT_ORDER.get(r['verdict'], 9), r['file']))

    if not rows:
        return 'No files found in either folder.'

    w = {
        'file': max([4] + [len(r['file']) for r in rows]),
        'type': max([4] + [len(f'{r["type"] or "?"} {r["id"] or ""}'.strip())
                           for r in rows]),
        'verdict': max([7] + [len(r['verdict']) for r in rows]),
    }

    out = []
    header = (f'{"FILE":<{w["file"]}}  {"OBJECT":<{w["type"]}}  '
              f'{"VERDICT":<{w["verdict"]}}  SECTIONS / NOTE')
    out.append(header)
    out.append('-' * len(header))
    for r in rows:
        out.append(_fmt_row(r['file'], r['type'], r['id'], r['verdict'],
                            r['sections'], w))

    tally = {}
    for r in rows:
        tally[r['verdict']] = tally.get(r['verdict'], 0) + 1
    out.append('')
    out.append('Summary: ' + ', '.join(
        f'{k}={tally[k]}'
        for k in sorted(tally, key=lambda k: VERDICT_ORDER.get(k, 9))))

    detail = [r for r in rows if r['verdict'] == 'unmatched']
    if detail:
        out.append('')
        out.append('=' * len(header))
        out.append('DETAIL (non-matched objects)')
        out.append('=' * len(header))
        for r in detail:
            out.append('')
            out.append(f'### {r["file"]}  [{r["verdict"]}]  '
                       f'sections: {", ".join(r["sections"]) or "-"}')
            for lineno, g, c in r['diffs']:
                gtxt = '<absent>' if g is None else g
                ctxt = '<absent>' if c is None else c
                out.append(f'  line {lineno}:')
                out.append(f'    gold: {gtxt}')
                out.append(f'    cand: {ctxt}')

    return '\n'.join(out)


def needs_attention(outcome):
    """True if anything in the run needs a human eye."""
    return bool(
        any(r['verdict'] in ('unmatched', 'missing-candidate', 'missing-gold')
            for r in outcome['results'])
        or outcome.get('missing_candidate') or outcome.get('missing_gold')
        or outcome.get('collision') or outcome.get('unkeyable'))
