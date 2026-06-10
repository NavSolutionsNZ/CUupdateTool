#!/usr/bin/env python3
"""
test_diffengine.py -- known-answer harness for the difference engine.

Two assertion layers:
  1. VERDICT layer: for each object, the set of non-TAKE_B (node, kind, verdict)
     rows matches the signed-off expectation (the §8.3 cases + our T14/T36 work).
  2. EXECUTION layer: for gated-executable objects, execute.execute() reproduces
     the hand-merged fixture byte-for-byte after agreed normalisation.

Normalisation (applied to BOTH sides before comparing execution output):
  - line endings -> LF
  - trailing whitespace stripped per line
  - doc-trigger entry leading whitespace canonicalised to 6 spaces
These are TortoiseMerge/editor artifacts, not merge convention (agreed).
"""
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'cuupdate'))
from diffengine import DiffEngine
import execute as ex

CUST = {'AP', 'WBL'}
VEND = {'PA', 'PPA', 'EU', 'INC', 'IMM', 'PS'}
LANGS = {'ENZ'}

# Per-object customer-prefix overrides (census differs per customer/object).
# T77's customisations are DC-tagged (Direct Credit), so DC must be a customer
# prefix for it. Defaults to CUST when an object isn't listed here.
CUST_OVERRIDE = {
    'T77': {'AP', 'WBL', 'DC'},
    'T80': {'AP', 'WBL', 'DC'},
    'T81': {'AP', 'WBL', 'DC'},
}


def _cust_for(name):
    return CUST_OVERRIDE.get(name, CUST)


PARAMS = dict(cu_token='CU26Q1', initials='RL', text='CU upgrade.',
              merge_date='08/06/26', merge_date_dots='08.06.26')

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')

# ---- expected non-TAKE_B verdicts (node, kind, verdict) --------------------
from collections import Counter

EXPECTED_VERDICTS = {
    'T14': Counter({(50000, 'field-graft', 'CARRY'): 1,
                    (None,  'code',        'CARRY'): 2}),   # AP001651, WBL
    'T36': Counter({(50090, 'field-graft', 'CARRY'): 1,
                    (50091, 'field-graft', 'CARRY'): 1,
                    (50096, 'field-graft', 'CARRY'): 1,
                    (50097, 'field-graft', 'CARRY'): 1,
                    (11,    'caption',     'CARRY'): 1,
                    (100,   'caption',     'CARRY'): 1,
                    (None,  'code',        'DEV'):   3,     # AP001691 x2, AP001651
                    (None,  'code',        'CARRY'): 1}),   # AP2263
    'T77': Counter({(1, 'caption', 'CARRY'): 1}),           # OptionCaption/String carry
    'T80': Counter({(9,    'caption', 'CARRY'): 1,          # option + Description carry
                    (None, 'code',    'CARRY'): 1}),        # DC5.00 block transplant
    'T81': Counter({(50000, 'field-graft', 'CARRY'): 1,     # AP field
                    (None,  'code',        'CARRY'): 1}),   # DC5.00 block; global VAR
                                                            # carry is execution-layer
}

# Objects that should auto-execute, and the fixture they must reproduce.
EXEC_CASES = {
    'T14': (os.path.join(FIX, 'Cust_T14.stripped.txt'),
            os.path.join(FIX, '20206Q1_T14.stripped.txt'),
            os.path.join(FIX, 'Merged_T14.stripped.txt')),
    'T77': (os.path.join(FIX, 'EX-T77.stripped.txt'),
            os.path.join(FIX, 'CU-T77.stripped.txt'),
            os.path.join(FIX, 'MyMerged-T77.stripped.txt')),
    'T80': (os.path.join(FIX, 'EX-T80.stripped.txt'),
            os.path.join(FIX, 'CU-T80.stripped.txt'),
            os.path.join(FIX, 'MyMerged-T80.stripped.txt')),
    'T81': (os.path.join(FIX, 'EX-T81.stripped.txt'),
            os.path.join(FIX, 'CU-T81.stripped.txt'),
            os.path.join(FIX, 'MyMerged-T81.stripped.txt')),
}
# Objects that should route to DEV in the narrow build (not execute).
EXEC_GATED_TO_DEV = ['T36']

# ---- type-dispatch layer (commit 1) ----------------------------------------
# Real sample pairs (samples/, not fixtures/) exercising the per-type front
# gate: type is read from line 1 of the body; validated types (Table/Codeunit)
# proceed; un-validated types (Page/Report) route the WHOLE object to DEV.
SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'samples')


def _spair(stem):
    return (os.path.join(SAMPLES, f'Cust_{stem}.txt'),
            os.path.join(SAMPLES, f'20206Q1_{stem}.txt'))


# stem -> (expected_type, expected_validated)
TYPE_CASES = {
    'T14':      ('TABLE',    True),
    'C80':      ('CODEUNIT', True),
    'P21':      ('PAGE',     False),
    'P5025649': ('PAGE',     False),
    'R790':     ('REPORT',   False),
}

