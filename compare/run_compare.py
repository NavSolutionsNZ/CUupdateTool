#!/usr/bin/env python3
"""
run_compare.py -- CLI for the comparison oracle (kept for local testing).

    python compare/run_compare.py <golds_dir> <candidates_dir> [--out report.txt]

Pairs gold/candidate objects by filename, compares each (with the header-stamp
and doc-trigger tolerances described in compareengine), prints the per-object
summary table + detail blocks, and optionally writes the same report to a file.

The report itself is built by compareengine.build_report, which the GUI shares,
so console / file / GUI all render identical text. This runner is NOT frozen --
the shipped artifact is the GUI exe (compare_gui.py via compare.spec).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compareengine as ce


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Compare hand-merged GOLD objects against CUupdate.exe '
                    'CANDIDATE output, paired by filename.')
    ap.add_argument('golds_dir', help='folder of hand-merged known-answer files')
    ap.add_argument('candidates_dir', help='folder of CUupdate.exe output files')
    ap.add_argument('--out', metavar='PATH',
                    help='also write the report to this file')
    args = ap.parse_args(argv)

    for d in (args.golds_dir, args.candidates_dir):
        if not os.path.isdir(d):
            ap.error(f'not a directory: {d}')

    results, miss_c, miss_g = ce.compare_dirs(args.golds_dir, args.candidates_dir)
    report = ce.build_report(results, miss_c, miss_g)

    print(report)
    if args.out:
        with open(args.out, 'w', encoding=ce.ENCODING) as f:
            f.write(report + '\n')
        print(f'\n[written] {args.out}')

    return 1 if ce.needs_attention(results, miss_c, miss_g) else 0


if __name__ == '__main__':
    raise SystemExit(main())
