#!/usr/bin/env python3
"""
triageengine.py -- vendor-delta triage for the CU upgrade process (Stage 1).

Compares the Existing vendor baseline against the New vendor baseline to find
the objects the vendor changed or added in the new CU. Those are the objects
that must land in the customer DB; everything identical between the two
baselines is dropped, which is the filter that removes the manual slog.

Comparison policy (deliberately STRICTER than the gold oracle):
  - BODY-ONLY: the OBJECT-PROPERTIES header (Date/Time/Modified/Version List)
    and the doc-trigger are excluded. The vendor re-stamps these every CU on
    untouched objects, so including them would flag nearly everything -- pure
    noise.
  - WHITESPACE-SIGNIFICANT: unlike the gold check, re-nesting / indentation
    changes DO count as a vendor change. This is a baseline-building pass: any
    real vendor edit, including layout, should flow into the new baseline now so
    next CU's baseline matches the vendor's current formatting and we stop
    carrying a permanent cosmetic delta forward.

Body extraction reuses compareengine._body_only (strip header + doc-trigger);
only the equality test differs (strict, no whitespace collapse). No fork of the
strip logic.

Verdicts per object key:
  changed   present in both baselines, bodies differ        -> needs to land
  new       present only in the New baseline (vendor added) -> needs to land
  removed   present only in the Existing baseline           -> vendor dropped it
  unchanged bodies identical                                -> dropped (no action)

`changed` and `new` together are the object set to carry into the customer DB.
"""
import os
import sys

# Import the comparison engine (sibling package). Path insert keeps this working
# both from source (repo root on path) and from a frozen build where modules sit
# at top level.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, '..', 'compare'),
           os.path.join(_HERE, '..')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import compareengine as ce  # noqa: E402


# Object type letter -> NAV type name, for the type-grouped export report.
TYPE_NAME = {
    'T': 'TABLE', 'C': 'CODEUNIT', 'P': 'PAGE', 'R': 'REPORT',
    'X': 'XMLPORT', 'Q': 'QUERY', 'M': 'MENUSUITE', 'N': 'TABLEDATA',
}
# Display order for the report (tables first, then dependent types).
TYPE_ORDER = ['T', 'C', 'P', 'R', 'X', 'Q', 'M', 'N']


def _strict_body(path):
    """Return the comparable body of an object: header + doc-trigger stripped,
    but whitespace preserved verbatim (strict). Reuses the engine's
    body-extraction; differs only in NOT collapsing whitespace.
    """
    return ce._body_only(ce.read_lines(path))


def bodies_differ(path_a, path_b):
    """True if the two objects' bodies differ (strict, whitespace-significant).

    Header and doc-trigger are excluded via _body_only; everything else is
    compared line-for-line with no normalisation, so indentation/re-nesting
    counts as a difference.
    """
    return _strict_body(path_a) != _strict_body(path_b)


def split_key(key):
    """('T', '18') from 'T18'. Returns (None, key) if it has no leading letter."""
    if key and key[0].isalpha():
        return key[0].upper(), key[1:]
    return None, key


def triage_baselines(existing_dir, new_dir):
    """Compare Existing vs New vendor baselines by object key.

    Returns a dict:
      {
        'changed':   [(key, existing_file, new_file), ...],  # bodies differ
        'new':       [(key, new_file), ...],                 # only in New
        'removed':   [(key, existing_file), ...],            # only in Existing
        'unchanged': [key, ...],                             # identical (dropped)
        'unkeyable': [(side, filename), ...],
        'collision': [(key, side, [filenames]), ...],
      }
    """
    def index(folder, side):
        keyed, collisions, unkeyable = {}, {}, []
        for f in sorted(os.listdir(folder)):
            if not os.path.isfile(os.path.join(folder, f)):
                continue
            k = ce.object_key(f)
            if k is None:
                unkeyable.append((side, f))
                continue
            if k in keyed:
                collisions.setdefault(k, [keyed[k]]).append(f)
            else:
                keyed[k] = f
        for k in collisions:
            keyed.pop(k, None)
        return keyed, collisions, unkeyable

    e_keyed, e_coll, e_unkey = index(existing_dir, 'existing')
    n_keyed, n_coll, n_unkey = index(new_dir, 'new')

    changed, unchanged = [], []
    for k in sorted(e_keyed.keys() & n_keyed.keys()):
        ef, nf = e_keyed[k], n_keyed[k]
        if bodies_differ(os.path.join(existing_dir, ef),
                         os.path.join(new_dir, nf)):
            changed.append((k, ef, nf))
        else:
            unchanged.append(k)

    new = sorted((k, n_keyed[k]) for k in n_keyed.keys() - e_keyed.keys())
    removed = sorted((k, e_keyed[k]) for k in e_keyed.keys() - n_keyed.keys())

    collision = ([(k, 'existing', v) for k, v in sorted(e_coll.items())]
                 + [(k, 'new', v) for k, v in sorted(n_coll.items())])
    unkeyable = sorted(e_unkey + n_unkey)

    return {
        'changed': changed,
        'new': new,
        'removed': removed,
        'unchanged': unchanged,
        'unkeyable': unkeyable,
        'collision': collision,
    }


