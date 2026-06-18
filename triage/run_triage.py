#!/usr/bin/env python3
"""
run_triage.py -- CLI for vendor-delta triage (Stage 1, for local testing).

    python triage/run_triage.py <existing_baseline> <new_baseline> \
        [--stage <out_dir>] [--report <path>]

Compares the two vendor baselines, prints the type-grouped pipe-separated export
report and a summary, optionally writes the report to a file, and optionally
stages the New-baseline copies of the changed + new objects into <out_dir>.

Not frozen -- the shipped artifact is the GUI (triage_gui.py via triage.spec).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import triageengine as te


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Triage vendor baselines: find objects the vendor changed '
                    'or added in the new CU.')
    ap.add_argument('existing_baseline', help='folder of Existing-CU objects')
    ap.add_argument('new_baseline', help='folder of New-CU objects')
    ap.add_argument('--stage', metavar='DIR',
                    help='copy New-baseline changed+new objects into DIR')
    ap.add_argument('--report', metavar='PATH',
                    help='write the export report to this file')
    args = ap.parse_args(argv)

    for d in (args.existing_baseline, args.new_baseline):
        if not os.path.isdir(d):
            ap.error(f'not a directory: {d}')

    result = te.triage_baselines(args.existing_baseline, args.new_baseline)
    report = te.export_report(result)

    print(report)
    print()
    print('Summary: ' + te.summary(result))

    if args.report:
        with open(args.report, 'w', encoding=te.ce.ENCODING) as f:
            f.write(report + '\n')
        print(f'[written] {args.report}')

    if args.stage:
        staged = te.stage_new_baseline(result, args.new_baseline, args.stage)
        print(f'[staged] {len(staged)} object(s) -> {args.stage}')

    # Non-zero if there is anything to carry, handy for scripting.
    return 1 if (result['changed'] or result['new']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
