#!/usr/bin/env python3
"""
run_compare.py -- CLI for the comparison oracle.

    python compare/run_compare.py <golds_dir> <candidates_dir> [--out report.txt]

Pairs gold/candidate objects by filename, compares each byte-for-byte (with the
header-stamp tolerance described in compareengine), and prints a per-object
summary table followed by detail blocks for every non-matched object. With
--out, the identical report is also written to a file.

Console-first by design (Rich's call): a clean run is just the table; detail
blocks print only for things that need a human eye.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compareengine as ce


VERDICT_ORDER = {
    'unmatched': 0,
    'matched-except-header': 1,
    'missing-candidate': 2,
    'missing-gold': 3,
    'matched': 4,
}


def _fmt_row(file, typ, oid, verdict, sections, w):
    t = f'{typ or "?"} {oid or ""}'.strip()
    secs = ', '.join(sections) if sections else ''
    return (f'{file:<{w["file"]}}  {t:<{w["type"]}}  '
            f'{verdict:<{w["verdict"]}}  {secs}')


def build_report(results, missing_candidate, missing_gold):
    """Return the full report as a single string (console and file identical)."""
    rows = []
    for r in results:
        rows.append({
            'file': r['file'], 'type': r.get('type'), 'id': r.get('id'),
            'verdict': r['verdict'], 'sections': r.get('sections', []),
            'diffs': r.get('diffs', []),
            'missing_doc_tags': r.get('missing_doc_tags', []),
        })
    for fn in missing_candidate:
        rows.append({'file': fn, 'type': None, 'id': None,
                     'verdict': 'missing-candidate', 'sections': [],
                     'diffs': [], 'missing_doc_tags': []})
    for fn in missing_gold:
        rows.append({'file': fn, 'type': None, 'id': None,
                     'verdict': 'missing-gold', 'sections': [],
                     'diffs': [], 'missing_doc_tags': []})

    rows.sort(key=lambda r: (VERDICT_ORDER.get(r['verdict'], 9), r['file']))

    w = {
        'file': max([4] + [len(r['file']) for r in rows]),
        'type': max([4] + [len(f'{r["type"] or "?"} {r["id"] or ""}'.strip())
                           for r in rows]),
        'verdict': max(len('matched-except-header'),
                       *[len(r['verdict']) for r in rows]) if rows else 8,
    }

    out = []
    header = (f'{"FILE":<{w["file"]}}  {"OBJECT":<{w["type"]}}  '
              f'{"VERDICT":<{w["verdict"]}}  SECTIONS')
    out.append(header)
    out.append('-' * len(header))
    for r in rows:
        out.append(_fmt_row(r['file'], r['type'], r['id'], r['verdict'],
                            r['sections'], w))

    # Tally
    tally = {}
    for r in rows:
        tally[r['verdict']] = tally.get(r['verdict'], 0) + 1
    out.append('')
    out.append('Summary: ' + ', '.join(
        f'{k}={tally[k]}' for k in sorted(tally, key=lambda k: VERDICT_ORDER.get(k, 9))))

    # Detail blocks for everything that is not a clean match.
    detail = [r for r in rows if r['verdict'] in
              ('unmatched', 'matched-except-header')]
    if detail:
        out.append('')
        out.append('=' * len(header))
        out.append('DETAIL (non-matched objects)')
        out.append('=' * len(header))
        for r in detail:
            out.append('')
            out.append(f'### {r["file"]}  [{r["verdict"]}]  '
                       f'sections: {", ".join(r["sections"]) or "-"}')
            if r.get('missing_doc_tags'):
                out.append('  doc-trigger tags in gold but missing from '
                           'candidate: ' + ', '.join(r['missing_doc_tags']))
            for lineno, g, c in r['diffs']:
                gtxt = '<absent>' if g is None else g
                ctxt = '<absent>' if c is None else c
                out.append(f'  line {lineno}:')
                out.append(f'    gold: {gtxt}')
                out.append(f'    cand: {ctxt}')

    return '\n'.join(out)


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
    report = build_report(results, miss_c, miss_g)

    print(report)
    if args.out:
        with open(args.out, 'w', encoding=ce.ENCODING) as f:
            f.write(report + '\n')
        print(f'\n[written] {args.out}')

    # Exit non-zero if anything needs attention -- handy for scripting a
    # whole-customer check into a pass/fail gate.
    needs_eye = any(r['verdict'] in ('unmatched', 'missing-candidate',
                                     'missing-gold')
                    for r in results) or miss_c or miss_g
    return 1 if needs_eye else 0


if __name__ == '__main__':
    raise SystemExit(main())
