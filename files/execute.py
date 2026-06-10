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
# var-option:  option-string VAR (global/local) the customer extended by
#              appending members (B's literal is a strict prefix of A's) - take
#              A's declaration line. RULE 2.
_EXECUTABLE_KINDS = {'field-graft', 'doc-graft', 'code', 'caption', 'var-option'}
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
    elif kind == 'type-unsupported':
        return "object type not yet auto-merged by the tool - manual merge"
    elif kind == 'type-mismatch':
        return "A and B are different object types (or header unreadable) - manual merge"
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


def _global_var_decls(lines):
    """Locate the object-level (global) VAR section and return
    (start_idx, end_idx, {name: full_line}). end_idx is the index of the first
    line after the declarations (a PROCEDURE/closing brace), i.e. the insert
    point. Declarations look like '      <name>@<id> : <type>;'. Returns
    (None, None, {}) if no global VAR section is found.

    The global VAR is the first top-level '    VAR' (four-space indent). Local
    VARs inside procedures are indented deeper or sit after a PROCEDURE header;
    we stop collecting at the first non-decl, non-blank line so we never reach
    into a following procedure."""
    decl = re.compile(r'^      (\w+)@(\d+)\s*:\s*.+;\s*$')
    try:
        i = next(k for k, l in enumerate(lines) if l.rstrip() == '    VAR')
    except StopIteration:
        return None, None, {}
    decls = {}
    j = i + 1
    last_decl = i
    while j < len(lines):
        l = lines[j]
        m = decl.match(l)
        if m:
            decls[m.group(1)] = l
            last_decl = j
        elif l.strip() == '':
            pass
        else:
            break
        j += 1
    return i, last_decl + 1, decls


_VAR_DECL = re.compile(r'^      (\w+)@(\d+)\s*:\s*(.+?);\s*$')
_PROC_HDR = re.compile(r'^    (?:LOCAL )?PROCEDURE\s+\w+@(\d+)\s*\(')


def _var_blocks(lines):
    """Scan EVERY VAR section in the object - the object-level (global) block
    and each LOCAL/PROCEDURE-level block - and return a list of blocks:

        [{'scope': '@global' | '@<procid>',
          'start': <idx of the 'VAR' line>,
          'end':   <insert idx: first line after the last declaration>,
          'decls': {name: (full_line, value)}}, ...]

    A VAR section is a '    VAR' line (four-space indent). Its scope is the
    procedure it belongs to: the global block is the one NOT preceded by a
    PROCEDURE header; a local block is keyed by its owning procedure's @id.
    Locals are scoped PER PROCEDURE - a local 'i' in proc X is unrelated to a
    local 'i' in proc Y - so matching across A and B must compare like scope
    with like scope, never pooling all locals together.

    Declarations are '      <name>@<id> : <type-or-value>;' at six-space indent;
    collection stops at the first non-decl, non-blank line so a block never
    reaches into the following procedure."""
    blocks = []
    cur_scope = '@global'        # before any PROCEDURE header we're in object scope
    i = 0
    while i < len(lines):
        l = lines[i]
        pm = _PROC_HDR.match(l)
        if pm:
            cur_scope = '@' + pm.group(1)
            i += 1
            continue
        if l.rstrip() == '    VAR':
            decls = {}
            j = i + 1
            last = i
            while j < len(lines):
                m = _VAR_DECL.match(lines[j])
                if m:
                    decls[m.group(1)] = (lines[j], m.group(3))
                    last = j
                elif lines[j].strip() == '':
                    pass
                else:
                    break
                j += 1
            blocks.append({'scope': cur_scope, 'start': i,
                           'end': last + 1, 'decls': decls})
            i = j
            continue
        i += 1
    return blocks


