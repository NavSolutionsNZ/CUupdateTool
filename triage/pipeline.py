#!/usr/bin/env python3
"""
pipeline.py -- full CU upgrade pipeline (Stage 2 + 3), driven from HQ's
changed-objects file.

HQ now delivers a single combined .txt of every object they changed in the new
CU, so the vendor-delta question is answered -- this module takes that list and
drives the rest:

  1. Split HQ's file into per-object CU-<key>.txt files (the changed set).
  2. Export the matching objects from the Customer DB (EX-) and the Old Baseline
     DB (OB-), filtered to HQ's key list.
  3. Classify each object three ways:
       - take-straight (new): customer does not have the object.
       - take-straight (unmodified): customer Version List AND body both match
         the old baseline.
       - merge: customer Version List OR body differs from the old baseline
         (over-inclusive on purpose; CUupdate's no-CU-change short-circuit
         take-A's anything that needs no merge, so over-including is free while
         under-including risks losing customer work).
  4. Run CUupdate (run_batch) over the staged A/ B/ -> Merged/, auto vs DEV.
  5. Build the Import folder: take-straight CU objects + Merged- outputs.
     DEV-gated objects are flagged as still-needs-manual; they are NOT added to
     the import set (it is incomplete until they are hand-merged).
  6. Emit a per-object report: key | treatment | reason.

Customer-modified test uses the gold oracle's body comparison (body-only,
whitespace-collapsed): a customer never only re-nests, so a collapsed body
difference is the right signal for "customer has real code here".

Boundaries: DB export runs via PowerShell under Windows auth (no credentials
here). CUupdate is invoked as the user's frozen exe / CLI; its path is supplied.
"""
import os
import shutil
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, '..', 'compare'), os.path.join(_HERE, '..')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import compareengine as ce          # noqa: E402
import triageengine as te           # noqa: E402

import re as _re

# Version List header line, e.g. `    Version List=NAVW114.00,AP001651,WBL;`
_VERSION_LINE = _re.compile(r'Version\s*List\s*=([^;]*)', _re.I)


def _version_tokens(path):
    """The set of Version List tokens for an object, or empty set if none.

    Used for the triage gate: if the customer (EX) and old-baseline (OB)
    Version Lists differ, the customer registered a change in the header --
    a CUupdate candidate regardless of body. Read with latin-1 to match the
    rest of the tooling.
    """
    try:
        with open(path, 'r', encoding=ce.ENCODING) as f:
            for line in f:
                m = _VERSION_LINE.search(line)
                if m:
                    return {t.strip() for t in m.group(1).split(',') if t.strip()}
    except OSError:
        pass
    return set()

# Type letter -> run_batch subfolder name (mirrors Rich's manual convention;
# run_batch only needs A/ and B/ to share the same relative layout).
TYPE_SUBFOLDER = {
    'T': 'Table', 'C': 'Codeunit', 'P': 'Page', 'R': 'Report',
    'X': 'XMLPort', 'Q': 'Query', 'M': 'MenuSuite',
}


def split_hq_file(hq_file, out_dir, script_path=None):
    """Split HQ's combined changed-objects file into CU-<key>.txt per object.

    Reuses Split-NAVApplicationObjectFile via the PS1 (Windows). Returns the
    list of object keys produced.
    """
    # The PS1 exports+splits; for a file that already exists we only need the
    # split half. Rather than fork the PS1, call a thin split-only path here by
    # reusing the same cmdlet through PowerShell.
    os.makedirs(out_dir, exist_ok=True)
    script = script_path or _split_only_script()
    cmd = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
           '-File', script, '-Source', hq_file, '-Destination', out_dir,
           '-Prefix', 'CU']
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return [], ('powershell.exe not found -- splitting runs on Windows with '
                    'the NAV model-tools module.')
    if proc.returncode != 0:
        return [], (proc.stdout or '') + (proc.stderr or '')
    keys = [ce.object_key(f) for f in os.listdir(out_dir)
            if ce.object_key(f)]
    return sorted(set(keys)), (proc.stdout or '').strip()


