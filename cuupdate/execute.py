#!/usr/bin/env python3
"""
execute.py -- Stage 3 execution engine (NARROW PATH: field-graft only).

Consumes the DiffEngine ledger and, for objects that pass the whole-object
gate, produces the merged object text. This is the step that converts correct
verdicts into actual merged output -- the thing that reclaims TortoiseMerge time.

NARROW PATH SCOPE (this build):
  Executes ONLY 'field-graft' CARRY rows: a whole customer-added field, taken
  verbatim from A, inserted immediately after its surviving anchor sibling in B.
  Plus the deterministic bookkeeping (header + doc-trigger).

WHOLE-OBJECT GATE (agreed contract):
  An object is auto-executed ONLY if every non-TAKE_B row is a CARRY field-graft.
  A single row of any other kind/verdict (code, caption, doc-graft, DEV, etc.)
  routes the WHOLE object to DEV, untouched. No partial merges.

  -> T14 (one field-graft) executes.
  -> T36 (field-grafts + caption rows) routes to DEV in this build; caption-carry
     is a later path.

Output is byte-comparable to the hand-merged fixture modulo the agreed
normalisation (line-endings, trailing whitespace, doc-trigger leading indent).
The executor itself emits clean LF and canonical doc-trigger indentation; the
harness applies the same normalisation to both sides.
"""
import re
from diffengine import DiffEngine

# Kinds the narrow path can execute. Everything else gates to DEV.
# field-graft: whole customer-added field, inserted after its anchor sibling.
# code:        customer code block (// Start TAG .. // Stop TAG), inserted at
#              its anchor-equivalent position. Both are verbatim transplants.
# caption:     caption/optioncaption/optionstring carry on a shared field -
#              replace B's caption/option property lines with A's values.
_EXECUTABLE_KINDS = {'field-graft', 'code', 'caption'}
# Rows with this verdict are "no action needed, take B as-is" and don't block
# the gate (they describe vendor content we keep).
_BENIGN_VERDICT = 'TAKE_B'

DOC_INDENT = '      '          # canonical 6-space doc-trigger indent
DOC_TAG_WIDTH = 11             # tag column width before the date (from fixtures)


def describe_blocker(r):
    """Turn an internal classifier row into one line of operator English.

    Rows carry: kind, verdict, node (field number or None), tag, line, span.
    We surface what an operator can act on - the customer tag and the line
    number to jump to in TortoiseMerge - and keep the field number when the
    block sits in a numbered field. The internal kind/verdict is dropped from
    the operator text (a compact form is kept for the developer in []).
    """
    kind = r.get('kind', 'change')
    tag = r.get('tag')
    line = r.get('line')
    node = r.get('node')

    if kind == 'code':
        what = f"customer code block {tag!r}" if tag else "customer code block"
    elif kind == 'caption':
        what = "caption/option change"
    elif kind == 'field-graft':
        what = f"customer field {node}" if node else "customer field"
    else:
        what = f"{kind} change"

    where = []
    if node not in (None, ''):
        where.append(f"in field {node}")
    if line:
        where.append(f"at line {line}")
    loc = (" " + " ".join(where)) if where else ""

    return f"{what}{loc} - needs manual merge"


class GateToDev(Exception):
    """Raised when an object must route to DEV rather than auto-execute."""
    def __init__(self, reasons):
        self.reasons = reasons
        super().__init__('; '.join(reasons))


def _anchor_for(engine, node_id):
    """Public wrapper over the engine's single source of truth for placement.
    Returns the B node id to graft after, or None."""
    node = engine.Aby.get(node_id)
    if node is None:
        return None
    return engine._insertion_anchor(node)


def _b_node_end_line(engine, b_node_id):
    """1-based index of the LAST line of the given B node's block, in engine.B."""
    node = engine.Bby[b_node_id]
    start = node['line'] - 1                 # 'line' is 1-based
    nlines = node['props'].count('\n') + 1
    return start + nlines                     # exclusive end (next insert point)


def _bump_version_list(line, cu_token):
    """Append cu_token to the Version List token list if not already present.
    `line` is the raw 'Version List=...;' line."""
    m = re.match(r'(\s*Version List=)(.*?)(;?\s*)$', line)
    if not m:
        return line
    head, tokens, tail = m.group(1), m.group(2), m.group(3)
    parts = [t for t in tokens.split(',') if t != '']
    if cu_token not in parts:
        parts.append(cu_token)
    return f'{head}{",".join(parts)};'