def _carry_vars(engine):
    """RULE 1 (keep-over-delete, all scopes). For every VAR block in B - global
    and per-procedure local - carry any declaration present in the MATCHING A
    block but absent from B's, inserted at the end of B's block. Justified by
    the compile-break asymmetry: a variable that is referenced but not declared
    fails to compile, whereas an unused declaration is harmless - so when in
    doubt we keep, never drop. No customer tag exists on a declaration, so this
    relies on no provenance; it only ever ADDS what A has and B lacks.

    Returns (insertions, log):
      insertions: list of (after_idx, [decl lines]) for the executor.
      log:        human-readable lines naming what was carried (silent-but-
                  logged; this rule emits no classify row or gate).

    Matching: A blocks and B blocks are paired by scope. Within a scope a
    declaration is matched by variable NAME (its @id may differ between A and
    B); a name in A's block not in B's block is a customer addition."""
    a_blocks = {b['scope']: b for b in _var_blocks(engine.A)}
    insertions = []
    log = []
    order = {l: k for k, l in enumerate(engine.A)}
    for bb in _var_blocks(engine.B):
        ab = a_blocks.get(bb['scope'])
        if ab is None:
            continue
        added = [n for n in ab['decls'] if n not in bb['decls']]
        if not added:
            continue
        added.sort(key=lambda n: order.get(ab['decls'][n][0], 0))
        added_lines = [ab['decls'][n][0] for n in added]
        insertions.append((bb['end'], added_lines))
        for n in added:
            log.append(f"VAR carry [{bb['scope']}]: + {n} (customer-added, "
                       f"absent from CU) -> kept (compile-safety)")
    return insertions, log