def _split_only_script():
    """Locate Split-Objects.ps1 (split-only helper) bundled with the tool."""
    cands = [
        os.path.join(_HERE, 'scripts', 'Split-Objects.ps1'),
        os.path.join(getattr(sys, '_MEIPASS', _HERE), 'scripts',
                     'Split-Objects.ps1'),
    ]
    for c in cands:
        if os.path.isfile(c):
            return c
    return cands[0]


def keys_to_filter(keys):
    """Build a NAV object-id filter from a set of keys, grouped by type.

    NAV filters are per-table; Export-NAVApplicationObject takes a single
    Filter applied across types via 'Type=...;Id=...'. Simplest robust form:
    filter by Id only (ids are unique enough within an export for our purpose),
    e.g. 'Id=18|36|80'. Returns the filter string.
    """
    ids = []
    for k in keys:
        _letter, num = te.split_key(k)
        if num and num.isdigit():
            ids.append(num)
    ids = sorted(set(ids), key=int)
    return 'Id=' + '|'.join(ids) if ids else 'Id=0'


def classify(hq_dir, customer_dir, oldbase_dir):
    """Three-way classify each HQ object key.

    Returns a list of dicts: {key, treatment, reason, cu_file, ex_file, ob_file}
    treatment in {'new', 'take-straight', 'merge'}.
    """
    def index(folder):
        out = {}
        if not os.path.isdir(folder):
            return out
        for f in sorted(os.listdir(folder)):
            k = ce.object_key(f)
            if k and k not in out:
                out[k] = f
        return out

    hq = index(hq_dir)
    cust = index(customer_dir)
    old = index(oldbase_dir)

    rows = []
    for k in sorted(hq):
        cu_file = hq[k]
        if k not in cust:
            rows.append({'key': k, 'treatment': 'new',
                         'reason': 'customer does not have this object',
                         'cu_file': cu_file, 'ex_file': None, 'ob_file': None})
            continue
        ex_file = cust[k]
        ob_file = old.get(k)
        if ob_file is None:
            # Customer has it but no old-baseline reference: cannot prove
            # unmodified, so treat as merge to be safe.
            rows.append({'key': k, 'treatment': 'merge',
                         'reason': 'no old-baseline reference; cannot prove '
                                   'unmodified',
                         'cu_file': cu_file, 'ex_file': ex_file,
                         'ob_file': None})
            continue
        # Triage gate (either/or, deliberately over-inclusive): send to CUupdate
        # if the customer registered a change in the Version List OR the body
        # differs from the old baseline. CUupdate's own no-CU-change
        # short-circuit harmlessly take-A's anything that needs no merge, so
        # over-including costs nothing while under-including risks losing
        # customer work.
        vl_differs = (_version_tokens(os.path.join(customer_dir, ex_file))
                      != _version_tokens(os.path.join(oldbase_dir, ob_file)))
        body = ce.compare_pair(os.path.join(customer_dir, ex_file),
                               os.path.join(oldbase_dir, ob_file))
        body_differs = (body['verdict'] != 'matched')

        if not vl_differs and not body_differs:
            rows.append({'key': k, 'treatment': 'take-straight',
                         'reason': 'customer object unchanged from old baseline '
                                   '(Version List and body both match)',
                         'cu_file': cu_file, 'ex_file': ex_file,
                         'ob_file': ob_file})
        else:
            if vl_differs and body_differs:
                why = 'customer modified vs old baseline (Version List + body)'
            elif vl_differs:
                why = 'customer Version List differs from old baseline'
            else:
                why = 'customer body differs from old baseline'
            rows.append({'key': k, 'treatment': 'merge', 'reason': why,
                         'cu_file': cu_file, 'ex_file': ex_file,
                         'ob_file': ob_file})
    return rows


def stage_merge_job(rows, hq_dir, customer_dir, job_root):
    """Stage the merge objects into the A/<Type>/ B/<Type>/ layout run_batch
    expects: A/<Type>/EX-<key>.txt (customer), B/<Type>/CU-<key>.txt (vendor).
    Returns the count staged.
    """
    n = 0
    for r in rows:
        if r['treatment'] != 'merge':
            continue
        letter, _num = te.split_key(r['key'])
        sub = TYPE_SUBFOLDER.get(letter, letter or 'Other')
        a_dir = os.path.join(job_root, 'A', sub)
        b_dir = os.path.join(job_root, 'B', sub)
        os.makedirs(a_dir, exist_ok=True)
        os.makedirs(b_dir, exist_ok=True)
        shutil.copy2(os.path.join(customer_dir, r['ex_file']),
                     os.path.join(a_dir, f'EX-{r["key"]}.txt'))
        shutil.copy2(os.path.join(hq_dir, r['cu_file']),
                     os.path.join(b_dir, f'CU-{r["key"]}.txt'))
        n += 1
    return n


