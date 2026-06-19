# CU Triage & Pipeline — User Manual

Version {{VERSION}}

This tool prepares a customer's Business Central / NAV objects for a CU
(Cumulative Update) upgrade. It takes HQ's list of changed objects, works out
which the customer has actually modified, runs the automated merge over those,
and assembles an import-ready set — replacing what used to be a long manual
object-by-object process.

It is a separate tool from **CUupdate** (the merge engine) and **CUcompare**
(the gold-comparison oracle). This manual covers the triage/pipeline tool only.

---

## 1. What the tool does

### 1.1 The problem it solves

When a new CU arrives, only some vendor objects have changed, and of those, only
some have been customised by this customer. Historically you exported and
inspected objects one by one to find which needed merging. This tool narrows the
work automatically:

- HQ now supplies a single file listing every object changed in the new CU.
- The tool fetches the customer's and the old baseline's versions of those
  objects, and decides per object whether the customer touched it.
- Objects the customer never touched are taken straight from the new CU; only
  the ones they modified go through the CUupdate merge.

The result is a much smaller set to merge, and an import folder assembled from
what is ready.

### 1.2 The three treatments

Every object in HQ's changed list ends up in one of three treatments:

- **new** — the customer does not have this object. Take the new CU version
  straight; no merge.
- **take-straight** — the customer has it, but their version matches the old
  baseline (Version List and body both). They never modified it, so take the new
  CU version straight; no merge.
- **to-merge** — the customer's version differs from the old baseline (Version
  List or body). Their customisation must be carried onto the new CU version, so
  this object goes through CUupdate.

After the merge runs, `to-merge` objects resolve to **auto-merged** (CUupdate
merged them) or **manual-required** (CUupdate could not, and they need a hand
merge before the import set is complete).

### 1.3 Two tabs

- **CU Pipeline** — the main workflow described above, driven by HQ's file.
- **Baseline triage** — an older path that compares two vendor baselines (old CU
  vs new CU) directly, for when HQ does not supply a changed-objects file. Kept
  as a fallback.

---

## 2. The CU Pipeline, step by step

The pipeline runs as five explicit steps so each one's result is visible before
the next. Fill in the inputs at the top, then click the step buttons in order.

### 2.1 Inputs

- **HQ changed-objects file** — the single combined `.txt` HQ supplies.
- **Job root** — a working folder. The tool creates `hq/`, `customer/`,
  `oldbase/`, `A/`, `B/`, `Merged/`, and `Import/` under it.
- **SQL server** — the SQL Server hosting the databases.
- **NAV server (shared)** — the NAV service-tier host (one host for all
  instances).
- **Customer DB** — the customer's database, with its NAV instance and
  management port. Exported with the `EX-` prefix.
- **Old baseline DB** — the database for the CU the customer is currently on,
  with its instance and port. Exported with the `OB-` prefix.
- **CUbatch.exe (or run_batch.py)** — see section 3.

Note that the NAV instance name and the SQL database name are often different
(for example instance `iDealer26Q1` but database `iDealer2026Q1_DB`), and each
instance has its own management port.

### 2.2 Step 1 — Split HQ file

Splits HQ's combined file into one file per object (`hq/CU-<key>.txt`, e.g.
`CU-T18.txt`) and lists the object keys found. No database connection needed.

### 2.3 Step 2 — Export customer + old baseline

Exports just the objects in HQ's list from the customer DB (`EX-`) and the old
baseline DB (`OB-`). The export is filtered **by type and id together**
(`Type=Table;Id=18|36`, `Type=Codeunit;Id=80`, ...) so an object id never
over-pulls across types. Runs under Windows authentication — no credentials are
entered or stored.

### 2.4 Step 3 — Classify + report

Compares each object three ways and produces the treatment report (new /
take-straight / to-merge, with the reason for each). The report is saved
automatically to `<CU>_treatment.txt` in the job root, and shown in the output
pane.

