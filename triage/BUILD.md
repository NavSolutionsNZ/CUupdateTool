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

## Export baselines from the database (optional)

Instead of pointing at two pre-exported folders, the GUI can export both
baselines for you. Fill in the SQL server, the Existing and New database names,
and an export root, then click **Export from DB, then triage**. The tool runs
`triage/scripts/Export-Baseline.ps1` once per database:

- exports all objects up to the incadea dev-license ceiling
  (`Id=1..99008535`, so system/platform objects are skipped),
- splits into one file per object with `-PreserveFormatting`,
- renames to the `<Prefix>-<TypeChar><Id>.txt` convention (`OB-` for the
  existing baseline, `CU-` for the new),

into `root\existing` and `root\new`, then runs the triage on those folders.

Each database has its own NAV service tier (server instance) with its own management port, so the export needs the NAV server (shared host), the per-database instance name, and its management port -- supplied as GUI fields. Without the instance, Export-NAVApplicationObject raises "The Server Instance specified in the Options window is not available".

**Windows authentication only** — the script connects under the identity running
the tool; no credentials are entered or stored. This step requires Windows, the
NAV model-tools module (BC140 RoleTailored Client), and SQL access to the
databases. The module path defaults to the BC140 location and is a parameter on
the script if yours differs.

While testing, the PS1 lives in `triage/scripts/` and ships bundled inside the
exe. Once confirmed, you can keep a copy in a local folder on the SQL box (which
may have no internet access) and point the tool at it.

## CU Pipeline tab (HQ-file-driven, step by step)

When HQ ships a single combined `.txt` of every object changed in the new CU,
the **CU Pipeline** tab drives the rest. It runs as five explicit steps so each
subprocess hop surfaces its own result before the next.

Inputs: the HQ file, a job root (work folder), SQL server + Customer DB + Old
baseline DB, the CUupdate exe (or `run_batch.py`), and the merge parameters (CU
token, initials, date, date format).

1. **Split HQ file** - splits HQ's combined file into `hq/CU-<key>.txt` via
   `Split-Objects.ps1`; lists the object keys found.
2. **Export customer + old baseline** - exports just those keys from the
   Customer DB (`EX-`) and Old baseline DB (`OB-`) into `customer/` and
   `oldbase/`, filtered by object id.
3. **Classify + report** - three-way per object: `new` (customer lacks it),
   `take-straight` (customer Version List and body both match the old baseline),
   `merge` (Version List OR body differs).
4. **Stage + run CUupdate** - stages merge objects into `A/<Type>/` `B/<Type>/`
   and runs CUupdate's batch driver; CUupdate applies its own merge / DEV-gate
   rules.
5. **Build import set** - assembles `Import/` from what is ready (new +
   take-straight vendor objects, plus `Merged-` outputs). DEV-gated objects are
   flagged manual-required and left out - the import set is honestly incomplete
   until those are hand-merged. The final report marks each object new /
   take-straight / auto-merged / manual-required with the reason.

DB export and split run under Windows auth via PowerShell (no credentials
stored); CUupdate runs as the exe/CLI you point at.

## Roadmap (not yet built)

- Collapse the five pipeline steps into one "Run all" button after first real
  runs confirm each hop.
- Optionally drive the join + import of the final `Import/` set.