def run_cuupdate(cuupdate_exe, job_root, cu, initials, date,
                 date_format='DDMMYY', cust='AP,WBL', cust_digits='',
                 vend='PA,PPA,EU,INC,IMM,PS', langs='ENZ'):
    """Invoke CUupdate's batch driver over the staged job_root.

    cuupdate_exe may be the frozen exe (run in batch mode) or, for source runs,
    a path to python + run_batch.py. Returns (ok, output).
    """
    if cuupdate_exe.lower().endswith('.py'):
        cmd = [sys.executable, cuupdate_exe]
    else:
        cmd = [cuupdate_exe]
    cmd += ['--root', job_root, '--cu', cu, '--initials', initials,
            '--date-format', date_format, '--cust', cust,
            '--vend', vend, '--langs', langs]
    if date:
        cmd += ['--date', date]
    if cust_digits:
        cmd += ['--cust-digits', cust_digits]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return False, f'CUupdate not found: {cuupdate_exe}'
    return proc.returncode == 0, (proc.stdout or '') + (proc.stderr or '')


def build_import_set(rows, hq_dir, job_root, import_dir):
    """Assemble the import folder from what is READY:
      - take-straight + new  -> copy the CU object (HQ's new vendor version)
      - merged               -> copy Merged/<Type>/Merged-<key>.txt
    DEV-gated merge objects (no Merged- output) are NOT copied; they are
    returned as the still-needs-manual list so the import set is honestly
    incomplete until they are hand-merged.

    Returns (imported_keys, manual_required_keys).
    """
    os.makedirs(import_dir, exist_ok=True)
    imported, manual = [], []
    for r in rows:
        k = r['key']
        if r['treatment'] in ('new', 'take-straight'):
            shutil.copy2(os.path.join(hq_dir, r['cu_file']),
                         os.path.join(import_dir, f'CU-{k}.txt'))
            imported.append(k)
        elif r['treatment'] == 'merge':
            letter, _num = te.split_key(k)
            sub = TYPE_SUBFOLDER.get(letter, letter or 'Other')
            merged = os.path.join(job_root, 'Merged', sub, f'Merged-{k}.txt')
            if os.path.isfile(merged):
                shutil.copy2(merged, os.path.join(import_dir,
                                                  f'Merged-{k}.txt'))
                imported.append(k)
            else:
                manual.append(k)
    return imported, manual


def treatment_report(rows, imported=None, manual=None):
    """Per-object report: key | treatment | reason, grouped by treatment, with a
    tally. If imported/manual are given, merge objects are split into
    auto-merged vs manual-required.
    """
    manual_set = set(manual or [])
    lines = ['# CU upgrade treatment report',
             '# key | treatment | reason', '']

    def final_treatment(r):
        if r['treatment'] == 'merge':
            return 'manual-required' if r['key'] in manual_set else 'auto-merged'
        return r['treatment']

    order = {'new': 0, 'take-straight': 1, 'auto-merged': 2,
             'manual-required': 3, 'merge': 4}
    decorated = sorted(rows, key=lambda r: (order.get(final_treatment(r), 9),
                                            r['key']))
    tally = {}
    for r in decorated:
        ft = final_treatment(r)
        tally[ft] = tally.get(ft, 0) + 1
        lines.append(f'{r["key"]:<12} {ft:<16} {r["reason"]}')

    lines.append('')
    lines.append('Summary: ' + ', '.join(f'{k}={tally[k]}'
                                         for k in sorted(tally)))
    if manual_set:
        lines.append('')
        lines.append('# MANUAL MERGE REQUIRED before the import set is complete:')
        lines.append('  ' + ', '.join(sorted(manual_set)))
    return '\n'.join(lines)
