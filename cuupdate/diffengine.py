#!/usr/bin/env python3
"""Difference-driven merge engine (Stage 1/2) — diff finds everything, tag layer justifies each.

Ordering (per design): identify what DIFFERS between A and B FIRST, then justify each
difference by which tag layer explains it. The diff is exhaustive (cannot silently miss a
change); the tag is the justification, not the search key.

  A = old vendor base + customer code (current customer object, read-only)
  B = new vendor standard / CU (read-only)
  C = merge: B's vendor content + A's customer content (built in stage b; this stage REPORTS)

Justification table for each detected difference:
  customer tag explains it          -> CARRY  (customer customisation: caption-carry / field-graft /
                                              code->scorer / restructure->DEV)
  vendor tag explains it            -> TAKE_B (vendor upgrade change)
  A-only region, vendor-tagged      -> TAKE_B (vendor deletion: B dropped it)
  A-only region, customer-tagged    -> CARRY  (customer addition)
  A-only region, UNTAGGED           -> DEV    (cannot justify; never silently lose/guess)
  B-only tag/region                 -> TAKE_B (new tags only ever appear in B = vendor upgrade)
  structural diff, no tag, doc says -> doc-trigger path (pages/reports)
  unexplained / incoherent          -> DEV    (visible safety net)

Code regions are detected here and routed to the SCORER for the TRANSPLANT/DEV decision;
the engine is the front-end that finds every difference and dispatches each.
"""
import re
from difflib import SequenceMatcher
from scorer import Scorer, parse_proc_units

NODE  = re.compile(r'^\s*\{\s*(\d+)\s*;\s*(\d)?\s*;\s*([A-Za-z]+)')
DOC   = re.compile(r'^\s*([A-Za-z]{2,4}[-\.]?[\w.\-]*?)\s+(\d{2}\.\d{2}\.\d{2})\s+([A-Z]{1,3})\s+(.*)$')
# Object declaration: line 1 is `OBJECT <Type> <ID> <Name>` (NAV v14 export).
# Type is read from the body (intrinsic, authoritative) - never from filename
# or folder. A and B must agree on type (a disagreement is a hard DEV gate).
OBJTYPE = re.compile(r'^\s*OBJECT\s+([A-Za-z]+)\s+\d', re.I)

# Per-type handler scope. Each entry declares which difference-classes the
# engine should evaluate for that object type. `validated` gates whether the
# type may auto-merge at all: an un-validated (or unknown) type routes the
# WHOLE object to DEV before any rule runs, so Table rules can never misfire on
# a type we have not proven against real paired objects.
#   fields  - parse/classify { N ; ; } field nodes (field-graft, caption/option)
#   code    - scorer-driven CODE-section / trigger code-block transplant
#   doc     - doc-trigger carry + doc-justified grafts
# Table and Codeunit are validated by the existing fixture suite (T14/T36/T77/
# T80/T81). Page/Report/XMLport are registered but NOT yet validated - they
# gate to DEV until each gets a handler proven against real samples.
HANDLERS = {
    'TABLE':    dict(validated=True,  fields=True,  code=True,  doc=True),
    'CODEUNIT': dict(validated=True,  fields=False, code=True,  doc=True),
    # PAGE: validated. Clean control adds auto-merge (P14, P21V2); vendor-driven
    # caption renames take B; ambiguous vendor-tagged adds (P21) and property
    # modifications (P5025440) still route the OBJECT to DEV via the whole-object
    # gate - so flipping this on does NOT disable safety, it lets CONFIDENT Pages
    # through while uncertain ones are still surfaced for manual merge.
    'PAGE':     dict(validated=True,  fields=True,  code=True,  doc=True),
    'REPORT':   dict(validated=False, fields=True,  code=True,  doc=True),
    'XMLPORT':  dict(validated=False, fields=True,  code=True,  doc=True),
}
_DEFAULT_SCOPE = dict(validated=False, fields=True, code=True, doc=True)
ADD_V = re.compile(r'\b(add|added|adds|new|create[d]?)\b', re.I)
RES_V = re.compile(r'\b(divid|restructur|split|moved?|modif|chang|remov|delet|replac|re-?organi)', re.I)
RDLC  = re.compile(r'\b(header|footer|layout|rdlc|section|font|logo)\b', re.I)

