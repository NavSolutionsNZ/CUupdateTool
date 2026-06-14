#!/usr/bin/env python3
"""
compareengine.py -- byte-level oracle for CUupdate.exe output.

A standalone validation harness, fully isolated from the cuupdate/ engine
package (no engine imports). It compares hand-merged GOLD objects against the
tool's CANDIDATE output to build confidence and surface rule gaps.

Design (locked with Rich):
  - Pairing is BY FILENAME across two folders (golds/, candidates/).
  - Compare is STRICT RAW BYTE compare, latin-1/cp1252. No content normalising.
  - The OBJECT-PROPERTIES header carries housekeeping the tool stamps at run
    time (Date=, Time=, Modified=). When the ONLY difference between two
    otherwise-identical files lives on those header lines, the verdict is
    `matched-except-header` rather than `unmatched` -- nothing is hidden, but a
    date-stamp diff does not masquerade as a real content gap.
  - On a genuine content diff we locate each differing line to a C/AL SECTION
    (Version List, Properties, Fields, Keys, Triggers, Controls, Doc trigger,
    Code) so a human can decide at a glance whether it is a real manual step.

Verdicts:
  matched               bytes identical
  matched-except-header  differ only on Date=/Time=/Modified= header lines
  unmatched             real content difference (sections + lines reported)
  missing-candidate     gold has no candidate of the same filename
  missing-gold          candidate has no gold of the same filename

Nothing here makes a merge decision; it only judges equivalence.
"""
import os
import re
import difflib

ENCODING = 'latin-1'

# Object declaration: line 1 is `OBJECT <Type> <ID> <Name>` (NAV v14 export).
OBJTYPE = re.compile(r'^\s*OBJECT\s+([A-Za-z]+)\s+(\d+)\s*(.*?)\s*$', re.I)

# Header lines the tool stamps at run time. A difference confined to these is
# cosmetic (date/time/modified housekeeping), not a content gap.
HEADER_KEY = re.compile(r'^\s*(Date|Time|Modified)\s*=', re.I)

# Doc-trigger entry: `<tag> <DD.MM.YY> <rest>`. The tag is the WHOLE first token
# (e.g. PA035804.26149, EU.0020605, AP001651, WBL001) -- the granularity at
# which a customer addition would actually go missing. We compare only the SET
# of tags across gold/candidate; date and description are deliberately ignored
# (the doc-trigger is fully commented-out, so it carries no compile risk and its
# date is a run-day stamp).
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


# ---------------------------------------------------------------------------
# Doc-trigger boundary and tag set
# ---------------------------------------------------------------------------
# The documentation trigger is the trailing `BEGIN` / `{ ... }` block at the end
# of the CODE section (Rich: "the doc trigger is always at the end of the
# object"). It is entirely commented-out -- no compile risk -- so strict byte
# comparison STOPS at its opening brace. Within it we compare only the set of
# customer tags (whole first token of each dated entry); date and description
# are ignored as noise.

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


def doc_trigger_tags(lines, start):
    """Set of whole-first-token tags in the doc-trigger block beginning at the
    brace index `start`. Empty set if start is None.
    """
    tags = set()
    if start is None:
        return tags
    for j in range(start + 1, len(lines)):
        s = lines[j].strip()
        if s == '}':
            break
        m = DOC_ENTRY.match(lines[j])
        if m:
            tags.add(m.group(1))
    return tags


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

def _header_only_diff(gold, cand):
    """True iff gold and cand have the same number of lines and every line that
    differs is a Date=/Time=/Modified= header line on BOTH sides.

    Same length is required: a header-only stamp difference never changes line
    count. If lengths differ, it cannot be a pure header diff.
    """
    if len(gold) != len(cand):
        return False
    any_diff = False
    for g, c in zip(gold, cand):
        if g == c:
            continue
        any_diff = True
        if not (HEADER_KEY.match(g) and HEADER_KEY.match(c)):
            return False
    return any_diff


