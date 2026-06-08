#!/usr/bin/env python3
"""Structural differ — stage (a): classified node-diff REPORT (no merge writes).

Model (A,B inputs read-only; C = their merge, built later in stage b):
  A = old vendor base + customer code (the customer's current object)
  B = new vendor standard (the CU object)
  C = merge of A and B: B's vendor content + A's customer content, the latter
      re-anchored into B's upgraded context.  Anchors are LOCATED IN B; customer
      content is TAKEN FROM A; nothing is written here (stage a reports only).

Driver = the customer tags named in A's Version List (census-confirmed customer
prefixes).  For each VL customer tag, COLLECT EVERY occurrence across:
   Code  -> tagged // Start/Stop blocks in the CODE section  (scorer's domain; flagged, deferred)
   Tree  -> control/field nodes carrying the tag (customer-prefix Description=/inline)
   Doc   -> documentation-trigger changelog entry (fallback for untagged structural
            changes, plus disambiguation + intent)
NEVER stop at the first location: a tag's work may be split across all three
(e.g. T36 AP001651 = tagged code block + tagged FIELDS nodes + doc entry).

Tag matching is hyphen/dot-insensitive (VL 'WBL009' == body 'WBL-009').  Canonical
form = the VL spelling; drift is FLAGGED here, canonicalised into C in stage (b).
Bare-prefix VL tags (e.g. 'WBL') match by prefix and stay bare.

Verdicts:
  AUTO_GRAFT   clean structural add: customer node A-only, doc/tag confirm 'add',
               surviving same-level insertion anchor located in B.
  DEV          restructure/modify/ambiguous; RDLC/layout touch; add w/o surviving
               anchor; VL tag declared but located nowhere; code blocks (-> scorer).
  TAKE_B       no customer change attributable -> C takes B's version.
"""
import re
from difflib import SequenceMatcher

NODE  = re.compile(r'^\s*\{\s*(\d+)\s*;\s*(\d)?\s*;\s*([A-Za-z]+)')
# two incadea tag comment styles (same as scorer): line '// Start X' and block '{ Start X .. Stop X}'
OPEN  = lambda alt: re.compile(rf'^\s*(?://|\{{)\s*Start\s+({alt})([\w.\-]*)', re.I)
STOP  = lambda alt: re.compile(rf'^\s*(?://\s*)?Stop\s+({alt})([\w.\-]*)\s*\}}?', re.I)
INLINE_TAG = re.compile(r'(?://|\{)\s*Start\s+([A-Za-z][\w.\-]*)')   # detect a tag block inside a node's props
DOC   = re.compile(r'^\s*([A-Za-z]{2,4}[-\.]?[\w.\-]*?)\s+(\d{2}\.\d{2}\.\d{2})\s+([A-Z]{1,3})\s+(.*)$')
ADD_V = re.compile(r'\b(add|added|adds|new|create[d]?)\b', re.I)
RES_V = re.compile(r'\b(divid|restructur|split|moved?|modif|chang|remov|delet|replac|re-?organi|header|footer|layout)', re.I)
RDLC  = re.compile(r'\b(header|footer|layout|rdlc|section|font|logo)\b', re.I)

def norm(l): return re.sub(r'\s+', ' ', l.strip())
def sim(a, b): return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()
def load(fn): return open(fn, encoding='latin-1').read().replace('\r\n', '\n').split('\n')
def cf(tag): return re.sub(r'[-.]', '', tag).upper()          # canonical-fold for matching
def prefix(tag):
    m = re.match(r'^([A-Za-z]+)', tag); return m.group(1).upper() if m else ''


def parse_sections(lines):
    """Return dict of section-name -> (start_idx, end_idx) for FIELDS / CODE etc."""
    secs = {}; cur = None
    for i, l in enumerate(lines):
        m = re.match(r'^\s*(FIELDS|KEYS|CODE|CONTROLS|DATASET|ELEMENTS|PROPERTIES|REQUESTPAGE)\s*$', l)
        if m:
            if cur: secs[cur] = (secs[cur][0], i)
            cur = m.group(1); secs[cur] = (i, len(lines))
    return secs


def parse_controls(lines, lo=0, hi=None):
    """Ordered control/field nodes within [lo,hi): {id,level,type,line,props}."""
    hi = len(lines) if hi is None else hi
    out = []; i = lo
    while i < hi:
        m = NODE.match(lines[i])
        if m:
            node = {'id': m.group(1), 'level': int(m.group(2) or 0),
                    'type': m.group(3), 'line': i + 1, 'props': [lines[i]]}
            depth = lines[i].count('{') - lines[i].count('}'); j = i
            while depth > 0 and j + 1 < hi:
                j += 1; node['props'].append(lines[j])
                depth += lines[j].count('{') - lines[j].count('}')
            node['props'] = '\n'.join(node['props']); out.append(node); i = j + 1
        else:
            i += 1
    return out


