# Building and running CU Triage (vendor-delta triage, Stage 1)

`triage/triage_gui.py` is a double-click launcher that compares two vendor
baselines and tells you which objects the vendor changed or added in the new CU
— the objects that need to land in the customer DB. Everything identical between
the two baselines is dropped, which removes the manual slog of inspecting every
object.

It imports `triageengine` (which reuses `compareengine` for body extraction) and
adds no comparison fork of its own. Isolated from the main tool (`cuupdate/`).

## What it does (Stage 1)

Pairs objects by key (prefix-agnostic `<Type><Number>`, e.g. `CU-T18.txt` keys
to `T18`) across the Existing and New baseline folders, then classifies each:

- `changed` — present in both, **bodies differ** → must land in the customer DB
  (a later stage decides merge vs take-straight against the customer objects).
- `new` — present only in the New baseline → vendor-added, imports straight.
- `removed` — present only in the Existing baseline → vendor dropped it; flagged
  for review.
- `unchanged` — bodies identical → dropped, no action.

### Comparison policy — deliberately stricter than the gold oracle

- **Body-only**: the `OBJECT-PROPERTIES` header (`Date`/`Time`/`Modified`/
  `Version List`) and the doc-trigger are excluded. The vendor re-stamps these
  every CU on untouched objects, so including them would flag almost everything.
- **Whitespace-significant**: unlike the gold check, re-nesting / indentation
  changes **do** count as a vendor change. This is a baseline-building pass — any
  real vendor edit, including layout, should flow into the new baseline now so
  the next CU's baseline matches the vendor's current formatting and we stop
  carrying a permanent cosmetic delta forward.

## Output

A pipe-separated, type-grouped object list ready to paste into a NAV export
filter, e.g.:

```
TABLE: 18|36|5050
CODEUNIT: 80|90

# NEW objects (vendor-added; import straight, no merge):
PAGE: 9000|9001
```

Use that list to export exactly those objects from the customer DB for the next
stage. Optionally, point the tool at a **Stage** folder and it also copies the
New-baseline versions of the changed + new objects there.

## Run it directly (any machine with Python)

```
python triage/triage_gui.py
```

CLI (not frozen):

```
python triage/run_triage.py <existing_baseline> <new_baseline> \
    [--stage <out_dir>] [--report <path>]
```

## Freeze to a standalone .exe

```
pip install pyinstaller
python -m PyInstaller triage.spec
```

Produces `dist\CUtriage_<version>.exe`. The build clears only `CUtriage_*` from
`dist\`, so it coexists with `CUupdate_*` and `CUcompare_*`. Version comes from
`triage/__init__.py`. (Builds on Windows only; PyInstaller does not
cross-compile.)

## Roadmap (not yet built)

- **Stage 2**: add the customer DB export as a third input; split the changed
  set into take-straight (customer-unmodified vs Existing baseline) and ToMerge
  (customer-modified), staging A (customer) and B (new vendor) for CUupdate.
- **Stage 3**: drive the NAV PowerShell export to populate the baseline folders,
  and optionally shell out to CUupdate for the merge cases — keeping the whole
  process in one place. The export step is already a clean seam for this.
