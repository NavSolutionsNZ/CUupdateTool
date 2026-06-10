# CUupdateTool — Stage 3 runner (quick start)

Triage + auto-merge for CU upgrades. Auto-merges the basic objects (new field +
small customer code), routes anything uncertain to manual review. Conservative
whole-object gate: an object auto-merges ONLY if every customer block is
confidently CARRY; one uncertain block sends the whole object to manual.

## What you need together in one folder
    run_batch.py      batch driver (main entry point)
    run_one.py        single-pair driver
    execute.py        Stage 3 executor (transplant + bookkeeping)
    diffengine.py     difference engine / classifier
    scorer.py         anchor-survival scorer
Python 3 only, no third-party packages.

## Input layout (files must already be language-stripped by the cmdlet)
    <root>/A/<Type>/EX-<stem>.txt     customer object   (A)
    <root>/B/<Type>/CU-<stem>.txt     CU/vendor object  (B)

`<stem>` = TypeChar + Number:  Codeunit=C, Table=T, Page=P, Report=R.
  Table 14  -> EX-T14.txt / CU-T14.txt
Pairing is by stem; A and B must use the same <Type> subfolder name.

## Run — step by step

### 0. Check Python
Open a terminal (Windows: PowerShell or Command Prompt). Run:
    python --version
If that errors, try:  python3 --version
You need Python 3. Use whichever word works (`python` or `python3`) in the
commands below — on Windows it's usually `python`, on Mac/Linux `python3`.

### 1. Put the tool files together
The five files below MUST sit in ONE folder, and you run the command FROM that
folder (run_batch.py imports execute/diffengine/scorer from alongside it):
    run_batch.py  execute.py  diffengine.py  scorer.py  run_one.py
e.g.  C:\CUtool\

### 2. Lay out the job (inputs already language-stripped by the cmdlet)
    <root>\A\<Type>\EX-<stem>.txt      e.g.  C:\jobs\CustX\A\Table\EX-T14.txt
    <root>\B\<Type>\CU-<stem>.txt      e.g.  C:\jobs\CustX\B\Table\CU-T14.txt

### 3. Open the terminal in the tool folder
    cd C:\CUtool

### 4. Preview first (--dry-run: classifies, writes/moves NOTHING)
    python run_batch.py --root C:\jobs\CustX --cu CU26Q1 --initials RL \
        --text "CU upgrade." --date-format DDMMYY --dry-run

### 5. Real run (drop --dry-run)
    python run_batch.py --root C:\jobs\CustX --cu CU26Q1 --initials RL \
        --text "CU upgrade." --date-format DDMMYY

Set the four values to your job: --cu = CU token, --initials = yours,
--text = doc-trigger boilerplate. --date-format = customer DB date locale
(DDMMYY default / MMDDYY): the header Date= is written in that format; the
merge date defaults to today. Doc-trigger date is always DD.MM.YY.
Mac/Linux: use python3 and forward-slash paths (--root /path/to/job).

## What happens
- AUTO-MERGED: writes  <root>/Merged/<Type>/Merged-<stem>.txt
  and MOVES the two sources into <root>/AautoMerged/<Type>/ and
  <root>/BautoMerged/<Type>/.  -> only manual objects remain in A/ and B/.
- MANUAL/DEV: left in place in A/ and B/ (this is your manual worklist).
- ERRORS: left in place, reported; the batch never crashes on one bad object.

## Census prefixes (IMPORTANT per customer)
Defaults are for the current customer:
    --cust AP,WBL   --vend PA,PPA,EU,INC,IMM,PS   --langs ENZ
For a different customer, pass the correct prefixes or classification will be
wrong. (In production these come from Stage 0 census.)

## Notes / current limitations
- Output is language-stripped C/AL. Reattach the language layer (cmdlet,
  your Stage 8) before join/compile.
- Narrow path auto-merges field-grafts + clean code transplants only.
  Caption-carry and any DEV-scored code route to manual for now.
- Single object:  python3 run_one.py A.txt B.txt out.txt --cu CU26Q1 \
                      --initials RL --text "CU upgrade." --date-format DDMMYY
