# CUupdateTool

Automates the upgrade of customised C/AL objects for incadea (idealer) clients
on BC/NAV v14: takes a customer's current object (A) and the new CU/vendor
object (B) and produces a true two-input merge (C) that carries the customer's
code into the upgraded vendor context.

## Layout

```
cuupdate/     The tool. Everything the .exe is built from.
              cu_gui.py   double-click launcher (entry point)
              census.py   Stage 0: customer-tag census from Version Lists
              run_batch.py / execute.py / diffengine.py / scorer.py
              run_one.py, strip_lang_fixture.py   (dev utilities)
tests/        Known-answer harnesses + tests/fixtures/ data.
samples/      Real paired sample objects (Cust_* / 20206Q1_*) for ad-hoc runs.
docs/         ARCHITECTURE.md, CONTEXT.md, BUILD.md, README_run.md
cu.spec       PyInstaller recipe (kept at root; build cmd unchanged).
```

## Build / run

See `docs/BUILD.md`. In short: `pyinstaller cu.spec` on a Windows box produces
`dist\CUupdate.exe` — a single self-contained file. The exe bundles the
`cuupdate/` modules at build time and depends on nothing in this repo at
runtime, so only that one file goes to the server.

## Tests

From `tests/`: `python test_scorer.py`, `python test_diffengine.py`,
`python test_census.py`.
```