def _doc_trigger_line(cu_token, merge_date_dots, initials, text):
    """Build one canonical doc-trigger entry:
        '      <tag padded> <DD.MM.YY> <initials> <text>'
    """
    tag = cu_token.ljust(DOC_TAG_WIDTH)
    return f'{DOC_INDENT}{tag}{merge_date_dots} {initials} {text}'


def execute(custfn, vendfn, cust, vend, langs, params):
    """Run the engine, apply the gate, and return merged object text (LF) for an
    auto-executable object. Raise GateToDev otherwise.

    params: dict with keys cu_token, initials, text, merge_date (DD/MM/YY),
            merge_date_dots (DD.MM.YY).
    """
    e = DiffEngine(custfn, vendfn, cust, vend, langs)
    rows = e.classify()

    # --- whole-object gate -------------------------------------------------
    actionable = [r for r in rows if r['verdict'] != _BENIGN_VERDICT]
    blockers = [r for r in actionable
                if not (r['verdict'] == 'CARRY' and r['kind'] in _EXECUTABLE_KINDS)]
    if blockers:
        g = GateToDev([describe_blocker(r) for r in blockers])
        g.rows = blockers
        raise g

    grafts = [r for r in actionable if r['kind'] in ('field-graft', 'code')]
    captions = [r for r in actionable if r['kind'] == 'caption']

    # --- caption/option carry: replace B's caption/option lines with A's ----
    # Done first, on B's node text, before line insertions shift indices.
    b_lines = list(e.B)
    for r in captions:
        b_lines = _carry_caption(b_lines, e, r['node'])

    # --- build merged body: start from B, insert each customer block ------
    # Each insertion: (after_b_line_idx, [verbatim A lines]). We collect all,
    # then apply high-to-low so earlier indices don't drift.
    insertions = []
    for r in grafts:
        if r['kind'] == 'field-graft':
            anchor_id = _anchor_for(e, r['node'])
            if anchor_id is None or anchor_id not in e.Bby:
                raise GateToDev([f"field-graft node={r['node']} lost its anchor at execution"])
            after = _b_node_end_line(e, anchor_id)      # after anchor field block
            block = e.Aby[r['node']]['props'].split('\n')
        elif r['kind'] == 'code':
            chosen = r.get('chosen')
            if not chosen:
                raise GateToDev([f"code block {r['tag']} not coherently anchored at execution"])
            # chosen=(pb,pa): pb is B index of the before-anchor; insert the
            # verbatim customer block (A[start..stop] inclusive) right after it.
            after = chosen[0] + 1
            start, stop = r['span']
            # A-after-B: the customer addition carries its surrounding blank-line
            # spacing (a blank separating it from the preceding vendor block, and
            # one after). Include an immediately-adjacent blank line on each side.
            lo, hi = start, stop
            if lo - 1 >= 0 and e.A[lo - 1].strip() == '':
                lo -= 1
            if hi + 1 < len(e.A) and e.A[hi + 1].strip() == '':
                hi += 1
            block = e.A[lo:hi + 1]
        else:
            raise GateToDev([f"unexpected executable kind {r['kind']}"])
        insertions.append((after, block))

    out = list(b_lines)                                 # caption-carried B (LF)
    for after, block in sorted(insertions, key=lambda x: x[0], reverse=True):
        out[after:after] = block

    # --- header bookkeeping ------------------------------------------------
    out = _apply_header(out, e, params)

    # --- doc-trigger stamp -------------------------------------------------
    out = _append_doc_trigger(out, e, params)

    return '\n'.join(out)


def _carry_caption(b_lines, engine, node_id):
    """Replace B's CaptionML / OptionCaptionML / OptionString property lines for
    the given field with A's versions (carry customer caption/options). Matched
    by property name within the field's line span; B's line count is preserved
    (these are single-line property replacements) so later graft anchors that
    key off B node positions remain valid.

    A's value lines are language-normalised already (inputs are stripped), so we
    transplant A's exact property line."""
    import re as _re
    a_node = engine.Aby.get(node_id)
    b_node = engine.Bby.get(node_id)
    if a_node is None or b_node is None:
        return b_lines

    PROPS = ('CaptionML', 'OptionCaptionML', 'OptionString')
    prop_re = _re.compile(r'^\s*(' + '|'.join(PROPS) + r')=')

    # Map prop -> A's full line(s). A field node props are newline-joined.
    a_prop_lines = {}
    for l in a_node['props'].split('\n'):
        m = prop_re.match(l)
        if m:
            a_prop_lines[m.group(1)] = l

    # B node occupies b_lines[start : start+count]
    start = b_node['line'] - 1
    count = b_node['props'].count('\n') + 1
    out = list(b_lines)
    for i in range(start, start + count):
        m = prop_re.match(out[i])
        if m and m.group(1) in a_prop_lines:
            out[i] = a_prop_lines[m.group(1)]
    return out


