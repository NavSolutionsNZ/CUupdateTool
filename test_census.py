#!/usr/bin/env python3
"""
test_census.py -- known-answer harness for the Stage 0 prefix census.

Pins the two rules that matter:
  - prefix_of: leading [A-Za-z]+ run, uppercased.
  - is_vendor: Option A token-startswith against the exclusion filter.
And the edge cases that drove the design:
  - N.7.2.1  -> prefix N, vendor (matches 'N.7')
  - NAVW1.x  -> prefix NAVW, vendor (matches 'NAV')
  - WBL      -> prefix WBL, customer (bare token, no digits)
  - ESKER1.0 -> prefix ESKER, customer
"""
import os
import sys
import tempfile

import census

VEND = ['PA', 'EU', 'PPA', 'N.7', 'AR', 'LA', 'NAV', 'INC']


def check(label, got, want):
    ok = got == want
    print(f"  [{'OK ' if ok else 'XX '}] {label}: got {got!r} want {want!r}")
    return ok


def test_prefix_of():
    print("prefix_of:")
    cases = [
        ('NAVW1.x', 'NAVW'),
        ('N.7.2.1', 'N'),
        ('AP001651', 'AP'),
        ('AP-2362', 'AP'),
        ('WBL', 'WBL'),
        ('WBL10', 'WBL'),
        ('ESKER1.0', 'ESKER'),
        ('123abc', None),     # no leading alpha
    ]
    return all(check(t, census.prefix_of(t), want) for t, want in cases)


def test_is_vendor():
    print("is_vendor (Option A startswith):")
    cases = [
        ('N.7.2.1', True),    # startswith N.7
        ('NAVW1.x', True),    # startswith NAV
        ('PA50000', True),
        ('AP001651', False),
        ('WBL', False),
        ('ESKER1.0', False),
    ]
    return all(check(t, census.is_vendor(t, VEND), want) for t, want in cases)


def test_tokens_of():
    print("tokens_of (split/strip, drop empties):")
    got = census.tokens_of('NAVW1.x, N.7.2.1,AP001651,WBL')
    want = ['NAVW1.x', 'N.7.2.1', 'AP001651', 'WBL']
    return check('mixed-whitespace split', got, want)


def test_read_version_list():
    print("read_version_list:")
    body = (
        "OBJECT Table 14 Location\n"
        "{\n"
        "  OBJECT-PROPERTIES\n"
        "  {\n"
        "    Date=09/02/23;\n"
        "    Version List=NAVW1.x,N.7.2.1,AP001651,WBL;\n"
        "  }\n"
        "}\n"
    )
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False,
                                     encoding='latin-1') as f:
        f.write(body)
        path = f.name
    try:
        got = census.read_version_list(path)
    finally:
        os.unlink(path)
    return check('extract + strip ;', got, 'NAVW1.x,N.7.2.1,AP001651,WBL')


def test_end_to_end():
    print("end-to-end census on a synthetic object set:")
    objs = {
        'EX-T14.txt': 'NAVW1.x,N.7.2.1,AP001651,WBL',
        'EX-T36.txt': 'N.7.2.1,AP001651,AP2263',
        'EX-T38.txt': 'N.7.2.1, WBL,WBL009,ESKER1.0',
    }
    with tempfile.TemporaryDirectory() as root:
        a_tbl = os.path.join(root, 'A', 'Table')
        os.makedirs(a_tbl)
        for fn, vl in objs.items():
            with open(os.path.join(a_tbl, fn), 'w', encoding='latin-1') as f:
                f.write(f"OBJECT Table 0 X\n{{\n  OBJECT-PROPERTIES\n  {{\n"
                        f"    Version List={vl};\n  }}\n}}\n")
        result = census.census(root, VEND)
        cust = sorted(p for p, r in result['prefixes'].items() if not r['vendor'])
        vendor = sorted(p for p, r in result['prefixes'].items() if r['vendor'])
    ok1 = check('customer tags', cust, ['AP', 'ESKER', 'WBL'])
    ok2 = check('vendor tags', vendor, ['N', 'NAVW'])
    return ok1 and ok2


def main():
    tests = [test_prefix_of, test_is_vendor, test_tokens_of,
             test_read_version_list, test_end_to_end]
    results = [t() for t in tests]
    n_ok = sum(results)
    print(f"\n{n_ok}/{len(results)} test groups passed")
    sys.exit(0 if all(results) else 1)


if __name__ == '__main__':
    main()