def _diff_lines(gold, cand):
    """Return a list of (lineno, gold_line, cand_line) for genuine differences,
    aligned by LCS (difflib.SequenceMatcher) so a pure insertion or deletion
    shows ONLY the changed lines -- not every line below the edit point.

    lineno is 1-based in the gold file for 'replace' and 'delete' regions, and
    the gold insertion point for 'insert' regions. A side absent at that
    position is reported as None, so an inserted/deleted line reads cleanly as
    gold:<absent> or cand:<absent>.
    """
    out = []
    sm = difflib.SequenceMatcher(a=gold, b=cand, autojunk=False)
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
    """Compare one gold/candidate pair. Return a result dict.

    Comparison is in two regions:
      1. Everything strictly ABOVE the doc-trigger -> strict byte compare, with
         the Date=/Time=/Modified= header tolerance.
      2. The doc-trigger block -> SET compare of customer tags only; date and
         description ignored. A gold tag absent from candidate is a dropped
         customer element and forces `unmatched` with 'Doc trigger' in sections.
    """
    gold = read_lines(gold_path)
    cand = read_lines(cand_path)
    typ, oid, name = detect_type_id(gold if gold else cand)

    base = {
        'type': typ, 'id': oid, 'name': name,
        'gold': gold_path, 'cand': cand_path,
    }

    # Split each side at its own doc-trigger boundary. The body above is the
    # strict-compare region; the doc-trigger tag set is compared separately.
    g_start = doc_trigger_start(gold)
    c_start = doc_trigger_start(cand)
    g_body = gold[:g_start] if g_start is not None else gold
    c_body = cand[:c_start] if c_start is not None else cand
    g_tags = doc_trigger_tags(gold, g_start)
    c_tags = doc_trigger_tags(cand, c_start)

    # Doc-trigger judgement: only a gold tag MISSING from candidate matters
    # (a dropped customer addition). Extra candidate tags are not a gap.
    missing_tags = sorted(g_tags - c_tags)

    body_identical = (g_body == c_body)
    header_only = (not body_identical) and _header_only_diff(g_body, c_body)

    # ---- classify ----
    if body_identical and not missing_tags:
        base['verdict'] = 'matched'
        base['sections'] = []
        base['diffs'] = []
        return base

    if header_only and not missing_tags:
        base['verdict'] = 'matched-except-header'
        base['sections'] = ['Object properties']
        base['diffs'] = _diff_lines(g_body, c_body)
        return base

    # Real difference: collect body sections and/or doc-trigger gap.
    diffs = _diff_lines(g_body, c_body) if not body_identical else []
    secs = []
    if diffs:
        g_map = section_map(g_body)
        c_map = section_map(c_body)
        for lineno, g, c in diffs:
            # Label from the side that actually has content at this diff: gold
            # for replace/delete, candidate for a pure insertion.
            if g is not None:
                idx = lineno - 1
                label = g_map[idx] if 0 <= idx < len(g_map) else 'Body'
            else:
                # insertion: lineno is the gold insertion point; find the
                # candidate line's own section by locating it in c_map.
                label = _label_for_cand_line(c, c_map, c_body)
            if label not in secs:
                secs.append(label)
    if missing_tags:
        if 'Doc trigger' not in secs:
            secs.append('Doc trigger')

    base['verdict'] = 'unmatched'
    base['sections'] = secs
    base['diffs'] = diffs
    base['missing_doc_tags'] = missing_tags
    return base


