#!/usr/bin/env python3
"""
test_compare.py -- known-answer harness for the merge-integrity oracle.

The check is BODY-ONLY: the OBJECT-PROPERTIES block (Date/Time/Modified/Version
List) and the doc-trigger are stripped before comparing, because those are
trustworthy tool-stamped parameters that never match a hand-merge and are not
evidence of a merge error. So:

  T14  collision      (two gold files MyMerged-/MySanitised- key to T14)
  T36  matched        (differs only on header Date -> stripped -> identical body)
  T38  unmatched      (a real Fields difference in the body)
  T39  matched        (doc-trigger date/desc differ -> stripped -> identical)
  T40  matched        (a doc-trigger tag differs -> stripped -> identical body)
  C80  missing-candidate ; P21/T14 missing-gold ; notes_readme unkeyable

Fixtures use differing prefixes on each side (MyMerged- gold, EX- candidate) so
the suite exercises prefix-agnostic pairing. Plain print-OK/XX style, no pytest.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import compareengine as ce

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


def _by_key(outcome):
    return {r['key']: r for r in outcome['results']}


def test_verdicts():
    print("verdicts:")
    outcome = ce.compare_dirs(GOLDS, CANDS)
    by = _by_key(outcome)
    miss_c = [k for k, _fn in outcome['missing_candidate']]
    miss_g = [k for k, _fn in outcome['missing_gold']]
    coll = {(k, side) for k, side, _fns in outcome['collision']}

    check("T14 collision on gold side", ('T14', 'gold') in coll, True)
    check("T14 not paired", 'T14' in by, False)
    check("T36 header-only diff -> matched (header stripped)",
          by['T36']['verdict'], 'matched')
    check("T38 real body diff -> unmatched", by['T38']['verdict'], 'unmatched')
    check("T39 doc-trigger date/desc stripped -> matched",
          by['T39']['verdict'], 'matched')
    check("T40 doc-trigger tag stripped -> matched",
          by['T40']['verdict'], 'matched')
    check("C80 missing-candidate", 'C80' in miss_c, True)
    check("P21 missing-gold", 'P21' in miss_g, True)
    # Re-nested candidate (different indentation only) -> matched.
    check("T42 re-nesting ignored -> matched",
          by['T42']['verdict'], 'matched')


def test_whitespace():
    print("whitespace:")
    # Outside quotes: runs of whitespace collapse, ends stripped.
    check("indent collapses",
          ce._norm_ws('      // Start PA035597'),
          ce._norm_ws('        // Start PA035597'))
    check("inter-token spacing collapses",
          ce._norm_ws('Y :=  1;'), ce._norm_ws('Y := 1;'))
    check("trailing space stripped",
          ce._norm_ws('END;   '), 'END;')
    # Inside quotes: whitespace preserved, so a real in-string change differs.
    check("in-quote double space preserved",
          ce._norm_ws('MESSAGE("a  b")') != ce._norm_ws('MESSAGE("a b")'), True)
    # A re-nested option line with in-quote double-space still matches.
    a = '          ["Recurring Method"::"F  Fixed",'
    b = '   ["Recurring Method"::"F  Fixed",'
    check("re-nested option string matches",
          ce._norm_ws(a), ce._norm_ws(b))


def test_body_only():
    print("body-only:")
    # OBJECT-PROPERTIES block is stripped wholesale.
    lines = [
        'OBJECT Table 1 X',
        '{',
        '  OBJECT-PROPERTIES',
        '  {',
        '    Date=01/01/24;',
        '    Version List=NAVW1,CU26Q1;',
        '  }',
        '  FIELDS',
        '  {',
        '    { 1 ; ;No ;Code20 }',
        '  }',
        '}',
    ]
    body = ce.strip_object_properties(lines)
    check("no Date line after strip",
          any('Date=' in l for l in body), False)
    check("no Version List after strip",
          any('Version List' in l for l in body), False)
    check("FIELDS survives strip",
          any('FIELDS' in l for l in body), True)

    # Two objects differing ONLY in OBJECT-PROPERTIES (date + version list) are
    # matched, because the body is identical.
    g = lines[:]
    c = [l.replace('01/01/24', '14/06/26').replace(',CU26Q1', '') for l in lines]
    gb, cb = ce._body_only(g), ce._body_only(c)
    check("header-only difference -> identical body", gb == cb, True)


def test_doc_trigger_stripped():
    print("doc-trigger stripped:")
    g14 = ce.read_lines(os.path.join(GOLDS, 'MyMerged-T14.txt'))
    body = ce._body_only(g14)
    # The doc-trigger entries (dated lines) must not survive into the body.
    check("no dated doc entry in body",
          any(ce.DOC_ENTRY.match(l) for l in body), False)
    # Boundary detection still works (used to find what to strip).
    start = ce.doc_trigger_start(ce.strip_object_properties(g14))
    check("doc-trigger boundary found", start is not None, True)


def test_pairing():
    print("pairing:")
    check("MyMerged-T18 -> T18", ce.object_key('MyMerged-T18.txt'), 'T18')
    check("EX-T18 -> T18", ce.object_key('EX-T18.txt'), 'T18')
    check("MySanitised-P5205801 -> P5205801",
          ce.object_key('MySanitised-P5205801.txt'), 'P5205801')
    check("long number kept", ce.object_key('EX-T5045517.txt'), 'T5045517')
    check("case-insensitive", ce.object_key('ex-t18.txt'), 'T18')
    check("no key tail -> None", ce.object_key('notes_readme.txt'), None)
    outcome = ce.compare_dirs(GOLDS, CANDS)
    unkey = {fn for _side, fn in outcome['unkeyable']}
    check("notes_readme is unkeyable", 'notes_readme.txt' in unkey, True)
    by = _by_key(outcome)
    check("T36 paired across differing prefixes", 'T36' in by, True)


def test_sections():
    print("sections:")
    outcome = ce.compare_dirs(GOLDS, CANDS)
    by = _by_key(outcome)
    secs = by['T38']['sections']
    check("T38 names a Fields section",
          any(s.startswith('Fields') for s in secs), True)
    # Version List diff must NOT appear -- it is stripped with the header.
    check("T38 does not name Version List",
          'Version List' in secs, False)


def test_detect_type_id():
    print("detect_type_id:")
    lines = ce.read_lines(os.path.join(GOLDS, 'MyMerged-T14.txt'))
    check("type", ce.detect_type_id(lines)[0], 'TABLE')
    check("id", ce.detect_type_id(lines)[1], '14')
    cu = ce.read_lines(os.path.join(GOLDS, 'MyMerged-C80.txt'))
    check("codeunit type", ce.detect_type_id(cu)[0], 'CODEUNIT')


def test_report_builds():
    print("report:")
    outcome = ce.compare_dirs(GOLDS, CANDS)
    report = ce.build_report(outcome)
    check("report has detail block",
          'DETAIL (non-matched objects)' in report, True)
    check("report shows missing-candidate",
          'missing-candidate' in report, True)
    check("report shows collision", 'collision' in report, True)
    check("report shows unkeyable", 'unkeyable' in report, True)
    check("report does NOT mention matched-except-header",
          'matched-except-header' in report, False)


def main():
    for t in (test_verdicts, test_whitespace, test_body_only,
              test_doc_trigger_stripped, test_pairing, test_sections,
              test_detect_type_id, test_report_builds):
        t()
    print()
    if _failures:
        print(f"FAILED: {_failures} check(s)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