def parse_doc_trigger(lines):
    entries = []
    for l in lines:
        m = DOC.match(l)
        if m and not NODE.match(l):
            entries.append({'tag': m.group(1).strip(), 'date': m.group(2),
                            'who': m.group(3), 'desc': m.group(4).strip()})
        elif entries and l.strip().startswith('-'):
            entries[-1]['desc'] += ' ' + l.strip()
    return entries


class StructDiff:
    def __init__(self, custfn, vendfn, customer_prefixes):
        self.A = load(custfn); self.B = load(vendfn)
        self.CUST = {p.upper() for p in customer_prefixes}
        alt = '|'.join(sorted(self.CUST, key=len, reverse=True))
        self.OPEN = OPEN(alt); self.STOP = STOP(alt)
        self.Asec = parse_sections(self.A); self.Bsec = parse_sections(self.B)
        # tree nodes restricted to control regions (FIELDS for tables, CONTROLS for pages)
        self.Anodes = parse_controls(self.A)
        self.Bnodes = parse_controls(self.B)
        self.Bids = {n['id'] for n in self.Bnodes}
        self.doc = parse_doc_trigger(self.A)
        self.vl = self._version_list()
        self.is_report = self.A[0].strip().upper().startswith('OBJECT REPORT')

    def _version_list(self):
        for l in self.A:
            m = re.search(r'Version List=([^;]*)', l)
            if m:
                raw = [t.strip() for t in m.group(1).split(',') if t.strip()]
                return [t for t in raw if prefix(t) in self.CUST]
        return []

    def _code_range(self, lines, sec):
        c = sec.get('CODE'); return c if c else (0, len(lines))

    def code_occurrences(self, vtag):
        """Every // Start / { Start <tag> block in A matching vtag (fold-compared), ANYWHERE
        in the object — customer code blocks live in CODE-section procedures AND in object/field
        triggers under PROPERTIES (e.g. T39 WBL-009 OnRun @31). The scorer handles these blocks;
        the differ only needs to know they EXIST so it does not misroute the tag to a doc-DEV."""
        hits = []
        for i in range(len(self.A)):
            m = self.OPEN.match(self.A[i])
            if m and cf(m.group(1)+m.group(2)) == cf(vtag):
                hits.append({'line': i+1, 'raw': (m.group(1)+m.group(2))})
        return hits

    def tree_occurrences(self, vtag):
        """Control/field nodes in A carrying the customer tag as a node-level Description=
        (structural attribution). Nodes whose tag is a // Start / { Start CODE block inside a
        trigger are NOT returned here — that is tagged code, the scorer's domain (see resolve_tag).
        """
        hits = []
        for n in self.Anodes:
            # node-level Description= attribution only (not code-block tags inside triggers)
            tags = re.findall(r'Description=([^;}\n]+)', n['props'])
            toks = []
            for d in tags: toks += re.split(r'[,\s]+', d)
            if any(cf(t) == cf(vtag) and prefix(t) in self.CUST for t in toks if t):
                # exclude if the same node ALSO contains a customer code block for this tag:
                # then the attribution is the code block's (scorer), not a structural Description.
                node_has_code_block = any(
                    cf(m.group(1)) == cf(vtag) and prefix(m.group(1)) in self.CUST
                    for m in INLINE_TAG.finditer(n['props']))
                if not node_has_code_block:
                    hits.append(n)
        return hits

    def node_has_customer_codeblock(self, vtag):
        """True if some node's props contain a // Start / { Start <vtag> code block (scorer's domain)."""
        for n in self.Anodes:
            for m in INLINE_TAG.finditer(n['props']):
                if cf(m.group(1)) == cf(vtag) and prefix(m.group(1)) in self.CUST:
                    return True
        return False

    def doc_entry(self, vtag):
        for e in self.doc:
            if cf(e['tag']) == cf(vtag) and prefix(e['tag']) in self.CUST:
                return e
        return None

    def _insertion_anchor(self, node):
        """Preceding same-level sibling whose id survives in B -> graft anchor in B."""
        idx = next((k for k, n in enumerate(self.Anodes) if n is node), None)
        if idx is None: return None
        for k in range(idx-1, -1, -1):
            s = self.Anodes[k]
            if s['level'] == node['level'] and s['id'] in self.Bids: return s['id']
            if s['level'] < node['level']: break
        return None

    def resolve_tag(self, vtag):
        """Structural resolution for one VL customer tag. Collect ALL Tree/Doc findings
        (no stop-at-first). Tagged CODE is the SCORER's domain — the differ does not verdict
        it, only notes its presence (so 'found nowhere' and doc-fallback stay correct, and
        drift is flagged). Returns (rows, code_present)."""
        rows = []
        code_blocks = self.code_occurrences(vtag)                 # CODE-section // Start / { Start blocks
        code_in_node = self.node_has_customer_codeblock(vtag)     # tag is a code block inside a trigger
        code_present = bool(code_blocks) or code_in_node
        tree = self.tree_occurrences(vtag)                        # node-level Description= attribution
        doc  = self.doc_entry(vtag)
        drift = sorted({c['raw'] for c in code_blocks if cf(c['raw']) == cf(vtag) and c['raw'] != vtag})

        # TREE occurrences (structural) -> graft eligibility or modify-DEV
        for n in tree:
            anchor = self._insertion_anchor(n)
            a_only = n['id'] not in self.Bids
            doc_ok = (not doc) or (ADD_V.search(doc['desc']) and not RES_V.search(doc['desc']))
            if a_only and anchor and doc_ok:
                rows.append(dict(tag=vtag, loc='Tree', node=n['id'], line=n['line'],
                                 verdict='AUTO_GRAFT', reason=f'A-only field {n["id"]}; anchor after B node {anchor}'))
            else:
                why = ('field present in B -> property modification' if not a_only else
                       'no surviving insertion anchor' if not anchor else 'doc indicates restructure')
                rows.append(dict(tag=vtag, loc='Tree', node=n['id'], line=n['line'],
                                 verdict='DEV', reason=why))

        # DOC fallback -> only when there is NO code and NO structural tree finding for this tag
        if doc and not code_present and not tree:
            if self.is_report and RDLC.search(doc['desc']):
                rows.append(dict(tag=vtag, loc='Doc', node=None, line=None, verdict='DEV',
                                 reason=f'RDLC/layout change (manual): "{doc["desc"][:50]}"'))
            elif RES_V.search(doc['desc']):
                rows.append(dict(tag=vtag, loc='Doc', node=None, line=None, verdict='DEV',
                                 reason=f'restructure doc entry: "{doc["desc"][:50]}"'))
            elif ADD_V.search(doc['desc']):
                names = [x or y for x, y in re.findall(r"'([^']+)'|\"([^\"]+)\"", doc['desc'])]
                match = next((n for n in self.Anodes
                              if n['id'] not in self.Bids
                              and any(nm and nm.lower() in n['props'].lower() for nm in names)), None)
                if match:
                    anchor = self._insertion_anchor(match)
                    rows.append(dict(tag=vtag, loc='Doc', node=match['id'], line=match['line'],
                                     verdict='AUTO_GRAFT' if anchor else 'DEV',
                                     reason=(f'doc-confirmed add; field {match["id"]} A-only; anchor after B node {anchor}'
                                             if anchor else 'doc add but no surviving anchor')))
                else:
                    rows.append(dict(tag=vtag, loc='Doc', node=None, line=None, verdict='DEV',
                                     reason=f'doc add, node not located: "{doc["desc"][:50]}"'))
            else:
                rows.append(dict(tag=vtag, loc='Doc', node=None, line=None, verdict='DEV',
                                 reason=f'ambiguous doc entry: "{doc["desc"][:50]}"'))

        # VL tag declared but located in NEITHER code, tree, nor doc -> suspicious, human call
        if not code_present and not tree and not doc:
            rows.append(dict(tag=vtag, loc='(none)', node=None, line=None, verdict='DEV',
                             reason='declared in Version List but located in neither code, tree, nor doc'))

        for r in rows: r['drift'] = drift
        return rows, code_present

    def report(self):
        """Returns (rows, code_only_tags). rows = structural findings (Tree/Doc).
        code_only_tags = VL tags whose only presence is tagged code -> handled by scorer,
        the differ raises no structural row for them."""
        out = []; code_only = []
        for vtag in self.vl:
            rows, code_present = self.resolve_tag(vtag)
            out += rows
            if code_present and not rows:
                code_only.append(vtag)
        return out, code_only


