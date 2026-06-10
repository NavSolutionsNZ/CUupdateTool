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


def format_merge_dates(date_format='DDMMYY', when=None):
    """Build the two date strings the executor needs from a single date.

    - header `Date=` follows the CUSTOMER DB's locale: DDMMYY or MMDDYY
      (the dev declares which via the GUI radio button - NAV writes the header
      in whatever format the source database uses, so the stamp must match).
    - doc-trigger changelog date is ALWAYS DD.MM.YY (incadea convention,
      locale-independent - verified across all sample objects).

    `when` defaults to today. Returns (merge_date, merge_date_dots).
    """
    import datetime
    d = when or datetime.date.today()
    dd, mm, yy = f'{d.day:02d}', f'{d.month:02d}', f'{d.year % 100:02d}'
    if date_format.upper() == 'MMDDYY':
        merge_date = f'{mm}/{dd}/{yy}'
    else:                                   # default DDMMYY (NZ / most incadea)
        merge_date = f'{dd}/{mm}/{yy}'
    merge_date_dots = f'{dd}.{mm}.{yy}'     # doc trigger: always DD.MM.YY
    return merge_date, merge_date_dots


def run(root, cu, initials, date=None, text='CU upgrade.',
        cust='AP,WBL', vend='PA,PPA,EU,INC,IMM,PS', langs='ENZ',
        date_format='DDMMYY', dry_run=False):
    """Run the Stage 3 batch over <root>/A and <root>/B.

    Behaviour is identical to the CLI: auto-merged objects are written to
    Merged/ and their sources moved to AautoMerged/ + BautoMerged/; DEV-gated
    and error objects are left in place. Returns (report_str, results_dict)
    where results_dict has keys merged/dev/errors/unmatched/pairs so callers
    (CLI, GUI) can both print the report and inspect counts. Accepts cust/vend/
    langs as comma strings or as iterables of prefixes.

    Date handling: the tool computes TODAY's date and formats the header
    `Date=` per `date_format` (the customer DB's locale: 'DDMMYY' default or
    'MMDDYY'); the doc-trigger date is always DD.MM.YY. A `date` may still be
    passed explicitly (DD/MM/YY for DDMMYY, MM/DD/YY for MMDDYY) to override
    today - mainly for reproducible tests/fixtures.

    Mutates the filesystem under root (moves/writes) unless dry_run=True.
    """
    def _as_set(v):
        if isinstance(v, str):
            return {s.strip().upper() for s in v.split(',') if s.strip()}
        return {str(s).strip().upper() for s in v if str(s).strip()}

    root = os.path.abspath(root)
    CUST, VEND, LANGS = _as_set(cust), _as_set(vend), _as_set(langs)
    if date:
        # explicit override: header takes it verbatim; doc-trigger needs DD.MM.YY.
        # Re-derive dots from the chosen format so an MM/DD/YY input still yields
        # a DD.MM.YY doc date.
        parts = date.replace('.', '/').split('/')
        if len(parts) == 3:
            if date_format.upper() == 'MMDDYY':
                mm, dd, yy = parts
            else:
                dd, mm, yy = parts
            merge_date, merge_date_dots = date, f'{dd}.{mm}.{yy}'
        else:
            merge_date, merge_date_dots = date, date.replace('/', '.')
    else:
        merge_date, merge_date_dots = format_merge_dates(date_format)
    params = dict(cu_token=cu, initials=initials, text=text,
                  merge_date=merge_date, merge_date_dots=merge_date_dots)

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
    _suffix = " - needs manual merge"
    for stem, why in dev:
        reasons = [w.strip() for w in why.split(';') if w.strip()]
        if len(reasons) <= 1:
            lines.append(f"  {stem:10} {reasons[0] if reasons else why}")
        else:
            lines.append(f"  {stem:10} {len(reasons)} blocks need manual merge:")
            for rsn in reasons:
                # header already says "need manual merge"; trim the repeat
                rsn = rsn[:-len(_suffix)] if rsn.endswith(_suffix) else rsn
                lines.append(f"  {'':10}   - {rsn}")
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
    p.add_argument('--date', default=None,
                   help='override merge date (default: today). Header format '
                        'follows --date-format.')
    p.add_argument('--date-format', default='DDMMYY', choices=['DDMMYY', 'MMDDYY'],
                   help="customer DB date locale for the header Date= field "
                        "(default DDMMYY; doc-trigger date is always DD.MM.YY)")
    p.add_argument('--cust', default='AP,WBL')
    p.add_argument('--vend', default='PA,PPA,EU,INC,IMM,PS')
    p.add_argument('--langs', default='ENZ')
    p.add_argument('--dry-run', action='store_true', help='classify only, move nothing')
    a = p.parse_args()

    report, _ = run(a.root, a.cu, a.initials, a.date, text=a.text,
                    cust=a.cust, vend=a.vend, langs=a.langs,
                    date_format=a.date_format, dry_run=a.dry_run)
    print(report)


if __name__ == '__main__':
    main()