The customer-modified test is **either/or**: an object is to-merge if its
Version List **or** its body differs from the old baseline. This is deliberately
over-inclusive — CUupdate's own no-CU-change short-circuit harmlessly takes the
customer version for anything that needs no merge, so over-including is free,
while under-including risks losing customer work.

The comparison is **body-only**: the `OBJECT-PROPERTIES` header
(`Date`/`Time`/`Modified`/`Version List` value) and the documentation trigger
are excluded from the body check, because the vendor re-stamps those every CU.

### 2.5 Step 4 — Stage + run CUupdate

Stages the to-merge objects into the layout CUupdate expects —
`A/<Type>/EX-<key>.txt` (customer) and `B/<Type>/CU-<key>.txt` (vendor) — then
runs CUupdate's batch driver over them. CUupdate applies its own merge rules and
decides auto-merge vs manual review per object, using the merge parameters (CU
token, initials, date, date format) from the panel.

### 2.6 Step 5 — Build import set

Assembles the `Import/` folder from what is ready: the new and take-straight
vendor objects, plus the auto-merged outputs. Objects CUupdate gated to manual
review are flagged **manual-required** and deliberately left out — the import
set is honestly incomplete until those are hand-merged. The final report marks
each object new / take-straight / auto-merged / manual-required.

---

## 3. Running the merge: the batch exe vs run_batch.py

Step 4 drives CUupdate. Point the **CUbatch.exe (or run_batch.py)** field at one
of:

- **CUbatch_<version>.exe** — the headless batch merge executable. This needs no
  Python and no GUI, so it is the right choice on a server. Build it once from
  `cu_batch.spec` (see the CUupdate BUILD docs); it bundles the whole merge
  engine. The triage tool runs it directly with the merge parameters.
- **run_batch.py** — the same batch entry point as a script. Use this only on a
  machine that has Python and the `cuupdate` package present (the tool runs it
  from its own directory so its imports resolve).

Do **not** point the field at the standard `CUupdate.exe` — that is the GUI
build; it ignores batch arguments and just opens the merge window.

The merge parameters (CU token, initials, date, date format) are passed through
to CUupdate. Customer tag prefixes are **not** set here — CUupdate derives them
itself from the objects when it runs.

---

## 4. Date formats

`.txt` import is strict about date format: the dates in the object files must
match the regional setting of the instance they import into, or the import
errors. HQ's files use **DDMMYY**. The merge step's date format therefore
defaults to DDMMYY so the merged output, HQ's take-straight files, and the
import target all agree. Set the import instance's regional setting to match so
direct imports of take-straight objects do not fail on date mismatch.

---

## 5. The Baseline triage tab

This tab is the older, pre-HQ-file path. It compares two vendor baselines
directly:

- Point it at an **Existing baseline** folder (old CU objects) and a **New
  baseline** folder (new CU objects), or export both from their databases using
  the export panel.
- It reports which objects the vendor changed or added between the two CUs, as a
  type-grouped, pipe-separated list ready to paste into a NAV export filter.

Use this only when HQ has not supplied a changed-objects file. When they have,
the CU Pipeline tab is the workflow.

---

## 6. Progress and output

- A busy bar runs along the bottom while any step works, including the steps
  that do not open a PowerShell window, so you can tell the tool is progressing.
- Long exports show a per-phase banner (`[2/4] Exporting ...`) in the output so
  you can see which type group is in progress and how many remain.
- **Save output** writes the current output pane to a file. Step 3 also
  auto-saves its treatment report.

---

## 7. What runs where, and security

- The database export runs on your machine via PowerShell under **Windows
  authentication**. No database credentials are entered into the tool or stored;
  the export connects under the identity running the tool, so that account needs
  read access to each database.
- Object export and split use the NAV model-tools module (BC140). The export
  step requires Windows and that module; it cannot run on a machine without
  them.
- The export script lives in `triage/scripts/` and ships bundled in the exe.
  Once the workflow is stable it can be kept in a local folder on the SQL box
  (which may have no internet access) and pointed at from there.
