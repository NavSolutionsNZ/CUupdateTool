#!/usr/bin/env python3
"""
test_triage.py -- known-answer harness for the vendor-delta triage engine.

Fixtures (existing vs new vendor baseline):
  T18  unchanged body, only header Date/Version differ  -> unchanged (dropped)
  T36  vendor added a field                             -> changed
  C80  vendor RE-NESTED only (whitespace)               -> changed (STRICTER
                                                            than the gold check,
                                                            which would ignore it)
  P21  only in new baseline                             -> new
  C90  only in existing baseline                        -> removed

Plain print-OK/XX style, no pytest.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import triageengine as te

FIX = os.path.join(HERE, 'fixtures')
EXISTING = os.path.join(FIX, 'existing')
NEW = os.path.join(FIX, 'new')

_failures = 0


def check(label, got, want):
    global _failures
    ok = got == want
    if not ok:
        _failures += 1
    print(f"  [{'OK ' if ok else 'XX '}] {label}: got {got!r} want {want!r}")
    return ok


def test_classification():
    print("classification:")
    r = te.triage_baselines(EXISTING, NEW)
    changed = {k for k, _e, _n in r['changed']}
    new = {k for k, _n in r['new']}
    removed = {k for k, _e in r['removed']}
    unchanged = set(r['unchanged'])

    check("T18 unchanged (header-only diff dropped)", 'T18' in unchanged, True)
    check("T36 changed (field added)", 'T36' in changed, True)
    check("C80 changed by re-nesting (stricter than gold)",
          'C80' in changed, True)
    check("P21 new", 'P21' in new, True)
    check("C90 removed", 'C90' in removed, True)
    check("T18 not flagged changed", 'T18' in changed, False)


def test_strictness_vs_gold():
    print("strictness vs gold:")
    # The same C80 pair: triage flags it (whitespace-significant), but the gold
    # oracle's body comparison would call it matched (whitespace collapsed).
    import compareengine as ce
    e = os.path.join(EXISTING, 'CU-C80.txt')
    n = os.path.join(NEW, 'CU-C80.txt')
    check("triage: bodies differ (strict)", te.bodies_differ(e, n), True)
    res = ce.compare_pair(e, n)
    check("gold oracle: same pair is matched (whitespace ignored)",
          res['verdict'], 'matched')


def test_body_only():
    print("body-only:")
    # Header and doc-trigger differences alone never flag as changed.
    check("T18 header+doctrigger date diff -> unchanged",
          'T18' in set(te.triage_baselines(EXISTING, NEW)['unchanged']), True)


def test_report():
    print("report:")
    r = te.triage_baselines(EXISTING, NEW)
    rep = te.export_report(r)
    # changed (T36, C80) + new (P21) appear; unchanged (T18) does not.
    check("report lists TABLE 36", 'TABLE: 36' in rep, True)
    check("report lists CODEUNIT 80", '80' in rep and 'CODEUNIT' in rep, True)
    check("report has NEW section", 'NEW objects' in rep, True)
    check("report lists PAGE 21 as new", 'PAGE: 21' in rep, True)
    check("report does NOT list unchanged T18", 'TABLE: 18' in rep, False)
    check("report flags REMOVED C90", 'REMOVED' in rep and '90' in rep, True)


def test_grouping():
    print("grouping:")
    grouped = te._group_by_type(['T36', 'C80', 'C5063', 'T18', 'P21'])
    d = dict(grouped)
    # Tables before codeunits before pages (TYPE_ORDER); numeric sort within.
    check("tables sorted numerically", d['T'], ['18', '36'])
    check("codeunits sorted numerically", d['C'], ['80', '5063'])
    check("type order: T before C",
          [t for t, _ in grouped].index('T') <
          [t for t, _ in grouped].index('C'), True)


def test_staging(tmpdir='/tmp/_triage_stage_test'):
    print("staging:")
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)
    r = te.triage_baselines(EXISTING, NEW)
    staged = te.stage_new_baseline(r, NEW, tmpdir)
    files = set(os.listdir(tmpdir))
    # changed (T36, C80) + new (P21) staged; unchanged (T18) and removed not.
    check("staged count = changed + new", len(staged), 3)
    check("T36 staged", 'CU-T36.txt' in files, True)
    check("P21 staged (new)", 'CU-P21.txt' in files, True)
    check("T18 NOT staged (unchanged)", 'CU-T18.txt' in files, False)
    shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    for t in (test_classification, test_strictness_vs_gold, test_body_only,
              test_report, test_grouping, test_staging):
        t()
    print()
    if _failures:
        print(f"FAILED: {_failures} check(s)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