# Source objects for the verdict layer (stripped fixtures where present, else raw)
OBJ = {
    'T14': (os.path.join(FIX, 'Cust_T14.stripped.txt'),
            os.path.join(FIX, '20206Q1_T14.stripped.txt')),
    'T36': (os.path.join(FIX, 'Cust_T36.stripped.txt'),
            os.path.join(FIX, '20206Q1_T36.stripped.txt')),
    'T77': (os.path.join(FIX, 'EX-T77.stripped.txt'),
            os.path.join(FIX, 'CU-T77.stripped.txt')),
    'T80': (os.path.join(FIX, 'EX-T80.stripped.txt'),
            os.path.join(FIX, 'CU-T80.stripped.txt')),
    'T81': (os.path.join(FIX, 'EX-T81.stripped.txt'),
            os.path.join(FIX, 'CU-T81.stripped.txt')),
}


def _norm(text):
    out = []
    for l in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        l = l.rstrip()
        # canonicalise doc-trigger entries: 6-space indent, tag padded to 11,
        # internal whitespace (incl. TortoiseMerge tabs) collapsed to one space.
        m = re.match(r'^\s+([A-Za-z0-9.\-]+)\s+(\d{2}\.\d{2}\.\d{2}\s.*)$', l)
        if m:
            l = '      ' + m.group(1).ljust(11) + m.group(2)
        out.append(l)
    return '\n'.join(out)


def _verdict_set(name, a, b):
    e = DiffEngine(a, b, _cust_for(name), VEND, LANGS)
    rows = e.classify()
    out = Counter()
    for r in rows:
        if r['verdict'] != 'TAKE_B':
            nid = r['node']
            try:
                nid = int(nid)
            except (TypeError, ValueError):
                pass
            out[(nid, r['kind'], r['verdict'])] += 1
    return out


def run():
    fails = []

    # ---- verdict layer ----
    for name, (a, b) in OBJ.items():
        got = _verdict_set(name, a, b)
        want = EXPECTED_VERDICTS[name]
        if got != want:
            _k = lambda kv: (str(kv[0][0]), kv[0][1], kv[0][2])
            fails.append(f"[verdict] {name}: got {sorted(got.items(), key=_k)} "
                         f"want {sorted(want.items(), key=_k)}")
        else:
            print(f"[verdict] {name}: OK ({sum(got.values())} rows)")

    # ---- execution layer: must reproduce fixture ----
    for name, (a, b, merged) in EXEC_CASES.items():
        try:
            out = ex.execute(a, b, _cust_for(name), VEND, LANGS, PARAMS)
        except ex.GateToDev as g:
            fails.append(f"[exec] {name}: unexpectedly gated to DEV ({g})")
            continue
        with open(merged, encoding='latin-1') as f:
            want = f.read()
        if _norm(out) != _norm(want):
            fails.append(f"[exec] {name}: output != fixture (see diff dump)")
            _dump_diff(name, _norm(out), _norm(want))
        else:
            print(f"[exec] {name}: OK (reproduces fixture)")

    # ---- execution layer: must gate to DEV ----
    for name in EXEC_GATED_TO_DEV:
        a, b = OBJ[name]
        try:
            ex.execute(a, b, _cust_for(name), VEND, LANGS, PARAMS)
            fails.append(f"[gate] {name}: executed but should route to DEV")
        except ex.GateToDev:
            print(f"[gate] {name}: OK (routes to DEV)")

    # ---- type-dispatch layer: detection + validated/unvalidated gating ----
    for stem, (want_type, want_valid) in TYPE_CASES.items():
        a, b = _spair(stem)
        if not (os.path.isfile(a) and os.path.isfile(b)):
            continue                       # sample not present in this checkout
        e = DiffEngine(a, b, _cust_for(stem), VEND, LANGS)
        if e.obj_type != want_type:
            fails.append(f"[type] {stem}: detected {e.obj_type!r} want {want_type!r}")
            continue
        if e.scope['validated'] != want_valid:
            fails.append(f"[type] {stem}: validated={e.scope['validated']} want {want_valid}")
            continue
        rows = e.classify()
        gated = any(r['kind'] == 'type-unsupported' for r in rows)
        if want_valid and gated:
            fails.append(f"[type] {stem}: validated type wrongly gated as unsupported")
        elif not want_valid and not gated:
            fails.append(f"[type] {stem}: unvalidated type NOT gated -> would run wrong rules")
        else:
            print(f"[type] {stem}: OK ({want_type}, validated={want_valid})")

    # ---- type-dispatch layer: A/B type mismatch -> DEV ----
    a_tbl, _ = _spair('T14')
    _, b_cu = _spair('C80')
    if os.path.isfile(a_tbl) and os.path.isfile(b_cu):
        e = DiffEngine(a_tbl, b_cu, CUST, VEND, LANGS)
        rows = e.classify()
        if e.type_mismatch and [r['kind'] for r in rows] == ['type-mismatch']:
            print("[type] mismatch: OK (Table/Codeunit pair -> single DEV row)")
        else:
            fails.append(f"[type] mismatch: not gated correctly "
                         f"(mismatch={e.type_mismatch}, rows={[r['kind'] for r in rows]})")

    print()
    if fails:
        print(f"FAIL ({len(fails)})")
        for f in fails:
            print('  ' + f)
        sys.exit(1)
    print("PASS")


def _dump_diff(name, got, want):
    import difflib
    g, w = got.split('\n'), want.split('\n')
    d = list(difflib.unified_diff(w, g, fromfile=f'{name}.fixture',
                                  tofile=f'{name}.got', lineterm=''))
    print(f"---- {name} diff (first 40 lines) ----")
    for l in d[:40]:
        print(l)
    print("---- end diff ----")


if __name__ == '__main__':
    run()
