#!/usr/bin/env python3
"""
run_batch.py -- Stage 3 batch driver over a customer job's A/ and B/ folders.

Layout expected (inputs already language-stripped by the native cmdlet):
    A/<Type>/EX-<stem>.txt      customer object  (A)   e.g. A/Table/EX-T14.txt
    B/<Type>/CU-<stem>.txt      CU/vendor object (B)   e.g. B/Table/CU-T14.txt
  where <stem> is <TypeChar><Number>: Table->T, Page->P, Report->R, Codeunit->C.
  (e.g. Table 14 -> T14). Pairing is by <stem>.

For each pair:
  - AUTO-MERGED  -> write Merged/<Type>/Merged-<stem>.txt, then MOVE the two
                    source files into AautoMerged/<Type>/ and BautoMerged/<Type>/.
                    They leave A/ and B/, so only manual-review objects remain.
  - DEV (gated)  -> left in place in A/ and B/ for manual TortoiseMerge.
  - ERROR        -> left in place, reported.

Usage:
    python3 run_batch.py --root /path/to/job \
        --cu CU26Q1 --initials RL --text "CU upgrade." --date 08/06/26
    (--root defaults to current dir; expects A/ and B/ under it)

Census prefixes/languages: hardcoded to current customer (Stage 0 feeds these
in production). Override with --cust / --vend / --langs if needed.
"""
import argparse, os, re, shutil, sys
import execute as ex

TYPECHAR = {'C': 'Codeunit', 'T': 'Table', 'P': 'Page', 'R': 'Report'}


def find_pairs(root):
    """Walk A/ for EX-*.txt, match B/ CU-*.txt by stem. Returns
    [(stem, type_subdir, a_path, b_path)] and a list of unmatched A files."""
    a_root = os.path.join(root, 'A')
    b_root = os.path.join(root, 'B')
    pairs, unmatched = [], []
    if not os.path.isdir(a_root) or not os.path.isdir(b_root):
        sys.exit(f"expected A/ and B/ under {root}")
    for dirpath, _, files in os.walk(a_root):
        rel = os.path.relpath(dirpath, a_root)          # e.g. 'Table' or '.'
        for fn in files:
            m = re.match(r'EX-(.+)\.txt$', fn, re.I)
            if not m:
                continue
            stem = m.group(1)
            b_dir = os.path.join(b_root, rel)
            b_path = os.path.join(b_dir, f'CU-{stem}.txt')
            a_path = os.path.join(dirpath, fn)
            if os.path.isfile(b_path):
                pairs.append((stem, rel, a_path, b_path))
            else:
                unmatched.append(a_path)
    return pairs, unmatched


def _moved(root, side, type_sub, src):
    """Move src into <side>autoMerged/<type_sub>/ preserving the subfolder."""
    dest_dir = os.path.join(root, f'{side}autoMerged', type_sub)
    os.makedirs(dest_dir, exist_ok=True)
    shutil.move(src, os.path.join(dest_dir, os.path.basename(src)))


def run(root, cu, initials, date, text='CU upgrade.',
        cust='AP,WBL', vend='PA,PPA,EU,INC,IMM,PS', langs='ENZ',
        dry_run=False):
    """Run the Stage 3 batch over <root>/A and <root>/B.

    Behaviour is identical to the CLI: auto-merged objects are written to
    Merged/ and their sources moved to AautoMerged/ + BautoMerged/; DEV-gated
    and error objects are left in place. Returns (report_str, results_dict)
    where results_dict has keys merged/dev/errors/unmatched/pairs so callers
    (CLI, GUI) can both print the report and inspect counts. Accepts cust/vend/
    langs as comma strings or as iterables of prefixes.

    Mutates the filesystem under root (moves/writes) unless dry_run=True.
    """
    def _as_set(v):
        if isinstance(v, str):
            return {s.strip().upper() for s in v.split(',') if s.strip()}
        return {str(s).strip().upper() for s in v if str(s).strip()}

    root = os.path.abspath(root)
    CUST, VEND, LANGS = _as_set(cust), _as_set(vend), _as_set(langs)
    params = dict(cu_token=cu, initials=initials, text=text,
                  merge_date=date, merge_date_dots=date.replace('/', '.'))

    pairs, unmatched = find_pairs(root)
    merged, dev, errors = [], [], []

    for stem, type_sub, a_path, b_path in sorted(pairs):
        try:
            out = ex.execute(a_path, b_path, CUST, VEND, LANGS, params)
        except ex.GateToDev as g:
            dev.append((stem, str(g)))
            continue
        except Exception as e:                          # never crash the batch
            errors.append((stem, f'{type(e).__name__}: {e}'))
            continue

        if dry_run:
            merged.append((stem, '(dry-run, not written)'))
            continue

        out_dir = os.path.join(root, 'Merged', type_sub)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f'Merged-{stem}.txt')
        with open(out_path, 'w', encoding='latin-1', newline='') as f:
            f.write(out)
        _moved(root, 'A', type_sub, a_path)
        _moved(root, 'B', type_sub, b_path)
        merged.append((stem, out_path))

    # ---- report (built as a string so GUI and CLI share one source) ----
    lines = []
    lines.append(f"\n=== Batch complete: {len(pairs)} pairs "
                 f"({len(unmatched)} unmatched A files) ===")
    lines.append(f"\nAUTO-MERGED ({len(merged)}):")
    for stem, dest in merged:
        shown = os.path.relpath(dest, root) if os.path.sep in str(dest) else dest
        lines.append(f"  {stem:10} -> {shown}")
    lines.append(f"\nMANUAL REVIEW / DEV ({len(dev)}):  (left in A/ and B/)")
    for stem, why in dev:
        lines.append(f"  {stem:10} {why}")
    if errors:
        lines.append(f"\nERRORS ({len(errors)}):  (left in place)")
        for stem, why in errors:
            lines.append(f"  {stem:10} {why}")
    if unmatched:
        lines.append("\nUNMATCHED A FILES (no CU- counterpart):")
        for u in unmatched:
            lines.append(f"  {os.path.relpath(u, root)}")

    report = "\n".join(lines)
    results = dict(merged=merged, dev=dev, errors=errors,
                   unmatched=unmatched, pairs=pairs)
    return report, results


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', default='.')
    p.add_argument('--cu', required=True)
    p.add_argument('--initials', required=True)
    p.add_argument('--text', default='CU upgrade.')
    p.add_argument('--date', required=True, help='DD/MM/YY')
    p.add_argument('--cust', default='AP,WBL')
    p.add_argument('--vend', default='PA,PPA,EU,INC,IMM,PS')
    p.add_argument('--langs', default='ENZ')
    p.add_argument('--dry-run', action='store_true', help='classify only, move nothing')
    a = p.parse_args()

    report, _ = run(a.root, a.cu, a.initials, a.date, text=a.text,
                    cust=a.cust, vend=a.vend, langs=a.langs, dry_run=a.dry_run)
    print(report)


if __name__ == '__main__':
    main()
