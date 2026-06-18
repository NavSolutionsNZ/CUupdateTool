# Building and running CU Compare (the output oracle)

`compare/compare_gui.py` is a double-click launcher for the comparison oracle.
It wraps `compareengine` and adds no comparison logic of its own — it collects
two folders, runs the comparison, and shows the report. The oracle is fully
isolated from the main tool (`cuupdate/`): it imports nothing from the engine.

## What it does

Pairs objects by filename across a GOLD folder (your hand-merged known-answers)
and a CANDIDATE folder (CUupdate.exe output), then judges each pair:

- `matched` — byte-identical above the doc-trigger, same doc-trigger tags.
- `matched-except-header` — differs only on the `Date=` / `Time=` / `Modified=`
  header stamps the tool writes at run time.
- `unmatched` — a real content difference; the report names the C/AL section(s)
  (Version List, Properties, Fields, Keys, Triggers, Controls, Doc trigger,
  Code) and shows the differing lines.
- `missing-candidate` / `missing-gold` — a file present on only one side.

The doc-trigger (the trailing commented-out `BEGIN { ... }` block) is compared
as a **set of customer tags** only — its dates and descriptions are ignored as
noise. A customer tag present in the gold but missing from the candidate means
the tool dropped a customer addition, and is reported as `unmatched`.

## Run it directly (any machine with Python)

```
python compare/compare_gui.py
```

tkinter ships with CPython, so no extra install is needed for local use. For a
quick headless check there is also a CLI runner (not frozen):

```
python compare/run_compare.py <gold_dir> <candidate_dir> [--out report.txt]
```

## Freeze to a standalone .exe (for the server, no Python installed)

The server has no Python, so build a self-contained executable **once** on any
Windows machine that does have Python:

```
pip install pyinstaller
pyinstaller compare.spec
```

This produces `dist\CUcompare_<version>.exe` (e.g. `dist\CUcompare_1.0.exe`) — a
single file that bundles the interpreter and the oracle. The version comes from
`compare/__init__.py`. When the build starts the console prints a banner line
`compare.spec: building CUcompare_<version>.exe`; if you do NOT see that banner,
a stale auto-generated `compare_gui.spec` is being used instead — delete it and
any `build/` cache, then run `pyinstaller compare.spec` again. The build clears
`dist\` first, so only the current version's exe is left behind.

Copy that one file to the server and double-click it. Nothing else needs to be
installed there. Ship a new version by bumping `__version__` in
`compare/__init__.py`, rebuilding, and pasting the new `.exe` across.

(The `.exe` can only be built on Windows; PyInstaller does not cross-compile.
Build on Windows, deploy the resulting `.exe` to the server.)

## Using it

1. **Gold folder** — pick the folder of your hand-merged known-answer objects.
2. **Candidate folder** — pick the folder of CUupdate.exe output for the same
   objects.
3. Click **Run comparison**. A clean run shows just the summary table; objects
   needing a human eye get a DETAIL block beneath it.
4. **Save report...** writes the shown text to a file.

Pairing is by **object key**, not by full filename: the `<Type><Number>` token
after the final `-` and before `.txt` (e.g. `MyMerged-T18.txt` and `EX-T18.txt`
both key to `T18` and pair). This is prefix-agnostic, so gold and candidate
copies of the same object pair even when self-merge naming differs
(`MyMerged-`, `MySanitised-`, `EX-`, ...). If the same key appears twice in one
folder the pair is ambiguous and reported as a `collision` (not compared); a
file with no `-<Type><Number>.txt` tail is reported as `unkeyable`.
