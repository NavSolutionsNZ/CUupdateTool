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
a = p.parse_args()

params = dict(cu_token=a.cu, initials=a.initials, text=a.text,
              merge_date=a.date, merge_date_dots=a.date.replace('/', '.'))

try:
    merged = ex.execute(a.cust, a.vend, CUST, VEND, LANGS, params)
except ex.GateToDev as g:
    print(f"DEV: {g}")          # route this object to manual TortoiseMerge
    sys.exit(2)

with open(a.out, 'w', encoding='latin-1', newline='') as f:
    f.write(merged)
print(f"MERGED -> {a.out}")