def norm(l): return re.sub(r'\s+', ' ', l.strip())
def sim(a, b): return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()
def load(fn): return open(fn, encoding='latin-1').read().replace('\r\n', '\n').split('\n')
def cf(tag): return re.sub(r'[-.]', '', tag).upper()
def prefix(tag):
    m = re.match(r'^([A-Za-z]+)', tag); return m.group(1).upper() if m else ''


class DiffEngine:
    def __init__(self, custfn, vendfn, customer_prefixes, vendor_prefixes, languages=None):
        self._custfn = custfn; self._vendfn = vendfn
        self.A = load(custfn); self.B = load(vendfn)
        self.CUST = {p.upper() for p in customer_prefixes}
        self.VEND = {p.upper() for p in vendor_prefixes}
        self.LANGS = set(languages or [])               # customer language layer codes (e.g. ENZ)
        alt = '|'.join(sorted(self.CUST | self.VEND, key=len, reverse=True))
        # both tag styles: line '// Start X' and block '{ Start X .. Stop X}'
        self.OPEN = re.compile(rf'^\s*(?://|\{{)\s*Start\s+({alt})([\w.\-]*)', re.I)
        self.STOP = re.compile(rf'^\s*(?://\s*)?Stop\s+({alt})([\w.\-]*)\s*\}}?', re.I)
        self.INLINE = re.compile(rf'(?://|\{{)\s*Start\s+({alt})([\w.\-]*)', re.I)
        self.Anodes = self._parse(self.A); self.Bnodes = self._parse(self.B)
        self.Aby = {n['id']: n for n in self.Anodes}
        self.Bby = {n['id']: n for n in self.Bnodes}
        self.doc = self._parse_doc(self.A)
        self.obj_type, self.type_mismatch = self._detect_type()
        self.scope = HANDLERS.get(self.obj_type, _DEFAULT_SCOPE)

    def _detect_type(self):
        """Object type from line 1 of the body (intrinsic, authoritative).
        Returns (TYPE_UPPER_or_None, mismatch_bool). mismatch is True when A and
        B disagree on type (or A's type is unreadable) - a hard DEV condition,
        since we cannot trust a merge of two differently-typed objects."""
        def t(lines):
            m = OBJTYPE.match(lines[0]) if lines else None
            return m.group(1).upper() if m else None
        ta, tb = t(self.A), t(self.B)
        if ta is None:
            return None, True
        return ta, (tb is not None and tb != ta)

    def _parse(self, lines):
        out = []; i = 0
        while i < len(lines):
            m = NODE.match(lines[i])
            if m:
                node = {'id': m.group(1), 'level': int(m.group(2) or 0),
                        'type': m.group(3), 'line': i + 1, 'props': [lines[i]]}
                depth = lines[i].count('{') - lines[i].count('}'); j = i
                while depth > 0 and j + 1 < len(lines):
                    j += 1; node['props'].append(lines[j])
                    depth += lines[j].count('{') - lines[j].count('}')
                node['props'] = '\n'.join(node['props']); out.append(node); i = j + 1
            else:
                i += 1
        return out

    def _parse_doc(self, lines):
        entries = []
        for l in lines:
            m = DOC.match(l)
            if m and not NODE.match(l):
                entries.append({'tag': m.group(1).strip(), 'date': m.group(2),
                                'who': m.group(3), 'desc': m.group(4).strip()})
            elif entries and l.strip().startswith('-'):
                entries[-1]['desc'] += ' ' + l.strip()
        return entries

    # --- helpers -------------------------------------------------------------
    def _layer(self, tag):
        p = prefix(tag)
        if p in self.CUST: return 'customer'
        if p in self.VEND: return 'vendor'
        return 'unknown'

    def _strip_lang(self, props):
        """Drop the customer language-layer caption lines for comparison (handled separately)."""
        out = []
        for l in props.split('\n'):
            if any(re.search(rf'\b{re.escape(code)}=', l) for code in self.LANGS):
                continue
            out.append(l)
        return out

    def _unit_tags(self, text):
        """Tags appearing in an arbitrary text slice (e.g. a procedure unit):
        inline code-block Start tags only. Used to corroborate ownership of a
        whole-procedure carry. Mirrors the 'code' half of _node_tags."""
        tags = []
        for m in self.INLINE.finditer(text):
            tags.append(('code', m.group(1) + m.group(2)))
        return tags

    def _node_tags(self, node):
        """All tags appearing in a node: inline code-block tags + Description= tokens."""
        tags = []
        for m in self.INLINE.finditer(node['props']):
            tags.append(('code', m.group(1) + m.group(2)))
        for d in re.findall(r'Description=([^;}\n]+)', node['props']):
            for t in re.split(r'[,\s]+', d):
                if t and prefix(t): tags.append(('desc', t))
        return tags

    def _doc_for(self, tag):
        for e in self.doc:
            if cf(e['tag']) == cf(tag) and self._layer(e['tag']) == 'customer':
                return e
        return None

    def _doc_justifies(self, node):
        """For an untagged A-only node, find a CUSTOMER doc entry that names it.
        The doc trigger is the justification when the node carries no body tag
        (Page controls, Table field-adds documented only in the changelog).

        Matched two ways (either direction is sufficient):
          1. a name QUOTED IN THE DOC desc appears in the node props
             (e.g. doc: Added "Foo Bar" -> node has SourceExpr="Foo Bar"); or
          2. the node's own identifier (a Page/Table Field's SourceExpr value,
             or a field's Name) appears BARE in the doc desc
             (e.g. node SourceExpr="E-Mail" -> doc: Added E-Mail field).
        Direction 2 is the common Page form: the customer quotes the field on
        the control, not in the changelog line. Returns (entry, tag) or
        (None, None)."""
        node_names = self._node_identifiers(node)
        for e in self.doc:
            if self._layer(e['tag']) != 'customer':
                continue
            desc = e['desc']
            # direction 1: names quoted in the doc appear in the node
            quoted = [x or y for x, y in re.findall(r"'([^']+)'|\"([^\"]+)\"", desc)]
            if any(nm and nm.lower() in node['props'].lower() for nm in quoted):
                return e, e['tag']
            # direction 2: the node's identifier appears (bare) in the doc text
            dl = desc.lower()
            if any(nm and nm.lower() in dl for nm in node_names):
                return e, e['tag']
        return None, None

    def _node_identifiers(self, node):
        """Distinctive name(s) that identify a node for doc-justification:
        a Field control's SourceExpr value (Pages) and the field Name token
        (Tables - the 3rd ;-delimited column of the node header). Quotes are
        stripped; only reasonably distinctive (len>=2) names are returned so a
        bare 'Code' SourceExpr can't spuriously match unrelated doc prose."""
        names = []
        for m in re.finditer(r'SourceExpr=("([^"]+)"|[^\s;}\n]+)', node['props']):
            v = (m.group(2) or m.group(1)).strip()
            if len(v) >= 2:
                names.append(v)
        # Table field Name: `{ N ; ; Name ; Type ; ... }` - 3rd column
        m = re.match(r'^\s*\{\s*\d+\s*;\s*\d?\s*;\s*([^;]+?)\s*;', node['props'])
        if m and m.group(1) and len(m.group(1).strip()) >= 2:
            names.append(m.group(1).strip())
        return names

    def _insertion_anchor(self, node):
        idx = next((k for k, n in enumerate(self.Anodes) if n['id'] == node['id']), None)
        if idx is None: return None
        for k in range(idx - 1, -1, -1):
            s = self.Anodes[k]
            if s['level'] == node['level'] and s['id'] in self.Bby: return s['id']
            if s['level'] < node['level']: break
        return None

    # --- the difference-driven classification -------------------------------
    def classify(self):
        rows = []

        # --- TYPE FRONT-GATE -------------------------------------------------
        # Detect type from the body and route the WHOLE object to DEV before any
        # rule runs when (a) A and B disagree on type / type is unreadable, or
        # (b) the type has no validated handler yet (Page/Report/XMLport).
        # This is the safety property that lets per-type handlers ship
        # incrementally: a type we have not proven can never get the wrong rules
        # run on it - it is surfaced for manual merge instead.
        if self.type_mismatch:
            rows.append(dict(node=None, tag=None, verdict='DEV', kind='type-mismatch',
                             line=1,
                             reason=f'A/B object-type disagreement or unreadable header '
                                    f'(A={self.obj_type!r}) -> human review'))
            return rows
        if not self.scope['validated']:
            rows.append(dict(node=None, tag=None, verdict='DEV', kind='type-unsupported',
                             line=1,
                             reason=f'object type {self.obj_type!r} has no validated '
                                    f'handler yet -> human review'))
            return rows

        fields_with_code = []   # field ids whose trigger holds customer code,
                                # to assert the scorer pass covered each one
        # Field-node classification (steps 1-3) runs only for types whose
        # handler declares `fields`. Code-only types (Codeunit) skip straight to
        # the CODE-section scorer pass (step 4). For a Codeunit these sets are
        # empty anyway (no field nodes); gating makes the intent explicit and
        # prevents field rules ever running on a non-field type.
        if self.scope['fields']:
            added   = [self.Aby[i] for i in self.Aby if i not in self.Bby]   # in A, not B
            removed = [self.Bby[i] for i in self.Bby if i not in self.Aby]   # in B, not A
            changed = [i for i in self.Aby if i in self.Bby
                       and self._strip_lang(self.Aby[i]['props']) != self._strip_lang(self.Bby[i]['props'])]
        else:
            added = removed = changed = []

        # 1) A-only nodes: justify by tag layer, then by doc trigger
        for n in added:
            # for a WHOLE new field, identity is its Description tag (the field-level attribution);
            # any code block inside travels with the field (no separate scorer anchor needed).
            desc_ctags = [t for k, t in self._node_tags(n) if k == 'desc' and self._layer(t) == 'customer']
            code_ctags = [t for k, t in self._node_tags(n) if k == 'code' and self._layer(t) == 'customer']
            vtags = [t for k, t in self._node_tags(n) if self._layer(t) == 'vendor']
            ctag = desc_ctags[0] if desc_ctags else (code_ctags[0] if code_ctags else None)
            doc_e, doc_tag = self._doc_justifies(n)
            if ctag:
                anchor = self._insertion_anchor(n)
                doc = self._doc_for(ctag)
                restruct = doc and RES_V.search(doc['desc']) and not ADD_V.search(doc['desc'])
                if anchor and not restruct:
                    rows.append(self._row(n, ctag, 'CARRY', 'field-graft',
                                          f'A-only field {n["id"]}, customer tag {ctag}; graft whole field after B {anchor}'))
                else:
                    rows.append(self._row(n, ctag, 'DEV', 'field-graft',
                                          'A-only customer field but ' + ('restructure per doc' if restruct else 'no surviving anchor')))
            elif doc_e:
                # customer doc entry justifies it -> takes priority over a (possibly misleading)
                # vendor Description tag on the field. The doc trigger is the customer's change manifest.
                anchor = self._insertion_anchor(n)
                restruct = RES_V.search(doc_e['desc']) and not ADD_V.search(doc_e['desc'])
                if anchor and not restruct:
                    rows.append(self._row(n, doc_tag, 'CARRY', 'doc-graft',
                                          f'A-only field {n["id"]} untagged but doc {doc_tag} confirms add; graft after B {anchor}'))
                else:
                    rows.append(self._row(n, doc_tag, 'DEV', 'doc-graft',
                                          f'doc {doc_tag} ({"restructure" if restruct else "no anchor"}) -> human review'))
            elif vtags:
                # An A-only node carrying ONLY a vendor tag is ambiguous: it
                # could be a genuine vendor deletion (vendor removed it in B) OR
                # a customer-added control that happens to wear a vendor
                # Description tag (seen on P21: customer FactBoxes 7/9/13/14 tagged
                # PA035597 but documented under customer entry AP-2362). From the
                # node alone we cannot tell these apart, and silently taking B
                # would DROP a customer addition - violating "never silently lose
                # a whole customer element". So route the OBJECT to DEV for a
                # human to decide. (No current fixture exercised the old silent
                # TAKE_B path; revisit if a real vendor-deletion case wants it.)
                rows.append(self._row(n, vtags[0], 'DEV', 'vendor-deletion',
                                      f'A-only field {n["id"]} carries only a vendor tag ({vtags[0]}) '
                                      f'- ambiguous (vendor deletion vs customer add w/ vendor tag) -> human review'))
            else:
                # whole untagged A-only field, no doc -> DEV (can fail silently; keep safe)
                rows.append(self._row(n, None, 'DEV', 'untagged-A-only',
                                      f'A-only field {n["id"]} untagged & undocumented -> human review'))

        # 2) B-only nodes: new in B = vendor upgrade -> take B (no action, but reported)
        for n in removed:
            rows.append(self._row(n, None, 'TAKE_B', 'vendor-upgrade',
                                  f'field {n["id"]} only in B -> vendor upgrade content, take B'))

        # 3) changed nodes: justify the change(s) by tag layer
        for nid in changed:
            a, b = self.Aby[nid], self.Bby[nid]
            ctags = [t for k, t in self._node_tags(a) if self._layer(t) == 'customer']
            has_codeblock = any(self._layer(m.group(1)) == 'customer'
                                for m in self.INLINE.finditer(a['props']))
            cap_changed = self._caption_base_differs(a, b)
            opt_changed = self._option_differs(a, b)
            other_changed = self._nonlang_noncaption_differs(a, b)
            # If the vendor touched this node in the CU (B has a vendor tag A
            # lacks), a caption/option difference is VENDOR-DRIVEN - the customer
            # just has the older vendor text. Suppress the customer caption-carry
            # so B's (renamed) caption is taken. Without this, the Table-era
            # "always carry customer caption" rule clobbers vendor renames on
            # Pages (P21: 'Quick Customer' -> vendor's 'New Quick Customer').
            if (cap_changed or opt_changed) and self._vendor_touched_node(a, b):
                cap_changed = opt_changed = False

            if has_codeblock:
                # Customer code lives in this shared node's trigger. The
                # whole-object scorer pass (below) scans EVERY Start/Stop block
                # in the object - including ones inside field triggers - and
                # emits a properly anchored 'code' row for each. Emitting a row
                # here too produced a duplicate with the FIELD's line and no
                # span/anchor, which (a) never deduped against the scorer row
                # (different line) and (b) crashed the gate as "not coherently
                # anchored". So we do NOT emit an executable code row here; we
                # just remember the field so we can assert the scorer covered it.
                fields_with_code.append(nid)
                # A field can have BOTH a code block AND a caption/option change
                # (e.g. an OptionString extended alongside a new CASE branch in
                # its OnValidate). The code is handled by the scorer. Here
                # 'other_changed' is necessarily True (the trigger differs by the
                # code block), so we must NOT apply the usual 'and not
                # other_changed' guard - that other change is explained by the
                # code. Carry the caption/option whenever it differs.
                if cap_changed or opt_changed:
                    rows.append(self._caption_row(a, b, nid, ctags, cap_changed, opt_changed))
            elif (cap_changed or opt_changed) and not other_changed:
                rows.append(self._caption_row(a, b, nid, ctags, cap_changed, opt_changed))
            elif ctags and other_changed:
                rows.append(self._row(a, ctags[0], 'DEV', 'property-modify',
                                      f'field {nid} customer-tagged property change beyond caption -> human review'))
            elif other_changed:
                # changed beyond caption/option, no customer tag -> vendor upgrade
                rows.append(self._row(a, None, 'TAKE_B', 'vendor-change',
                                      f'field {nid} differs (non-caption) but no customer tag -> take B'))
            else:
                rows.append(self._row(a, ctags[0] if ctags else None, 'TAKE_B', 'vendor-change',
                                      f'field {nid} no material customer difference -> take B'))

        # 3b) proc-graft: a whole customer PROCEDURE absent from B. Identity is
        # name@id; a procedure present in A but with no matching key in B can
        # only be a customer addition (the vendor never had it to upgrade). We
        # carry the ENTIRE unit verbatim - attribute line ([Internal] etc.),
        # signature, VAR block and BEGIN..END - as one atom, A-after-B at the
        # end of the CODE section. The anchor scorer is the wrong instrument
        # here: the block inside the proc body has NO vendor neighbour to
        # bracket against (the proc doesn't exist in B), so it always scored 0
        # and gated. Ownership is proven structurally (absent from B) and
        # CORROBORATED by a customer tag in the unit - we require the customer
        # tag so a vendor procedure the customer merely retained from an older
        # base (renamed in B) is NOT mis-carried as a duplicate.
        owned_spans = []      # (start,stop) 0-based A-line spans already carried
                              # by a structural atom (added field / proc-graft);
                              # scorer code blocks inside these are covered.
        # added customer fields already grafted (their triggers travel with them)
        graft_ids = {r['node'] for r in rows
                     if r['kind'] in ('field-graft', 'doc-graft') and r['verdict'] == 'CARRY'}
        for nid in graft_ids:
            nd = self.Aby.get(nid)
            if nd:
                s = nd['line'] - 1
                owned_spans.append((s, s + nd['props'].count('\n')))

        ua = self._proc_units(self.A)
        ub = self._proc_units(self.B)
        for key, u in ua.items():
            if key in ub:
                continue                      # vendor has it -> not a customer add
            tags = [t for k, t in self._unit_tags(u['text'])
                    if self._layer(t) == 'customer']
            if not tags:
                # absent from B but no customer tag: ambiguous (could be a vendor
                # proc renamed in B). Don't guess - leave to the whole-object gate
                # via the existing scorer path / DEV. We simply don't claim it.
                continue
            rows.append(dict(node=None, tag=tags[0], verdict='CARRY', kind='proc-graft',
                             line=u['start'] + 1,
                             reason=f"customer procedure {key} absent from B "
                                    f"(tag {tags[0]}) -> graft whole procedure A-after-B",
                             span=(u['start'], u['end']), proc_key=key))
            owned_spans.append((u['start'], u['end']))

        # 4) object-level / CODE-section customer code blocks. The scorer scans
        # the WHOLE object and scores every customer Start/Stop block by anchor
        # survival. Blocks that live OUTSIDE any field node (global triggers, the
        # CODE{} procedures) are scored but never surfaced by the per-node loop
        # above. Emit a 'code' row for each such block so the executor can act on
        # it and the whole-object gate can SEE it (never silently drop code).
        # SUPPRESS blocks already covered by a structural atom (an added customer
        # field grafted whole, or a proc-graft): scoring them by anchor is
        # meaningless (no vendor neighbour) and would gate the object on code
        # that is in fact carried verbatim with its enclosing unit.
        def _covered(sb):
            return any(s <= sb['start'] and sb['stop'] <= e for s, e in owned_spans)
        emitted_lines = {r['line'] for r in rows if r['kind'] == 'code'}
        for sb in self._scorer_blocks():
            if sb['line'] in emitted_lines:
                continue
            if _covered(sb):
                continue                      # carried by its enclosing owned unit
            verdict = 'CARRY' if sb['verdict'] == 'TRANSPLANT' else 'DEV'
            node = {'id': None, 'line': sb['line']}
            rows.append(dict(node=None, tag=sb['tag'], verdict=verdict, kind='code',
                             line=sb['line'],
                             reason=f"CODE-section block {sb['tag']} -> scorer "
                                    f"[{sb['content']}:{sb['verdict']} score={sb['score']}]",
                             span=(sb['start'], sb['stop']), chosen=sb['chosen']))

        # Safety net: every field we saw customer code in (above) should now be
        # covered by at least one scorer-emitted code row. If the scorer somehow
        # produced none for the whole object yet a field clearly had a customer
        # block, surface that as DEV rather than silently dropping it.
        if fields_with_code and not any(r['kind'] == 'code' for r in rows):
            for nid in fields_with_code:
                a = self.Aby[nid]
                ctags = [t for k, t in self._node_tags(a) if self._layer(t) == 'customer']
                rows.append(self._row(a, ctags[0] if ctags else None, 'DEV', 'code',
                                      f'field {nid} customer code block not resolved by scorer -> human review'))

        # 5) option-string VAR append carry (global + local). A declaration in
        # BOTH A and B (same name, same scope) whose value is a single-quoted
        # string literal that the customer EXTENDED by appending members (B's
        # literal is a strict prefix of A's). Take A's. Other value differences
        # (true edits, re-orders) are not prefixes -> not emitted here -> they
        # fall to the whole-object DEV gate (no tag exists to attribute them).
        for vo in self._var_option_carries():
            rows.append(dict(node=None, tag=None, verdict='CARRY', kind='var-option',
                             line=vo['b_line_no'],
                             reason=f"VAR {vo['name']} [{vo['scope']}] option list "
                                    f"extended by customer (CU value is a prefix) "
                                    f"-> carry customer declaration"))
        return rows

    # ---- VAR-section scan (global + per-procedure local) -------------------
    _VAR_DECL = re.compile(r'^      (\w+)@(\d+)\s*:\s*(.+?);\s*$')
    _PROC_HDR = re.compile(r'^    (?:LOCAL )?PROCEDURE\s+\w+@(\d+)\s*\(')
    # NOTE: procedure-unit parsing (and its name@id / attribute-line regexes)
    # lives in scorer.parse_proc_units - a SINGLE shared implementation used by
    # both modules so they cannot drift. An optional attribute line
    # ([Internal]/[Integration]/[External]/[Event...]) directly above a
    # signature is carried WITH the procedure as one atom.

    def _proc_units(self, lines):
        """Delegates to the shared scorer.parse_proc_units. Returns
        {name@id: {'name','id','start','end','local','text'}} for every
        CODE-section procedure; identity is name@id so a customer procedure
        absent from B is detectable by key difference."""
        return parse_proc_units(lines)

    def _var_blocks(self, lines):
        """Return [{'scope', 'decls': {name: (line_idx, value)}}] for every VAR
        section: the object-level block ('@global') and each procedure-level
        block (keyed by the owning procedure @id). Locals are scoped per
        procedure - never pooled - so cross-A/B matching compares like scope."""
        blocks = []
        scope = '@global'
        i = 0
        while i < len(lines):
            pm = self._PROC_HDR.match(lines[i])
            if pm:
                scope = '@' + pm.group(1); i += 1; continue
            if lines[i].rstrip() == '    VAR':
                decls = {}; j = i + 1
                while j < len(lines):
                    m = self._VAR_DECL.match(lines[j])
                    if m:
                        decls[m.group(1)] = (j, m.group(3))
                    elif lines[j].strip() == '':
                        pass
                    else:
                        break
                    j += 1
                blocks.append({'scope': scope, 'decls': decls}); i = j; continue
            i += 1
        return blocks

    def _var_option_carries(self):
        """Rule-2 cases: declaration in both A and B (matched scope + name),
        both values single-quoted literals, B's a STRICT prefix of A's."""
        a_blocks = {b['scope']: b for b in self._var_blocks(self.A)}
        out = []
        for bb in self._var_blocks(self.B):
            ab = a_blocks.get(bb['scope'])
            if ab is None:
                continue
            for name, (b_idx, b_val) in bb['decls'].items():
                if name not in ab['decls']:
                    continue
                _, a_val = ab['decls'][name]
                if a_val == b_val:
                    continue
                if not (a_val.startswith("'") and a_val.endswith("'")
                        and b_val.startswith("'") and b_val.endswith("'")):
                    continue
                ai, bi = a_val[1:-1], b_val[1:-1]
                if ai.startswith(bi) and len(ai) > len(bi):
                    out.append({'name': name, 'scope': bb['scope'],
                                'b_line_no': b_idx + 1})
        return out

    def _caption_row(self, a, b, nid, ctags, cap_changed, opt_changed):
        """Build a caption/option CARRY row. RULE (user decision): always carry
        the customer's caption/option values on any such difference (tag not
        required) - caption drift is low-risk and easy to catch in testing.
        Option lists carry the customer set; WARN (not gate) if the vendor
        changed options mid-list (their set isn't a prefix of the customer's)
        since that can shift option ordinals - flagged for the tester."""
        warn = opt_changed and not self._vendor_options_are_prefix(a, b)
        return dict(node=a['id'], tag=(ctags[0] if ctags else None),
                    verdict='CARRY', kind='caption', line=a['line'],
                    reason=f'field {nid} caption/option override: carry customer '
                           f'caption/optioncaption/optionstring'
                           + (' [WARN: vendor also changed options mid-list]' if warn else ''),
                    warn=warn)

    def _caption_base_differs(self, a, b):
        def cap(n):
            # stop the value at ; ] } or newline: on a Page control a single-
            # value caption can be the LAST property before the closing brace
            # with no trailing ';', so '}' must terminate the capture or the
            # brace leaks into the value and falsely reads as a caption change.
            m = re.search(r'(?<!Option)CaptionML=\[?([A-Z]{3})=([^;\]}\n]+)', n['props'])
            return (m.group(1), norm(m.group(2))) if m else None
        return cap(a) is not None and cap(a) != cap(b)

    def _option_differs(self, a, b):
        """True if OptionCaptionML or OptionString differs between A and B."""
        return (self._opt_caption(a) != self._opt_caption(b)
                or self._opt_string(a) != self._opt_string(b))

    def _vendor_touched_node(self, a, b):
        """True when B's Description carries a VENDOR tag that A's does not -
        i.e. the vendor modified this node in the CU. On a shared node this is
        the signal that a caption/property difference is VENDOR-DRIVEN (the
        vendor renamed it), not a customer override: the customer's value is
        merely the older vendor text. Evidence: P21 control 1109400039/41 -
        vendor renamed 'Quick Customer' -> 'New Quick Customer' and added tag
        EU.0200720.199642 in B; the customer still has the old caption. Carrying
        the customer caption there would CLOBBER the vendor rename, so we take B.
        Compared by TAG (the @id/suffix can vary)."""
        def vtags(n):
            return {cf(t) for k, t in self._node_tags(n)
                    if k == 'desc' and self._layer(t) == 'vendor'}
        return bool(vtags(b) - vtags(a))

    def _opt_caption(self, n):
        m = re.search(r'OptionCaptionML=\[?([A-Z]{3})=([^;\]}\n]*)', n['props'])
        return norm(m.group(2)) if m else None

    def _opt_string(self, n):
        m = re.search(r'OptionString=([^;}\n]*)', n['props'])
        return norm(m.group(1)) if m else None

    def _vendor_options_are_prefix(self, a, b):
        """True if B's (vendor) OptionString is a prefix of A's (customer) one,
        i.e. the customer only APPENDED options and the vendor changed nothing
        mid-list. When False, vendor touched options mid-list -> ordinal shift
        risk -> WARN (carry still proceeds per user rule)."""
        av, bv = self._opt_string(a), self._opt_string(b)
        if av is None or bv is None:
            return True                       # no option string to worry about
        ao = av.split(','); bo = bv.split(',')
        return ao[:len(bo)] == bo             # B is a prefix of A

    def _nonlang_noncaption_differs(self, a, b):
        def keyset(n):
            s = self._strip_lang(n['props'])
            txt = '\n'.join(s)
            txt = re.sub(r'OptionCaptionML=\[?[A-Z]{3}=[^;\]\n]*;?', '', txt)  # drop option caption
            txt = re.sub(r'OptionString=[^;\n]*;?', '', txt)                  # drop option string
            txt = re.sub(r'CaptionML=\[?[A-Z]{3}=[^;\]\n]+;?', '', txt)       # drop caption
            txt = re.sub(r'Description=[^;}\n]+', '', txt)                    # drop tag-bearing Description
            return norm(txt)
        return keyset(a) != keyset(b)

    def _scorer_blocks(self):
        """Return the scorer's full per-block results for the whole object,
        each with tag, line (1-based start), span (0-based start,stop), content
        class, score and verdict. Used to surface CODE-section blocks as rows."""
        if not hasattr(self, '_sblocks'):
            self._sblocks = []
            try:
                sc = Scorer(self._custfn, self._vendfn, self.CUST, self.CUST | self.VEND)
                for b in sc.blocks():
                    r = sc.score_block(b)
                    self._sblocks.append(dict(tag=r['tag'], line=r['line'],
                                              span=(b['start'], b['stop']),
                                              content=r['content'], score=r['score'],
                                              verdict=r['verdict'], chosen=r.get('chosen')))
            except Exception:
                self._sblocks = []
        # normalise key name expected by caller
        return [dict(tag=s['tag'], line=s['line'], start=s['span'][0],
                     stop=s['span'][1], content=s['content'], score=s['score'],
                     verdict=s['verdict'], chosen=s['chosen']) for s in self._sblocks]

    def _scorer_verdicts(self, tags):
        """Run the anchor scorer once (cached) and return [(tag, verdict)] for the given
        customer tags. The scorer owns the TRANSPLANT/DEV decision for code blocks."""
        if not hasattr(self, '_scache'):
            self._scache = {}
            try:
                sc = Scorer(self._custfn, self._vendfn, self.CUST, self.CUST | self.VEND)
                for b in sc.blocks():
                    r = sc.score_block(b)
                    self._scache.setdefault(cf(r['tag']), []).append(
                        'CARRY' if r['verdict'] == 'TRANSPLANT' else 'DEV')
            except Exception:
                self._scache = {}
        out = []
        for t in tags:
            for v in self._scache.get(cf(t), []):
                out.append((t, v))
        return out

    def _row(self, node, tag, verdict, kind, reason):
        return dict(node=node['id'] if node else None, tag=tag, verdict=verdict,
                    kind=kind, line=node['line'] if node else None, reason=reason)

