#!/usr/bin/env python3
"""
test_compare.py -- known-answer harness for the comparison oracle.

Pins each verdict against hand-built fixtures (compare/tests/fixtures):
  T14  matched               (byte identical)
  T36  matched-except-header  (only Date=/Time=/Modified= differ)
  T38  unmatched              (Version List + a Field node differ)
  C80  missing-candidate      (gold only)
  P21  missing-gold           (candidate only)

Plus unit checks on type/ID detection and section attribution. Same plain
print-OK/XX style as the existing repo tests; no pytest dependency. Exit code
is non-zero if any check fails, so it slots into the green-suite gate.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import compareengine as ce
import run_compare

FIX = os.path.join(HERE, 'fixtures')
GOLDS = os.path.join(FIX, 'golds')
CANDS = os.path.join(FIX, 'candidates')

_failures = 0


def check(label, got, want):
    global _failures
    ok = got == want
    if not ok:
        _failures += 1
    print(f"  [{'OK ' if ok else 'XX '}] {label}: got {got!r} want {want!r}")
    return ok


def _by_file(results):
    return {r['file']: r for r in results}


def test_verdicts():
    print("verdicts:")
    results, miss_c, miss_g = ce.compare_dirs(GOLDS, CANDS)
    by = _by_file(results)

    check("T14 matched", by['T14.txt']['verdict'], 'matched')
    check("T36 matched-except-header",
          by['T36.txt']['verdict'], 'matched-except-header')
    check("T38 unmatched", by['T38.txt']['verdict'], 'unmatched')
    check("C80 missing-candidate", 'C80.txt' in miss_c, True)
    check("P21 missing-gold", 'P21.txt' in miss_g, True)
    # Doc-trigger: date + description differ, tags identical -> matched.
    check("T39 doc-date/desc ignored -> matched",
          by['T39.txt']['verdict'], 'matched')
    # Doc-trigger: a customer tag present in gold is missing from candidate.
    check("T40 missing doc tag -> unmatched",
          by['T40.txt']['verdict'], 'unmatched')


def test_doc_trigger():
    print("doc-trigger:")
    results, _c, _g = ce.compare_dirs(GOLDS, CANDS)
    by = _by_file(results)
    # T40 surfaces the dropped tag explicitly and names the Doc trigger section.
    check("T40 names Doc trigger section",
          'Doc trigger' in by['T40.txt']['sections'], True)
    check("T40 reports the missing tag",
          by['T40.txt'].get('missing_doc_tags'), ['WBL030'])
    # T39 must NOT be dragged to unmatched by date/description noise.
    check("T39 no missing tags",
          by['T39.txt'].get('missing_doc_tags', []), [])
    # Boundary detection on a real-shaped object.
    g14 = ce.read_lines(os.path.join(GOLDS, 'T14.txt'))
    start = ce.doc_trigger_start(g14)
    check("T14 doc-trigger boundary found", start is not None, True)
    tags = ce.doc_trigger_tags(g14, start)
    check("T14 tags include WBL001", 'WBL001' in tags, True)
    check("T14 tags include AP001651", 'AP001651' in tags, True)


def test_sections():
    print("sections:")
    results, _c, _g = ce.compare_dirs(GOLDS, CANDS)
    by = _by_file(results)
    secs = by['T38.txt']['sections']
    # The Version List line and a Field node both differ -> both surfaced.
    check("T38 names Version List", 'Version List' in secs, True)
    check("T38 names a Fields section",
          any(s.startswith('Fields') for s in secs), True)
    # A pure header diff is attributed to Object properties, nothing else.
    check("T36 header-only section",
          by['T36.txt']['sections'], ['Object properties'])


def test_detect_type_id():
    print("detect_type_id:")
    lines = ce.read_lines(os.path.join(GOLDS, 'T14.txt'))
    check("type", ce.detect_type_id(lines)[0], 'TABLE')
    check("id", ce.detect_type_id(lines)[1], '14')
    cu = ce.read_lines(os.path.join(GOLDS, 'C80.txt'))
    check("codeunit type", ce.detect_type_id(cu)[0], 'CODEUNIT')


def test_header_only_guard():
    print("header-only guard:")
    # Different line counts can never be a pure header diff.
    a = ['Date=01/01/24;', 'X', 'Y']
    b = ['Date=14/06/26;', 'X']
    check("length mismatch is not header-only",
          ce._header_only_diff(a, b), False)
    # A content line differing alongside a header line is not header-only.
    a = ['Date=01/01/24;', 'real']
    b = ['Date=14/06/26;', 'REAL']
    check("content diff is not header-only",
          ce._header_only_diff(a, b), False)
    # Pure header stamp difference is header-only.
    a = ['Date=01/01/24;', 'Modified=No;', 'same']
    b = ['Date=14/06/26;', 'Modified=Yes;', 'same']
    check("pure stamp diff is header-only",
          ce._header_only_diff(a, b), True)


def test_report_builds():
    print("report:")
    results, miss_c, miss_g = ce.compare_dirs(GOLDS, CANDS)
    report = run_compare.build_report(results, miss_c, miss_g)
    check("report mentions matched-except-header",
          'matched-except-header' in report, True)
    check("report has detail block",
          'DETAIL (non-matched objects)' in report, True)
    check("report shows missing-candidate",
          'missing-candidate' in report, True)


def main():
    for t in (test_verdicts, test_sections, test_doc_trigger,
              test_detect_type_id, test_header_only_guard, test_report_builds):
        t()
    print()
    if _failures:
        print(f"FAILED: {_failures} check(s)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