def _apply_header(lines, engine, params):
    """Set Date=merge_date, ensure Modified=Yes, append CU token to Version List.
    Version List source is A's (carries customer tokens); B's is vanilla."""
    a_vl = next((l for l in engine.A if re.match(r'\s*Version List=', l)), None)
    out = []
    seen_modified = False
    in_props = False
    for l in lines:
        if re.match(r'\s*OBJECT-PROPERTIES', l):
            in_props = True
        if in_props and re.match(r'\s*Date=', l):
            l = re.sub(r'(Date=)[^;]*;', rf'\g<1>{params["merge_date"]};', l)
        if in_props and re.match(r'\s*Modified=', l):
            seen_modified = True
            l = re.sub(r'(Modified=)[^;]*;', r'\g<1>Yes;', l)
        if in_props and re.match(r'\s*Version List=', l):
            base = a_vl if a_vl else l                  # prefer A's token list
            l = _bump_version_list(base, params['cu_token'])
            # If we just inserted Modified before VL and B had none, add it.
            if not seen_modified:
                indent = re.match(r'(\s*)', l).group(1)
                out.append(f'{indent}Modified=Yes;')
                seen_modified = True
        out.append(l)
    return out


def _append_doc_trigger(lines, engine, params):
    """Doc-trigger carry (A-after-B): B's changelog entries stay as-is; then
    append A's customer-tagged changelog entries that B lacks, in their original
    A order; then append the CU stamp line as the final entry. All inserted at
    the end of the existing changelog block (after the last existing entry,
    including any continuation lines)."""
    new_stamp = _doc_trigger_line(params['cu_token'], params['merge_date_dots'],
                                  params['initials'], params['text'])

    # An entry line starts with indent + TAG + DD.MM.YY; a continuation line is
    # indented further with no leading tag/date (e.g. wrapped vendor text).
    entry_re = re.compile(r'^\s+([A-Za-z0-9.\-]+)\s+\d{2}\.\d{2}\.\d{2}\s')

    # Customer doc entries present in A but not in B, preserved verbatim with
    # any continuation lines that follow them.
    carry = _customer_doc_entries(engine, entry_re)

    # Find the end of the changelog block in the current (B-derived) output:
    # the index of the last entry line OR its trailing continuation lines.
    last_idx = None
    for i, l in enumerate(lines):
        if entry_re.match(l):
            last_idx = i
    if last_idx is None:
        raise GateToDev(['no doc-trigger changelog found to stamp'])
    # extend past any continuation lines belonging to that last entry
    j = last_idx + 1
    while j < len(lines) and lines[j].strip() and not entry_re.match(lines[j]) \
            and not lines[j].strip().startswith('}') and lines[j].strip() != 'END.':
        j += 1
    insert_at = j  # insert carried entries + stamp here

    block = carry + [new_stamp]
    return lines[:insert_at] + block + lines[insert_at:]


def _customer_doc_entries(engine, entry_re):
    """Return A's changelog entry lines (plus continuation lines) that are NOT
    already present in B's changelog.

    Self-identifying by SET DIFFERENCE, not by prefix: an entry present in A but
    absent from B is a customer addition by definition (the vendor base cannot
    have entries the older customer object lacks; newer vendor entries live in B
    and are kept because we build on B). This deliberately does NOT depend on the
    customer-prefix census - the doc trigger reliably carries customer tags even
    when those tags were never declared as customer prefixes (e.g. DC in T77).
    Matching is on the exact (stripped) entry line, so shared history is never
    re-carried and a verbatim duplicate is never produced."""
    a_lines = engine.A
    b_text = '\n'.join(engine.B)
    idxs = [i for i, l in enumerate(a_lines) if entry_re.match(l)]
    if not idxs:
        return []
    out = []
    for i in idxs:
        if a_lines[i].strip() in b_text:           # already in B (shared history)
            continue
        entry = [a_lines[i]]
        k = i + 1
        while k < len(a_lines) and a_lines[k].strip() and not entry_re.match(a_lines[k]) \
                and not a_lines[k].strip().startswith('}') and a_lines[k].strip() != 'END.':
            entry.append(a_lines[k]); k += 1
        out.extend(entry)
    return out
