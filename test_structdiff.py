import sys; sys.path.insert(0, '/home/claude/CUupdateTool')
from structdiff import StructDiff

# expected verdicts keyed by (obj, tag) for documented customer entries.
# Extend this dict and rerun when adding objects (cf. test_scorer.py pattern).
EXP = {
 ('P21', 'WBL10'):   'AUTO_GRAFT',   # 'Purchase Order No. Mandatory' field — clean add, anchor survives
 ('P21', 'AP-2362'): 'DEV',          # "Divided ... FactBox into FactBox2/3" — restructure
}

OBJS = [('P21', 'Cust_P21.txt', '20206Q1_P21.txt')]
CUST = {'AP', 'WBL'}

results = {}
for name, a, b in OBJS:
    sd = StructDiff(a, b, CUST)
    rows, code_only = sd.report()
    for r in rows:
        results[(name, r['tag'])] = r

passed = failed = unknown = 0
print(f"{'case':20} {'expected':12} {'got':12} result")
for (name, tag), exp in EXP.items():
    got = results.get((name, tag), {}).get('verdict', 'MISSING')
    ok = (got == exp)
    print(f"{name+' '+tag:20} {exp:12} {got:12} {'PASS' if ok else 'FAIL <<<'}")
    passed += ok; failed += (not ok)

# any DEV-routed UNDOC/extra rows are reported but not failures (correct-conservative)
for k, r in results.items():
    if k not in EXP:
        unknown += 1
        print(f"  (untested) {k[0]} {k[1]:10} {r['kind']:9} -> {r['verdict']} :: {r['reason']}")

print(f"\nPASS={passed} FAIL={failed} (untested rows={unknown})")