if __name__ == '__main__':
    OBJS = [('T14','Cust_T14.txt','20206Q1_T14.txt'), ('C80','Cust_C80.txt','20206Q1_C80.txt'),
            ('T36','Cust_T36.txt','20206Q1_T36.txt'), ('R790','Cust_R790.txt','20206Q1_R790.txt'),
            ('P21','Cust_P21.txt','20206Q1_P21.txt'), ('P5025649','Cust_P5025649.txt','20206Q1_P5025649.txt'),
            ('R5025607','Cust_R5025607.txt','20206Q1_R5025607.txt'), ('T38','Cust_T38.txt','20206Q1_T38.txt'),
            ('T39','Cust_T39.txt','20206Q1_T39.txt'), ('T5025400','Cust_T5025400.txt','20206Q1_T5025400.txt')]
    CUST = {'AP', 'WBL'}
    for name, a, b in OBJS:
        sd = StructDiff(a, b, CUST)
        vl = ','.join(sd.vl) if sd.vl else '(none)'
        print(f"\n#### {name}  [{sd.A[0].split(None,2)[1]}]  VL customer tags: {vl}")
        rows, code_only = sd.report()
        if not rows and not code_only:
            print("   (no structural customer change)")
        for r in rows:
            d = f" drift={r['drift']}" if r['drift'] else ""
            n = f" field={r['node']}" if r['node'] else ""
            print(f"   [{r['tag']:9}] {r['loc']:7}{n:13} -> {r['verdict']:12} :: {r['reason']}{d}")
        if code_only:
            print(f"   (code-only, handled by scorer: {', '.join(code_only)})")