def _group_by_type(keys):
    """Group a list of object keys by type letter, preserving TYPE_ORDER and
    sorting numbers numerically within each type. Returns [(type_letter, [nums])].
    """
    buckets = {}
    for k in keys:
        letter, num = split_key(k)
        buckets.setdefault(letter, []).append(num)

    def numkey(n):
        return (0, int(n)) if n.isdigit() else (1, n)

    ordered = []
    seen = set()
    for letter in TYPE_ORDER:
        if letter in buckets:
            ordered.append((letter, sorted(buckets[letter], key=numkey)))
            seen.add(letter)
    # Any unexpected type letters after the known ones.
    for letter in sorted(b for b in buckets if b not in seen and b is not None):
        ordered.append((letter, sorted(buckets[letter], key=numkey)))
    return ordered


def export_report(result):
    """Pipe-separated, type-grouped object list for export from NAV.

    The objects that must land in the customer DB = changed + new. New objects
    are also listed in their own section so they are visibly distinct (a new
    object imports cleanly, no merge risk).

    Example:
        TABLE: 18|36|5050
        CODEUNIT: 80|90

        NEW (no merge needed):
        PAGE: 9000|9001
    """
    changed_keys = [k for k, _e, _n in result['changed']]
    new_keys = [k for k, _n in result['new']]

    lines = []
    lines.append('# Objects to carry into the customer DB (vendor-changed + new)')
    lines.append('# Pipe-separated object numbers, grouped by type.')
    lines.append('')

    all_keys = changed_keys + new_keys
    if all_keys:
        for letter, nums in _group_by_type(all_keys):
            name = TYPE_NAME.get(letter, letter or '?')
            lines.append(f'{name}: {"|".join(nums)}')
    else:
        lines.append('(none -- no vendor changes between the two baselines)')

    if new_keys:
        lines.append('')
        lines.append('# NEW objects (vendor-added; import straight, no merge):')
        for letter, nums in _group_by_type(new_keys):
            name = TYPE_NAME.get(letter, letter or '?')
            lines.append(f'{name}: {"|".join(nums)}')

    if result['removed']:
        lines.append('')
        lines.append('# REMOVED in new CU (present in Existing, gone in New) '
                     '-- review:')
        for letter, nums in _group_by_type([k for k, _f in result['removed']]):
            name = TYPE_NAME.get(letter, letter or '?')
            lines.append(f'{name}: {"|".join(nums)}')

    return '\n'.join(lines)


def summary(result):
    """One-line tallies for the GUI/console status."""
    return (f"changed={len(result['changed'])}, new={len(result['new'])}, "
            f"removed={len(result['removed'])}, "
            f"unchanged={len(result['unchanged'])}, "
            f"collision={len(result['collision'])}, "
            f"unkeyable={len(result['unkeyable'])}")


def stage_new_baseline(result, new_dir, out_dir):
    """Copy the NEW-baseline copy of every changed + new object into out_dir.

    These are the vendor objects that must land in the customer DB. For changed
    objects this is the new vendor version (the B-side a later merge would use);
    for new objects it is the object itself (imports straight). Returns the list
    of filenames staged.

    Stage 1 stops here -- it does not fetch customer objects or run any merge.
    """
    import shutil
    os.makedirs(out_dir, exist_ok=True)
    staged = []
    for _k, _ef, nf in result['changed']:
        shutil.copy2(os.path.join(new_dir, nf), os.path.join(out_dir, nf))
        staged.append(nf)
    for _k, nf in result['new']:
        shutil.copy2(os.path.join(new_dir, nf), os.path.join(out_dir, nf))
        staged.append(nf)
    return staged