def _carry_var_options(engine):
    """RULE 2 (option-string append carry, all scopes). For a declaration
    present in BOTH the matching A and B VAR blocks at the same NAME where both
    values are single-quoted string literals and B's literal is a STRICT PREFIX
    of A's (the customer appended option members to the end), take A's line.

    This is the option-string-as-text-constant case (e.g. ReportUsage2 on P347:
    the customer extended the inline option list). A non-append value difference
    (a true edit, a re-order, a rename) is NOT a prefix and is deliberately left
    to the whole-object DEV gate - there is no tag to attribute it, so we don't
    guess. Literal (character) prefix, not token prefix: a customer rename of an
    existing member therefore fails the test and routes to DEV, as intended.

    Returns list of (b_line_idx, a_line, name, vendor_changed) where
    vendor_changed flags that B's own value is NOT a prefix-extension of A
    elsewhere - reserved for the ordinal-shift WARN (vendor also changed the
    list mid-stream). Here B IS a prefix of A by construction, so vendor didn't
    change members; vendor_changed stays False (no WARN) for the append case."""
    a_blocks = {b['scope']: b for b in _var_blocks(engine.A)}
    out = []
    for bb in _var_blocks(engine.B):
        ab = a_blocks.get(bb['scope'])
        if ab is None:
            continue
        # B line index for each name in this block: walk the block span.
        for name, (b_line, b_val) in bb['decls'].items():
            if name not in ab['decls']:
                continue
            a_line, a_val = ab['decls'][name]
            if a_val == b_val:
                continue
            # both must be single-quoted string literals
            if not (a_val.startswith("'") and a_val.endswith("'")
                    and b_val.startswith("'") and b_val.endswith("'")):
                continue
            a_inner, b_inner = a_val[1:-1], b_val[1:-1]
            # strict prefix: B's members are the leading run of A's, customer
            # appended more. Equal already filtered above.
            if a_inner.startswith(b_inner) and len(a_inner) > len(b_inner):
                # locate B's physical line index for this declaration
                idx = next((k for k in range(bb['start'], bb['end'])
                            if engine.B[k] == b_line), None)
                if idx is not None:
                    out.append((idx, a_line, name, bb['scope']))
    return out


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

    grafts = [r for r in actionable if r['kind'] in ('field-graft', 'doc-graft', 'code')]
    captions = [r for r in actionable if r['kind'] == 'caption']

    # --- caption/option carry: replace B's caption/option lines with A's ----
    # Done first, on B's node text, before line insertions shift indices.
    b_lines = list(e.B)
    for r in captions:
        b_lines = _carry_caption(b_lines, e, r['node'])

    # --- RULE 2: option-string VAR append carry (global + local) ------------
    # Replace B's declaration line with A's where the customer appended option
    # members (B's literal is a strict prefix of A's). A single-line property
    # replacement, like caption carry - B's line count is preserved so graft
    # anchors keyed off B positions stay valid. The classifier emits a CARRY
    # 'var-option' row per such case (gate + DEV-report visibility); here we
    # apply it. Index is B's own line position (caption carry above changes
    # content, never line count, so indices remain valid).
    for idx, a_line, _name, _scope in _carry_var_options(e):
        if 0 <= idx < len(b_lines):
            b_lines[idx] = a_line

    # --- build merged body: start from B, insert each customer block ------
    # Each insertion: (after_b_line_idx, source_order, [verbatim A lines]).
    # source_order is the block's position in A (1-based line) so that when two
    # grafts share the SAME anchor (e.g. P21 FactBoxes 7 & 9 both anchor after
    # the same surviving B sibling) they are emitted in A-order rather than
    # being inverted by the high-to-low application. Non-graft inserts get a
    # source_order too (their A position) so the global ordering stays sane.
    insertions = []
    for r in grafts:
        # field-graft (explicit customer tag) and doc-graft (doc-trigger
        # justified, no body tag - the common Page control-add form) are
        # mechanically identical: insert the whole customer node verbatim after
        # its surviving anchor sibling in B. Only the justification differs.
        if r['kind'] in ('field-graft', 'doc-graft'):
            anchor_id = _anchor_for(e, r['node'])
            if anchor_id is None or anchor_id not in e.Bby:
                raise GateToDev([f"{r['kind']} node={r['node']} lost its anchor at execution"])
            after = _b_node_end_line(e, anchor_id)      # after anchor field block
            block = e.Aby[r['node']]['props'].split('\n')
            # Pages (and any blank-separated node list) put a blank line between
            # sibling controls. We insert right after the anchor node's closing
            # brace; B already has its own blank AFTER that point, so to keep the
            # grafted node separated from the anchor we carry a LEADING blank
            # when A had one immediately before this node. (Tables pack fields
            # with no blank between them, so A won't have one and nothing is
            # added - leaving the existing Table behaviour unchanged.)
            a_line = e.Aby[r['node']]['line']           # 1-based first line of node in A
            if a_line - 2 >= 0 and e.A[a_line - 2].strip() == '':
                block = [''] + block
            src = a_line
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
            src = start
        else:
            raise GateToDev([f"unexpected executable kind {r['kind']}"])
        insertions.append((after, src, block))

    # --- RULE 1: carry customer VAR declarations (global + local), keep-over-
    # delete. Present in A's matching-scope VAR block, absent from B's. Rides the
    # same insertion list so the high-to-low application keeps indices sane.
    # Silent-but-logged: pure compile-safety, no judgement, no classify row.
    var_ins, var_log = _carry_vars(e)
    for after_v, block_v in var_ins:
        insertions.append((after_v, float('inf'), block_v))   # VAR section: apply last within its anchor

    out = list(b_lines)                                 # caption-carried B (LF)
    # Apply high-to-low by anchor so earlier indices don't drift. For grafts
    # SHARING an anchor, the inner sort by source_order DESC + the reverse outer
    # pass means: at a given anchor we insert the LATER-in-A block first, then
    # the earlier one in front of it -> final on-page order matches A-order.
    for after, _src, block in sorted(insertions, key=lambda x: (x[0], x[1]), reverse=True):
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

    # Description carries the field's tag list (e.g. 'PA032441,DC'). When the
    # customer extends a field's options they also add their tag here. Carry
    # A's Description, but ONLY when B's tags are a subset of A's - i.e. the
    # customer appended tags and the vendor didn't add one of their own that A
    # lacks. If the vendor added a tag A doesn't have, leave B's line alone (a
    # genuine vendor change to preserve; it surfaces as a diff for review).
    desc_re = _re.compile(r'(Description=)([^}\n]*)')

    def _desc_tags(line):
        m = desc_re.search(line)
        return [t.strip() for t in m.group(2).split(',') if t.strip()] if m else None

    # A's Description line (may sit on the same physical line as another prop,
    # e.g. '...OptionString=...; Description=PA032441,DC }'). Keep A's literal
    # value substring so exact spacing is preserved on transplant.
    a_desc_tags = None
    a_desc_literal = None
    for l in a_node['props'].split('\n'):
        m = desc_re.search(l)
        if m:
            a_desc_literal = m.group(2)
            a_desc_tags = [t.strip() for t in m.group(2).split(',') if t.strip()]
            break

    # B node occupies b_lines[start : start+count]
    start = b_node['line'] - 1
    count = b_node['props'].count('\n') + 1
    out = list(b_lines)
    for i in range(start, start + count):
        m = prop_re.match(out[i])
        if m and m.group(1) in a_prop_lines:
            out[i] = a_prop_lines[m.group(1)]
        # Description tag-list carry (subset guard): only when the customer
        # appended tags (B's set is a subset of A's) - never clobber a vendor
        # tag A lacks. Transplant A's literal value to preserve spacing.
        if a_desc_tags is not None and desc_re.search(out[i]):
            b_tags = _desc_tags(out[i]) or []
            if set(b_tags) <= set(a_desc_tags) and a_desc_tags != b_tags:
                out[i] = desc_re.sub(lambda mm: mm.group(1) + a_desc_literal, out[i])
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
