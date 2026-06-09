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
from scorer import Scorer

NODE  = re.compile(r'^\s*\{\s*(\d+)\s*;\s*(\d)?\s*;\s*([A-Za-z]+)')
DOC   = re.compile(r'^\s*([A-Za-z]{2,4}[-\.]?[\w.\-]*?)\s+(\d{2}\.\d{2}\.\d{2})\s+([A-Z]{1,3})\s+(.*)$')
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
        self.is_report = self.A[0].strip().upper().startswith('OBJECT REPORT')

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
        """For an untagged A-only node, find a CUSTOMER doc entry whose quoted name(s) appear
        in the node's props (pages have zero body tags; the doc trigger is the justification).
        Returns (entry, tag) or (None, None)."""
        for e in self.doc:
            if self._layer(e['tag']) != 'customer':
                continue
            names = [x or y for x, y in re.findall(r"'([^']+)'|\"([^\"]+)\"", e['desc'])]
            if any(nm and nm.lower() in node['props'].lower() for nm in names):
                return e, e['tag']
        return None, None

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
        added   = [self.Aby[i] for i in self.Aby if i not in self.Bby]   # in A, not B
        removed = [self.Bby[i] for i in self.Bby if i not in self.Aby]   # in B, not A
        changed = [i for i in self.Aby if i in self.Bby
                   and self._strip_lang(self.Aby[i]['props']) != self._strip_lang(self.Bby[i]['props'])]

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
                rows.append(self._row(n, vtags[0], 'TAKE_B', 'vendor-deletion',
                                      f'A-only field {n["id"]} is vendor-tagged ({vtags[0]}) -> vendor removed it in B'))
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

            if has_codeblock:
                # customer code lives in this shared node's trigger -> scorer decides per block
                sv = self._scorer_verdicts(ctags)
                verdict = 'DEV' if any(v == 'DEV' for _, v in sv) else ('CARRY' if sv else 'SCORER')
                detail = ', '.join(f'{t}:{v}' for t, v in sv) if sv else 'scorer'
                rows.append(self._row(a, ctags[0] if ctags else None, verdict, 'code',
                                      f'field {nid} customer code block -> scorer [{detail}]'))
            elif (cap_changed or opt_changed) and not other_changed:
                # Caption / OptionCaption / OptionString difference, nothing else.
                # RULE (user decision): always carry the customer's caption/option
                # values on any such difference (tag NOT required) - caption drift
                # is low-risk and easy to catch in testing. Option lists carry the
                # customer set; we WARN (not gate) if the vendor changed options
                # mid-list (their set isn't a prefix of the customer's) since that
                # can shift option ordinals - flagged for the tester to eyeball.
                warn = opt_changed and not self._vendor_options_are_prefix(a, b)
                rows.append(dict(node=a['id'], tag=(ctags[0] if ctags else None),
                                 verdict='CARRY', kind='caption', line=a['line'],
                                 reason=f'field {nid} caption/option override: carry customer '
                                        f'caption/optioncaption/optionstring'
                                        + (' [WARN: vendor also changed options mid-list]' if warn else ''),
                                 warn=warn))
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

        # 4) object-level / CODE-section customer code blocks. The scorer scans
        # the WHOLE object and scores every customer Start/Stop block by anchor
        # survival. Blocks that live OUTSIDE any field node (global triggers, the
        # CODE{} procedures) are scored but never surfaced by the per-node loop
        # above. Emit a 'code' row for each such block so the executor can act on
        # it and the whole-object gate can SEE it (never silently drop code).
        emitted_lines = {r['line'] for r in rows if r['kind'] == 'code'}
        for sb in self._scorer_blocks():
            if sb['line'] in emitted_lines:
                continue
            verdict = 'CARRY' if sb['verdict'] == 'TRANSPLANT' else 'DEV'
            node = {'id': None, 'line': sb['line']}
            rows.append(dict(node=None, tag=sb['tag'], verdict=verdict, kind='code',
                             line=sb['line'],
                             reason=f"CODE-section block {sb['tag']} -> scorer "
                                    f"[{sb['content']}:{sb['verdict']} score={sb['score']}]",
                             span=(sb['start'], sb['stop']), chosen=sb['chosen']))
        return rows

    def _caption_base_differs(self, a, b):
        def cap(n):
            m = re.search(r'(?<!Option)CaptionML=\[?([A-Z]{3})=([^;\]\n]+)', n['props'])
            return (m.group(1), norm(m.group(2))) if m else None
        return cap(a) is not None and cap(a) != cap(b)

    def _option_differs(self, a, b):
        """True if OptionCaptionML or OptionString differs between A and B."""
        return (self._opt_caption(a) != self._opt_caption(b)
                or self._opt_string(a) != self._opt_string(b))

    def _opt_caption(self, n):
        m = re.search(r'OptionCaptionML=\[?([A-Z]{3})=([^;\]\n]*)', n['props'])
        return norm(m.group(2)) if m else None

    def _opt_string(self, n):
        m = re.search(r'OptionString=([^;\n]*)', n['props'])
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

