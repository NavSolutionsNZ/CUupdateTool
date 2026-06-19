#!/usr/bin/env python3
"""
test_pipeline.py -- known-answer harness for the CU upgrade pipeline logic.

Covers the pure-Python core (classify / filter / stage / import / report). The
PowerShell split + DB export and the CUupdate invocation are Windows/NAV-only
and are not exercised here; they are thin subprocess shells around proven tools.

Fixtures (fixtures/pipe), already split:
  hq/       CU-T14, CU-T36, CU-C80, CU-P21   (HQ changed set)
  customer/ EX-T36, EX-C80, EX-P21           (T14 absent)
  oldbase/  OB-T36, OB-C80                    (P21 absent)

Expected classification:
  T14 -> new           (customer absent)
  T36 -> take-straight (customer == old baseline)
  C80 -> merge         (customer != old baseline)
  P21 -> merge         (customer present, no old-baseline reference)
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'compare'))
import pipeline as pl

PIPE = os.path.join(HERE, 'fixtures', 'pipe')
HQ = os.path.join(PIPE, 'hq')
CUST = os.path.join(PIPE, 'customer')
OLD = os.path.join(PIPE, 'oldbase')

_failures = 0


def check(label, got, want):
    global _failures
    ok = got == want
    if not ok:
        _failures += 1
    print(f"  [{'OK ' if ok else 'XX '}] {label}: got {got!r} want {want!r}")
    return ok


def _by_key(rows):
    return {r['key']: r for r in rows}


def test_classify():
    print("classify:")
    rows = pl.classify(HQ, CUST, OLD)
    by = _by_key(rows)
    check("T14 new (customer absent)", by['T14']['treatment'], 'new')
    check("T36 take-straight (== old baseline)",
          by['T36']['treatment'], 'take-straight')
    check("C80 merge (!= old baseline)", by['C80']['treatment'], 'merge')
    check("P21 merge (no old-baseline ref)", by['P21']['treatment'], 'merge')
    # VL gate: identical body but customer Version List differs -> merge.
    check("T50 merge on Version List alone (body identical)",
          by['T50']['treatment'], 'merge')
    check("T50 reason cites Version List",
          'Version List' in by['T50']['reason'], True)


def test_vl_gate():
    print("version-list gate:")
    # The T50 bodies are identical; only the VL token set differs.
    ex = os.path.join(CUST, 'EX-T50.txt')
    ob = os.path.join(OLD, 'OB-T50.txt')
    body = pl.ce.compare_pair(ex, ob)
    check("T50 bodies match (body gate would take-straight)",
          body['verdict'], 'matched')
    check("T50 version tokens differ",
          pl._version_tokens(ex) != pl._version_tokens(ob), True)
    check("WBL is the customer-only token",
          'WBL' in (pl._version_tokens(ex) - pl._version_tokens(ob)), True)


def test_filter():
    print("type-aware filter:")
    filters = pl.keys_to_type_filters(['T18', 'C80', 'T36', 'P21', 'X50'])
    # One filter per type, each pinning Type, ids sorted numerically.
    check("table filter", 'Type=Table;Id=18|36' in filters, True)
    check("codeunit filter", 'Type=Codeunit;Id=80' in filters, True)
    check("page filter", 'Type=Page;Id=21' in filters, True)
    check("xmlport filter (exact spelling)",
          'Type=XMLport;Id=50' in filters, True)
    check("one filter per type", len(filters), 4)
    # No id-only filter that would over-pull across types.
    check("no bare Id= filter",
          any(f.startswith('Id=') for f in filters), False)


def test_stage_merge():
    print("stage merge job:")
    job = os.path.join(PIPE, 'job')
    shutil.rmtree(job, ignore_errors=True)
    rows = pl.classify(HQ, CUST, OLD)
    n = pl.stage_merge_job(rows, HQ, CUST, job)
    check("three merge objects staged (C80, P21, T50)", n, 3)
    check("A/Codeunit/EX-C80.txt staged",
          os.path.isfile(os.path.join(job, 'A', 'Codeunit', 'EX-C80.txt')),
          True)
    check("B/Codeunit/CU-C80.txt staged",
          os.path.isfile(os.path.join(job, 'B', 'Codeunit', 'CU-C80.txt')),
          True)
    check("take-straight T36 NOT staged for merge",
          os.path.isfile(os.path.join(job, 'A', 'Table', 'EX-T36.txt')),
          False)
    shutil.rmtree(job, ignore_errors=True)


def test_import_and_report():
    print("import set + report:")
    job = os.path.join(PIPE, 'job')
    imp = os.path.join(PIPE, 'import')
    shutil.rmtree(job, ignore_errors=True)
    shutil.rmtree(imp, ignore_errors=True)
    rows = pl.classify(HQ, CUST, OLD)
    pl.stage_merge_job(rows, HQ, CUST, job)

    # Simulate CUupdate: C80 auto-merged (Merged- output present), P21 DEV-gated
    # (no output). Build the import set from what is ready.
    merged_dir = os.path.join(job, 'Merged', 'Codeunit')
    os.makedirs(merged_dir, exist_ok=True)
    with open(os.path.join(merged_dir, 'Merged-C80.txt'), 'w') as f:
        f.write('OBJECT Codeunit 80 Obj80\n{\n}\n')

    imported, manual = pl.build_import_set(rows, HQ, job, imp)
    check("import has new T14", 'T14' in imported, True)
    check("import has take-straight T36", 'T36' in imported, True)
    check("import has auto-merged C80", 'C80' in imported, True)
    check("P21+T50 flagged manual (DEV-gated, no merge output)",
          manual, ['P21', 'T50'])
    check("import file CU-T14.txt present",
          os.path.isfile(os.path.join(imp, 'CU-T14.txt')), True)
    check("import file Merged-C80.txt present",
          os.path.isfile(os.path.join(imp, 'Merged-C80.txt')), True)
    check("P21 NOT in import folder",
          os.path.isfile(os.path.join(imp, 'CU-P21.txt')), False)

    report = pl.treatment_report(rows, imported, manual, merged=True)
    check("report shows manual-required section",
          'MANUAL MERGE REQUIRED' in report, True)
    check("report lists P21 as manual", 'P21' in report, True)
    check("report shows new treatment", 'new' in report, True)
    check("post-merge report uses auto-merged label",
          'auto-merged' in report, True)
    # Classify-stage report (no merge yet) must say to-merge, not auto-merged.
    classify_report = pl.treatment_report(rows)
    check("classify report uses to-merge", 'to-merge' in classify_report, True)
    check("classify report does NOT say auto-merged",
          'auto-merged' in classify_report, False)

    shutil.rmtree(job, ignore_errors=True)
    shutil.rmtree(imp, ignore_errors=True)


def main():
    for t in (test_classify, test_vl_gate, test_filter, test_stage_merge,
              test_import_and_report):
        t()
    print()
    if _failures:
        print(f"FAILED: {_failures} check(s)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
