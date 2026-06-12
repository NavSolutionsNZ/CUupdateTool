#!/usr/bin/env python3
"""Drive the Stage 3 executor on ONE language-stripped object pair.

Usage:
  python3 run_one.py <Cust_A.txt> <CU_B.txt> <out_Merged.txt> \
      --cu CU26Q1 --initials RL --text "CU upgrade." --date 08/06/26

Inputs must already have the language layer stripped (native cmdlet in prod).
Prints either "MERGED -> <out>" or "DEV: <reasons>" (route to manual merge).
"""
import argparse, sys
import execute as ex

# Census-derived prefixes/languages. In production these come from Stage 0;
# hardcoded here to match the current prototype.
CUST = {'AP', 'WBL'}
VEND = {'PA', 'PPA', 'EU', 'INC', 'IMM', 'PS'}
LANGS = {'ENZ'}

p = argparse.ArgumentParser()
p.add_argument('cust'); p.add_argument('vend'); p.add_argument('out')
p.add_argument('--cu', required=True)
p.add_argument('--initials', required=True)
p.add_argument('--text', default='CU upgrade.')
p.add_argument('--date', required=True, help='DD/MM/YY')
p.add_argument('--cust-digits', default='',
               help='customer prefixes that require trailing digits to count '
                    'as a token (comma-separated, e.g. AP); blank = optional')
a = p.parse_args()

CUST_DIGITS = {s.strip().upper() for s in a.cust_digits.split(',') if s.strip()}

params = dict(cu_token=a.cu, initials=a.initials, text=a.text,
              merge_date=a.date, merge_date_dots=a.date.replace('/', '.'))

# no-CU-change short-circuit: if the vendor made no change to this object, A is
# already correct against the new CU - leave A untouched (no merge, no stamp).
import diffengine as de
if de.DiffEngine(a.cust, a.vend, CUST, VEND, LANGS,
                 cust_digit_required=CUST_DIGITS).no_cu_change():
    print(f"NO CU CHANGE -> {a.cust} (vendor unchanged; use A verbatim, no merge)")
    sys.exit(0)

try:
    merged = ex.execute(a.cust, a.vend, CUST, VEND, LANGS, params)
except ex.GateToDev as g:
    print(f"DEV: {g}")          # route this object to manual TortoiseMerge
    sys.exit(2)

with open(a.out, 'w', encoding='latin-1', newline='') as f:
    f.write(merged)
print(f"MERGED -> {a.out}")
