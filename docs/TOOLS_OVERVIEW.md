# CU Upgrade Tooling — Overview

A suite of three tools that together take a customer through a Business Central /
NAV Cumulative Update (CU) upgrade, from working out what changed to producing an
import-ready set of objects. Each tool is standalone, ships as its own
double-click executable, and can be used independently.

---

## The three tools

### CUupdate — the merge engine

The core tool. Given a customer's customised object (A) and the new vendor
object (B), it produces a merged object (C) that carries the customer's
customisations onto the new vendor version — or routes the object to manual
review when it cannot merge safely. This is the engine the whole upgrade is
built around. It has its own user manual.

**Use it when:** you have paired customer/vendor objects and need them merged.

### CUcompare — the comparison oracle

A validation tool. It compares the merge tool's output against a hand-merged
"gold" version of the same object, to confirm the automated merge reproduced
what an expert would do by hand. It compares the object body only (ignoring
vendor date/version stamps and the documentation trigger) and ignores
whitespace-only reformatting, so it flags real differences in merged code rather
than cosmetic noise.

**Use it when:** you want to build confidence that the merge tool is producing
correct results, by checking it against known-good examples. Once that
confidence is established, this tool is no longer needed for routine runs.

### CU Triage & Pipeline — the upgrade driver

The newest tool, and the one that orchestrates an end-to-end upgrade. Driven by
HQ's list of objects changed in the new CU, it:

1. splits HQ's file into individual objects,
2. fetches the matching customer and old-baseline objects from their databases,
3. classifies each as new, take-straight, or to-merge,
4. runs CUupdate over the to-merge set,
5. assembles an import-ready folder of new + take-straight + merged objects,
   flagging anything that still needs a manual merge.

**Use it when:** HQ has supplied a changed-objects file and you want to triage
and merge a whole customer's upgrade in one place.

---

## How they fit together

```
HQ changed-objects file
        |
        v
  +--------------+      objects the customer modified      +-----------+
  | CU Triage &  | -------------------------------------> | CUupdate  |
  | Pipeline     |   (staged as A = customer, B = vendor)  | (merge)   |
  +--------------+                                          +-----------+
        |                                                        |
        | new + take-straight objects          merged objects (C)|
        v                                                        v
                         Import-ready set
                                |
                                | (validation, during roll-out)
                                v
                          +-----------+
                          | CUcompare | (merged vs hand-merged gold)
                          +-----------+
```

The triage tool is the entry point and orchestrator; CUupdate does the merging
it can't do itself; CUcompare validates the merges during the period when you're
still building trust in the automation.

---

## Where each runs

All three are standalone Windows executables. The triage tool's database-export
step additionally needs the NAV model-tools module and Windows authentication to
the databases; the merge and comparison steps work on object files and do not
touch the databases.

---

## Per-tool documentation

- **CUupdate** — `docs/USER_MANUAL.md` (and `.docx`)
- **CU Triage & Pipeline** — `triage/USER_MANUAL.md` (and `.docx`)
- **CUcompare** — `compare/BUILD.md`
- Build instructions for each — the `BUILD.md` in each tool's folder.
