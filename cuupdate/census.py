#!/usr/bin/env python3
"""
census.py -- Stage 0 prefix census.

Discovers the customer prefix set for a job by reading the Version List header
of each A-side object. The Version List is the authoritative, curated record of
what is declared in an object; the prefix census reads it (NOT the doc trigger,
which is merely a place we merge blind by set-difference).

Rule (locked):
  - For each object, read the `Version List=...;` line in OBJECT-PROPERTIES.
  - Split on commas; strip whitespace; drop empties / trailing ';'.
  - Each token's prefix is its leading [A-Za-z]+ run (uppercased).
      NAVW1.x -> NAVW   N.7.2.1 -> N   AP001651 -> AP   WBL -> WBL   ESKER1.0 -> ESKER
  - A token is VENDOR if the raw (uppercased) token STARTS WITH any vendor
    exclusion entry (Option A: token-startswith, tolerant of version junk).
    Everything else is a CUSTOMER candidate.

Nothing here makes a merge decision. A prefix only matters downstream when it
gates a customer `// Start TAG` code block in the scorer. The census merely
PROPOSES a candidate set; the human confirms it. Every discovered prefix is
shown (excluded ones dimmed) so a mis-filtered prefix is always visible to
reinstate or reject. The confirmed list is written to a JSON artifact that
run_batch can be pointed at.

Usage:
    python3 census.py --root /path/to/job
    python3 census.py --root /path/to/job --out census_prefixes.json
    python3 census.py --root /path/to/job --vend PA,EU,PPA,N.7,AR,LA,NAV,INC

Discovery matches run_batch: walks A/ for EX-*.txt. With --loose it will also
scan flat Cust_*.txt files in --root (handy before the A/ tree is laid out).
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

# Convenience filter only -- NOT a merge-decision set. Prefixes matching these
# are pre-dimmed in the table as "likely vendor"; the human still sees and
# confirms everything.
DEFAULT_VENDOR_EXCLUSIONS = ['PA', 'EU', 'PPA', 'N.7', 'AR', 'LA', 'NAV', 'INC']

VERSION_LINE_RE = re.compile(r'Version\s*List\s*=\s*(.*?)\s*;?\s*$', re.I)
PREFIX_RE = re.compile(r'^([A-Za-z]+)')


def read_version_list(path):
    """Return the raw Version List value (text after '=', no trailing ';'),
    or None if the object has no Version List line."""
    with open(path, 'r', encoding='latin-1') as f:
        for line in f:
            m = VERSION_LINE_RE.search(line)
            if m:
                return m.group(1).rstrip(';').strip()
    return None


def tokens_of(version_list):
    """Split a Version List value into clean, non-empty tokens."""
    if not version_list:
        return []
    return [t.strip() for t in version_list.split(',') if t.strip()]


def prefix_of(token):
    """Leading [A-Za-z]+ run, uppercased. None if the token has no alpha lead."""
    m = PREFIX_RE.match(token)
    return m.group(1).upper() if m else None


def is_vendor(token, exclusions):
    """Option A: vendor if the raw uppercased token starts with any exclusion."""
    up = token.upper()
    return any(up.startswith(x) for x in exclusions)


def find_a_objects(root, loose=False):
    """Yield (label, path) for each A-side object.
    Primary: A/<Type>/EX-*.txt (matches run_batch). --loose also takes flat
    Cust_*.txt under root so a census can run before the A/ tree exists."""
    a_root = os.path.join(root, 'A')
    found = []
    if os.path.isdir(a_root):
        for dirpath, _, files in os.walk(a_root):
            for fn in files:
                m = re.match(r'EX-(.+)\.txt$', fn, re.I)
                if m:
                    found.append((m.group(1), os.path.join(dirpath, fn)))
    if loose:
        for fn in os.listdir(root):
            m = re.match(r'Cust_(.+)\.txt$', fn, re.I)
            if m and os.path.isfile(os.path.join(root, fn)):
                found.append((m.group(1), os.path.join(root, fn)))
    return sorted(found)


def census(root, exclusions, loose=False, force_vendor=None, force_cust=None):
    """Build the prefix census. Returns a dict with per-prefix evidence.

    The startswith filter (`exclusions`) is only a FIRST PASS. A developer
    reviewing the dry-run census can correct mis-attributions with two deltas:

      - force_vendor: prefixes the filter left as customer that are really
        vendor (mark vendor; they stop gating customer code-block carries).
      - force_cust:   prefixes the filter swallowed as vendor that are really
        customer (mark customer; they start gating carries).

    Both are sets of bare uppercased prefixes. force_vendor wins ties (a prefix
    listed in both is treated as vendor - the safe direction, since making a
    real customer prefix vendor only drops a carry, never injects vendor code).
    The override is recorded per-prefix as rec['forced'] so the report/artifact
    can show WHY a prefix landed where it did.
    """
    objs = find_a_objects(root, loose=loose)
    if not objs:
        where = "A/<Type>/EX-*.txt" + (" or Cust_*.txt" if loose else "")
        sys.exit(f"no A-side objects found under {root} ({where})")

    force_vendor = {p.upper() for p in (force_vendor or [])}
    force_cust = {p.upper() for p in (force_cust or [])}

    # prefix -> {count, vendor(bool), example tokens, objects seen in}
    prefixes = defaultdict(lambda: {'count': 0, 'vendor': False, 'forced': None,
                                    'tokens': set(), 'objects': set()})
    no_version = []

    for label, path in objs:
        vl = read_version_list(path)
        if vl is None:
            no_version.append(label)
            continue
        for tok in tokens_of(vl):
            pfx = prefix_of(tok)
            if pfx is None:
                continue
            rec = prefixes[pfx]
            rec['count'] += 1
            rec['tokens'].add(tok)
            rec['objects'].add(label)

    # A prefix is vendor only if EVERY token under it is vendor; a single
    # customer-looking token makes the whole prefix a candidate (shown for review).
    # Then apply the developer's review deltas on top. force_vendor wins ties.
    for pfx, rec in prefixes.items():
        rec['vendor'] = all(is_vendor(t, exclusions) for t in rec['tokens'])
        if pfx in force_vendor:
            rec['vendor'], rec['forced'] = True, 'vendor'
        elif pfx in force_cust:
            rec['vendor'], rec['forced'] = False, 'cust'

    return {
        'objects_scanned': [l for l, _ in objs],
        'objects_without_version_list': no_version,
        'prefixes': prefixes,
    }


def print_table(result, exclusions):
    prefixes = result['prefixes']
    cust = sorted(p for p, r in prefixes.items() if not r['vendor'])
    vendor = sorted(p for p, r in prefixes.items() if r['vendor'])

    def mark(p):
        f = prefixes[p].get('forced')
        return ' (forced)' if f else ''

    n = len(result['objects_scanned'])
    print(f"\n=== Stage 0 prefix census ({n} objects) ===")
    print(f"Vendor filter: {','.join(exclusions)}")
    print(f"\nCustomer tags ({len(cust)}):")
    for p in cust:
        print(f"  {p:8} x{prefixes[p]['count']}{mark(p)}")
    if vendor:
        print(f"Excluded as vendor: {', '.join(p + mark(p) for p in vendor)}")
    if result['objects_without_version_list']:
        print(f"No Version List in: {', '.join(result['objects_without_version_list'])}")
    print(f"\nProposed --cust: {','.join(cust)}\n")
    return cust


def write_artifact(out_path, result, exclusions, cust):
    prefixes = result['prefixes']
    payload = {
        'cust': cust,
        'vendor_exclusions': exclusions,
        'objects_scanned': result['objects_scanned'],
        'objects_without_version_list': result['objects_without_version_list'],
        'evidence': {
            p: {
                'count': r['count'],
                'vendor': r['vendor'],
                'forced': r.get('forced'),
                'tokens': sorted(r['tokens']),
                'objects': sorted(r['objects']),
            } for p, r in sorted(prefixes.items())
        },
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
    print(f"Wrote {out_path}  (cust = {','.join(cust) or '(none)'})")


def main():
    p = argparse.ArgumentParser(description="Stage 0 customer-prefix census from Version List headers.")
    p.add_argument('--root', default='.', help='job root (expects A/ under it)')
    p.add_argument('--vend', default=','.join(DEFAULT_VENDOR_EXCLUSIONS),
                   help='vendor exclusion filter (convenience only, not a merge set)')
    p.add_argument('--out', default=None,
                   help='write JSON artifact here (e.g. census_prefixes.json). '
                        'If omitted, only the table is printed.')
    p.add_argument('--loose', action='store_true',
                   help='also scan flat Cust_*.txt in --root (pre-A/-tree)')
    p.add_argument('--force-vendor', default='',
                   help='comma-separated prefixes the filter left as customer '
                        'but are really vendor (re-classify as vendor; they stop '
                        'gating customer code-block carries)')
    p.add_argument('--force-cust', default='',
                   help='comma-separated prefixes the filter swallowed as vendor '
                        'but are really customer (re-classify as customer)')
    a = p.parse_args()

    root = os.path.abspath(a.root)
    exclusions = [s.strip().upper() for s in a.vend.split(',') if s.strip()]
    force_vendor = [s.strip().upper() for s in a.force_vendor.split(',') if s.strip()]
    force_cust = [s.strip().upper() for s in a.force_cust.split(',') if s.strip()]

    result = census(root, exclusions, loose=a.loose,
                    force_vendor=force_vendor, force_cust=force_cust)
    cust = print_table(result, exclusions)

    if a.out:
        out_path = a.out if os.path.isabs(a.out) else os.path.join(root, a.out)
        write_artifact(out_path, result, exclusions, cust)


if __name__ == '__main__':
    main()
