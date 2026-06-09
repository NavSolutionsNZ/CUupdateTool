# Building and running the CU Update launcher

`cu_gui.py` is a double-click launcher for the batch merge. It wraps the
existing engine (`run_batch` / `execute` / `diffengine`) and adds nothing to
the merge logic — it only collects inputs, derives the customer tags from the
Stage 0 census, runs the batch, and shows the report.

## Run it directly (any machine with Python)

```
python cu_gui.py
```

tkinter ships with CPython, so no extra install is needed for local use.

## Freeze to a standalone .exe (for the server, no Python installed)

The server has no Python, so build a self-contained executable **once** on any
Windows machine that does have Python:

```
pip install pyinstaller
pyinstaller cu.spec
```

This produces `dist\CUupdate.exe` — a single file that bundles the interpreter
and all engine modules. Copy that one file to the server and double-click it.
Nothing else needs to be installed there.

(The `.exe` can only be built on Windows; PyInstaller does not cross-compile.
Build on Windows, deploy the resulting `.exe` to the server.)

## Using it

1. **Job folder** — pick the folder that contains the `A\` and `B\` subfolders
   (the language-stripped customer and CU objects). You can point it straight at
   the server location; files are read and written in place.
   - `A\<Type>\EX-<stem>.txt` (customer)
   - `B\<Type>\CU-<stem>.txt` (CU/vendor)
2. **CU token** (e.g. `CU26Q1`), **Initials** (e.g. `RL`), **Changelog text**
   (default `CU upgrade.`), **Date** (defaults to today, `DD/MM/YY`).
3. Click **Run merge**.

Customer tags are derived automatically from each object's Version List by the
census — you do not enter them.

## What happens to the files (unchanged from `run_batch`)

- **Auto-merged** → written to `Merged\<Type>\Merged-<stem>.txt`; the two source
  files move to `AautoMerged\` and `BautoMerged\`.
- **Manual review / DEV** → left in place in `A\` and `B\`. Whatever remains in
  `A\` and `B\` after a run is the manual TortoiseMerge queue.
- **Errors / unmatched** → left in place, listed in the report.

Use the **Dry run** checkbox to classify without writing or moving anything.
