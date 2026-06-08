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

## Run
Preview first (classifies, moves/writes nothing):
    python3 run_batch.py --root /path/to/job --cu CU26Q1 --initials RL \
        --text "CU upgrade." --date 08/06/26 --dry-run

Real run:
    python3 run_batch.py --root /path/to/job --cu CU26Q1 --initials RL \
        --text "CU upgrade." --date 08/06/26

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
                      --initials RL --text "CU upgrade." --date 08/06/26