def compare_dirs(gold_dir, cand_dir):
    """Pair files by identical filename across the two folders and compare each.

    Returns (results, missing_candidate, missing_gold) where results is a list
    of compare_pair dicts and the two missing lists hold filenames present on
    only one side.
    """
    gold_files = {f for f in os.listdir(gold_dir)
                  if os.path.isfile(os.path.join(gold_dir, f))}
    cand_files = {f for f in os.listdir(cand_dir)
                  if os.path.isfile(os.path.join(cand_dir, f))}

    paired = sorted(gold_files & cand_files)
    missing_candidate = sorted(gold_files - cand_files)   # gold, no candidate
    missing_gold = sorted(cand_files - gold_files)         # candidate, no gold

    results = []
    for fn in paired:
        res = compare_pair(os.path.join(gold_dir, fn),
                            os.path.join(cand_dir, fn))
        res['file'] = fn
        results.append(res)

    return results, missing_candidate, missing_gold


# ---------------------------------------------------------------------------
# Report rendering (shared by the CLI runner and the GUI)
# ---------------------------------------------------------------------------

VERDICT_ORDER = {
    'unmatched': 0,
    'matched-except-header': 1,
    'missing-candidate': 2,
    'missing-gold': 3,
    'matched': 4,
}


def _fmt_row(file, typ, oid, verdict, sections, w):
    t = f'{typ or "?"} {oid or ""}'.strip()
    secs = ', '.join(sections) if sections else ''
    return (f'{file:<{w["file"]}}  {t:<{w["type"]}}  '
            f'{verdict:<{w["verdict"]}}  {secs}')


def build_report(results, missing_candidate, missing_gold):
    """Return the full report as a single string (console, file, and GUI all
    render the identical text).
    """
    rows = []
    for r in results:
        rows.append({
            'file': r['file'], 'type': r.get('type'), 'id': r.get('id'),
            'verdict': r['verdict'], 'sections': r.get('sections', []),
            'diffs': r.get('diffs', []),
            'missing_doc_tags': r.get('missing_doc_tags', []),
        })
    for fn in missing_candidate:
        rows.append({'file': fn, 'type': None, 'id': None,
                     'verdict': 'missing-candidate', 'sections': [],
                     'diffs': [], 'missing_doc_tags': []})
    for fn in missing_gold:
        rows.append({'file': fn, 'type': None, 'id': None,
                     'verdict': 'missing-gold', 'sections': [],
                     'diffs': [], 'missing_doc_tags': []})

    rows.sort(key=lambda r: (VERDICT_ORDER.get(r['verdict'], 9), r['file']))

    if not rows:
        return 'No files found in either folder.'

    w = {
        'file': max([4] + [len(r['file']) for r in rows]),
        'type': max([4] + [len(f'{r["type"] or "?"} {r["id"] or ""}'.strip())
                           for r in rows]),
        'verdict': max(len('matched-except-header'),
                       *[len(r['verdict']) for r in rows]),
    }

    out = []
    header = (f'{"FILE":<{w["file"]}}  {"OBJECT":<{w["type"]}}  '
              f'{"VERDICT":<{w["verdict"]}}  SECTIONS')
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

    detail = [r for r in rows if r['verdict'] in
              ('unmatched', 'matched-except-header')]
    if detail:
        out.append('')
        out.append('=' * len(header))
        out.append('DETAIL (non-matched objects)')
        out.append('=' * len(header))
        for r in detail:
            out.append('')
            out.append(f'### {r["file"]}  [{r["verdict"]}]  '
                       f'sections: {", ".join(r["sections"]) or "-"}')
            if r.get('missing_doc_tags'):
                out.append('  doc-trigger tags in gold but missing from '
                           'candidate: ' + ', '.join(r['missing_doc_tags']))
            for lineno, g, c in r['diffs']:
                gtxt = '<absent>' if g is None else g
                ctxt = '<absent>' if c is None else c
                out.append(f'  line {lineno}:')
                out.append(f'    gold: {gtxt}')
                out.append(f'    cand: {ctxt}')

    return '\n'.join(out)


def needs_attention(results, missing_candidate, missing_gold):
    """True if anything in the run needs a human eye (unmatched or missing)."""
    return bool(
        any(r['verdict'] in ('unmatched', 'missing-candidate', 'missing-gold')
            for r in results)
        or missing_candidate or missing_gold)
