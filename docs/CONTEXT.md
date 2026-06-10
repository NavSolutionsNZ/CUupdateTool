# CUupdateTool — Project Context & Decision History

Companion to `ARCHITECTURE.md`. This captures *how* the design was reached, the evidence behind
each decision, the test-object inventory, and the open work — so anyone picking this up
(company-wide) has the reasoning, not just the rules.

---

## 1. Problem

incadea / BC-NAV **v14** customers run **idealer** (incadea standard) plus local customisations and
localisations. We need to carry those customisations forward when idealer ships a new cumulative
update. Reference case: a customer on **idealer CU202301** upgrading to **idealer CU2026Q1**.

Reusable across customers and CU jumps. Distributed company-wide, so anything customer-specific
must be **discovered**, never hardcoded.

## 2. The two instances we actually have

- **A** = customer: idealer + customisations, at the *from* CU.
- **B** = idealer 2026Q1 (vendor target), the *to* CU.
- We do **not** have clean vanilla idealer 202301. Early designs assumed we'd reconstruct it by
  stripping customer tags; this was **abandoned** once we confirmed customer changes are identified
  directly from tags (code) / documentation trigger + structural diff (pages/reports/fields), using
  A and B only. No reconstructed baseline is needed or used.

## 3. Key decisions, in the order they were made, with the evidence

1. **Don't use customer objects as the merge BASE.** Would zero out the customer delta and silently
   let idealer overwrite customisations (e.g. C80's posting-validation override would vanish).
2. **B is genuinely vanilla idealer**, not a customised build. Its PA/EU/INC/PPA tags are idealer's
   own. Confirmed by the user: incadea standard = "idealer"; common tags between A and B are vendor.
3. **Layer split by tag prefix:** vendor/keep = PA, EU, INC, PPA (+ later IMM, PS); customer/carry =
   AP, WBL (+ IMM/PS shown vendor by the in-both test). Validated by A∩B vs A-only presence.
4. **Pipeline ordering (cheap filters first):** Killme retire → Modified=No→take B → normalised
   A==B→take B → type-aware difference handling. Predicted "thousands of objects, only hundreds
   changed"; confirmed (e.g. C80 9k lines, customer delta = 2 blocks).
5. **Tag grammar** is incadea `// Start <prefix><id>` … `// Stop <prefix><id>`; ids include digits,
   dots, and hyphens (`PA035804.26149`, `WBL-006`, `AP-2362`). **Registry-anchored longest-prefix
   match** (so PPA ≠ PA). Discovered a real bug where greedy alpha matching ate the id — fixed.
6. **Agentic tag census (Stage 0):** scan all objects, infer prefix layer from in-both→vendor /
   A-only→customer, corroborated by customer Version List tokens; auto-classify when confident,
   prompt only on ambiguity. On real data: zero prompts. Nothing hardcoded.
7. **Layer-aware integrity:** defect in a customer block → STOP; defect in a vendor block → WARN +
   continue. Justified because idealer ships its OWN tag defects (`// Srop PA035804`, `// Stat
   EU…`, dangling opens) present identically in A and B — we must not halt on incadea's typos.
8. **Type-aware routing** (the central architectural split):
   - Code-bearing (Codeunit, Table-triggers): tag-driven transplant.
   - Structure-bearing (Page, Report, Table FIELDS): doc-trigger + structural diff (tags not
     expected; absence of tags ≠ unchanged).
   Forced by P21: a page with customer changes (version list WBL10/AP-2362) but ZERO body tags.
9. **Tables are hybrid:** code (tagged triggers) + structure (untagged field adds). T36 added fields
   50090-50097 untagged, documented as `AP001651 … Added Consignment fields 50090,50091,50096,
   50097`. Scope rule clarified: exclude customer-range *objects* (50000-99999), but customer fields
   *inside* a vendor object are carried forward, not dropped.
10. **Documentation trigger** is the customer's change manifest (a changelog at the tail of CODE:
    `<TAG> <DD.MM.YY> <initials> <description>`). Primary signal for structure-bearing objects,
    enrichment for code objects. User's insight; verified on P21 (WBL10 "Add field 'Purchase Order
    No. Mandatory'", AP-2362 FactBox work) and T36/T39. Free text → gates auto vs dev, never trusted
    as complete; structural diff confirms.
11. **"Take B" for untagged differences is scoped to CODE objects only.** For pages/reports an
    untagged-but-different region goes to DEV (don't silently lose untagged page work). Deliberate,
    on record; the one remaining silent-overwrite path, confined to where tag discipline holds.
12. **Language/localisation layer is discovered, not hardcoded.** Census infers it like tags:
    in-both code = base/development language; A-only code = customer layer. This customer: ENU base,
    ENZ (English NZ) customer layer; another customer could be DEU/FRA/NLD or several. Handled via
    **native cmdlets** `Export/Remove/Import-NAVApplicationObjectLanguage`. **Compile-only goal** —
    translation correctness is the local developer's job; no drift/translation reporting.
13. **Three content classes for code blocks** (the third discovered during the scorer build):
    - PURE_ADD — added lines only → auto-transplant if anchors survive.
    - VANILLA_MOD — commented original + replacement → auto only on high score + positional
      original-survival; else DEV.
    - VANILLA_SUPPRESS — commented vendor out, no replacement ("Remove short VIN check") → **always
      DEV** (re-suppressing vendor logic is a human call).
14. **Auto-transplant vs DEV** decided by a confidence score; VANILLA_MOD has a higher bar and
    requires the overridden original to survive at the anchored position. Conservative thresholds,
    every verdict logged for later tuning. Manual merges use a separate (future) merge-assist tool;
    review is two-phase (auto → pause → dev resolves → resume) with a self-contained side-by-side.

## 4. Anchor scorer — what was built and fixed

The scorer decides, per customer code block, TRANSPLANT vs DEV. Two false-positive bugs were found
and fixed (both "existence vs position"):
- Vendor-tag anchors were matched **globally**; now require **positional coherence** + **structural-
  boundary-aware** walking (stop at procedure/trigger/field/section boundaries). Fixes T36 AP001651
  (block inside a wholly customer-authored procedure absent from B) — was false TRANSPLANT, now DEV.
- VANILLA_MOD overridden-original was matched **globally**; now validated only **within the anchored
  region**. Fixes C80's coincidental `TESTFIELD` matches.

**Result: 19/19 known-answer cases pass across 22 blocks / 7 objects.** No false TRANSPLANT (the only
dangerous direction). False DEVs are correct-conservative (e.g. T38 WBL-009@1441 — first statement in
field 43's OnValidate, legitimately needs trigger-survival confirmation).

Files: `scorer.py` (the scorer), `test_scorer.py` (known-answer harness — extend the EXP dict and
rerun when adding objects). Prototype is **Python**; chosen for executable iteration in-session. The
production tool is **PowerShell** (must call the dev-shell cmdlets) — port pending.

## 5. Test-object inventory (the evidence set)

Pairs of `Cust_<obj>.txt` (A) and `20206Q1_<obj>.txt` (B). NOT committed if customer-confidential —
confirm before adding to the repo.

| Object | Type | Why it mattered |
|---|---|---|
| T14  | Table 14 Post Code | first object; revealed `Srop` typo, nested/interleaved tags |
| C80  | Codeunit 80 Sales-Post | VANILLA_MOD (commented TESTFIELD); idealer's own tag defects in both A&B |
| T36  | Table 36 Sales Header | hybrid: untagged field adds 50090-50097; AP001651 in customer-only proc (Page 50091) |
| R790 | Report 790 Calc Inventory | VANILLA_SUPPRESS (`//END;`); clean pure-add |
| P21  | Page 21 Customer Card | NO body tags; doc-trigger manifest; ENZ localisation layer |
| P5025649, R5025607 | custom-range Page/Report | untagged/structural cases |
| T38, T39 | Tables | IMM/PS vendor prefixes; WBL/AP customer; VANILLA_MOD & SUPPRESS; field-trigger anchors |
| T5025400 | Table (idealer 5025xxx range, IN scope) | confirms 5025xxx ≠ excluded customer range |

Census inference validated across all: vendor = PA/EU/INC/PPA/IMM/PS (in both A&B); customer =
AP/WBL (A-only). Language: ENU base (in both), ENZ customer layer (A-only); C80 has no captions.

## 6. Open work (UPDATED — see §8.8 for the latest session's detail)

1. **Prefix census (Stage 0) — NOW TOP PRIORITY.** Last silent-loss gap: customer CODE BLOCKS under
   an undeclared prefix are missed while the doc trigger carries their changelog entry (object claims
   a change it lacks). Build a census helper using the DOC TRIGGER as discovery source (it lists every
   customer tag). See §8.8.
2. **Structural differ** — DONE (`diffengine.py`); sees field-section + CODE-section code. Caption/
   OptionCaption/OptionString carry DONE (tag-independent, §8.8). Doc-trigger carry by set-difference
   DONE (prefix-independent, §8.8). Remaining polish: §8.5.1 field-TRIGGER scorer↔field line-range
   join; §8.5.2 RDLC report handling.
3. **Known-answer harness** — DONE (`test_diffengine.py`): T14 (field-graft+code), T36 (DEV-route),
   T77 (caption/option carry). All reproduce fixtures / gate correctly. scorer 20/20.
4. **Stage 3 execution** — DONE (field-graft + code transplant + caption/option carry + bookkeeping +
   doc-trigger set-difference carry). Whole-object gate. `execute.py` + `run_batch.py`/`run_one.py`.
5. **Scorer threshold tuning** — PURE 0.75 / VMOD 0.90; tune from real-run logs. VANILLA_MOD
   auto-transplant path unexercised in TRANSPLANT direction (all real VANILLA_MOD → DEV so far).
6. **Language extract/reattach** — mechanics resolved (§8.4); fixture-prep stripper built (NOT
   production). Still to WIRE native cmdlets into the pipeline (compile-only).
7. **PowerShell port** — port scorer + engine + executor; instance wrapper around v14 dev-shell.
8. **Merge-assist tool** (separate) — ingests dev-resolved objects into the merged set.
9. **Two-phase orchestration & reporting** — batch runner is a first cut (auto-merge + move done files
   out, leave manual worklist in A/B). Fuller: pause at side-by-side review → resume; ledger.

## 7. Working principles (consistent throughout)

- Discover what varies (tags, languages); infer from evidence; auto-proceed when confident; prompt
  only on genuine ambiguity.
- Do the confident mechanical work; route every uncertain/semantic call to a human.
- Never silently lose **whole** customer elements; small untagged deltas inside shared nodes are an
  accepted, on-record risk (caught at compile/UAT).
- Prefer native NAV cmdlets over re-implementing (language layers, merge, compile).
- Validate against real objects with known answers before trusting any heuristic.
- **Diff finds everything; tags justify.** Identify differences FIRST, then justify each by tag
  layer. Never search by tag first (silently misses untagged/odd-form changes).

---

## 8. Session log — difference-driven engine, brace tags, pipeline stages, language mechanics

This section is the authoritative current state. Read it before continuing.

### 8.0 The A/B/C model (locked terminology — A and B are EQUAL inputs to C)
- **A** = old vendor base + customer code (customer's current object). Read-only input.
- **B** = new vendor standard / CU2026Q1. Read-only input.
- **C** = the MERGE of A and B: B's vendor content + A's customer content, the latter RE-ANCHORED
  into B's upgraded context. C is the output (built in stage b). A and B are both first-class
  contributors — C is NOT "B with tweaks". Anchors are LOCATED IN B; customer content TAKEN FROM A;
  both written into C. B is never mutated.

### 8.1 Pipeline stages (agreed structure; compartmentalised, each emits an inspectable artifact)
- **Stage 0 — Census & intake.** Discover tag prefixes (vendor/customer) + language layers from
  A vs B; confirm via a modal (small: paths + confirm inference). Emits the registry.
- **Stage 1 — Determine changed objects.** Killme→retire, Modified=No→take B, normalised A==B→take B.
  Object export to .txt + language extract happens at this boundary (see 8.4). Emits changed-set.
- **Stage 2 — Classify changes.** scorer (code) + diffengine (structural) → per-change verdict
  (AUTO vs FLAG). NO merging. **This is what we are building now.** Emits the classified ledger.
- **Stage 3 — Execute auto-merges.** Build C: copy B, transplant/graft customer content at
  re-anchored positions, canonicalise drifted tags. Emits merged objects + audit.
- **Stage 4 — Flagged objects.** Side-by-side review, dev resolves, ingest. (Two-phase pause is the
  3→4 seam.)
- **Stage 5 — Completion.** Reattach language layer onto C, final integrity check.
- **Stage 6 — DB/instance, compile, deploy to merged tier (non-prod gated).**
Python prototype scope = Stage 2 brains (scorer + engine). Stages 0,1,3,5,6 are PowerShell; Stage 4
is UI+ingest.

### 8.2 Tag grammar — TWO standard incadea styles (both now handled in scorer AND engine)
- line-comment:  `// Start <tag>` … `// Stop <tag>`
- block-comment: `{ Start <tag>` …   `Stop <tag>}`  (braces are C/AL block-comment delimiters — the
  ENTIRE inner content is commented-out/suppressed vendor code). A brace block with no replacement
  is VANILLA_SUPPRESS → always DEV. CRITICAL bug fixed: brace inner was read as live code →
  false PURE_ADD→TRANSPLANT, which would have silently REINSTATED vendor logic the customer
  deliberately suppressed (T5025400 VIN-length check, WBL-006@1360). Scorer now 20/20.
- Tag matching is hyphen/dot-insensitive: VL `WBL009` == body `WBL-009` (`cf()` canonical-fold).
  Canonical form = the Version List spelling. Drift (e.g. body WBL-009 vs VL WBL009) is FLAGGED in
  stage a, and CANONICALISED into C in stage b so the NEXT upgrade reads clean tags. Bare `WBL`
  stays bare (never invent an id). Customer tags are carried as-is into C (their provenance);
  vendor/CU/date stamping is NOT done — B already IS the CU standard.

### 8.3 The difference-driven engine (`diffengine.py`) — verdict logic (CURRENT, CORRECT)
Diff A vs B (language-layer-normalised) into added / removed / changed control/field nodes (node
identity = control-ID, matched only within the parsed tree — a control-ID can also appear as a
PROCEDURE name, do not confuse). Then justify each difference by tag layer:
- A-only node, **customer Description tag** → CARRY (graft WHOLE field; identity = Description tag,
  NOT an inline code tag — a new field's inner code block travels with it, no separate scorer call).
- A-only node, **customer doc-trigger entry justifies it** (quoted name in node props) → CARRY
  (doc-graft). **Doc justification takes PRIORITY over a misleading vendor Description tag** on an
  A-only field (P5025649: field 1101353001 carries vendor `Description=PA038441` but doc "Add
  External Document No." is the true justification → CARRY, not vendor-deletion).
- A-only node, **vendor-tagged only** → TAKE_B (vendor deletion — B dropped it).
- A-only node, **untagged AND undocumented (whole field)** → DEV (a whole missing field can fail
  silently; keep safe). e.g. T38 field 70000 "RUID".
- **changed** shared node: customer code block inside → route to SCORER (TRANSPLANT→CARRY / DEV);
  customer-tagged caption override (base lang) only → CARRY (carry customer caption forward, e.g.
  T36 fields 11/100: customer "Customer Order No." vs CU "Your Reference" — MUST keep);
  customer-tagged other-property change → DEV; no customer tag → TAKE_B (vendor change, incl.
  untagged delta inside shared node = accepted risk); incoherent → DEV.
- **removed** (B-only) node / any B-only tag → TAKE_B (new tags ONLY ever appear in B = vendor
  upgrade; a customer can never introduce a new tag in this 2-object compare).

**Updates since original (§8.13–§8.14):** a changed shared node can be BOTH code AND caption/option —
they are NOT either/or. A field with a code block in its trigger AND an extended OptionString/
OptionCaptionML now emits a scorer-routed code row AND a caption CARRY (the caption carry also brings
the field's `Description=` tag list, subset-guarded). Separately, EXECUTION-layer carries that aren't
verdict rows: customer GLOBAL VAR declarations (A-only in the object-level VAR section) are carried so
dependent code compiles (§8.14). Caption/option carry rule: ALWAYS carry customer caption/option on
any such difference, tag not required (§8.8).

Validated verdicts on the corpus (ALL CORRECT): T14 WBL 50000 graft; T36 AP001651 50090/91/96/97
graft; T36 AP2308 11/100 caption-carry; P21 WBL10 doc-graft (anchor after B 5452600); P5025649 WBL
doc-graft; T38 70000 DEV; code fields (T38 4/43/5050, T39 6/5025358, T5025400 1) → scorer.
The engine reports a verdict for EVERY diff; most are TAKE_B vendor upgrades (e.g. T36 214 diffs,
6 customer) — proves it misses nothing.

### 8.4 Language layer — mechanics RESOLVED (do not re-litigate)
- Determine languages by **census** (in-both→base/development language; A-only→customer layer),
  **confirm in the modal** (discover-then-confirm; never hardcode, never blind-ask). Validated:
  base ENU (both A&B), customer ENZ (A-only), clean high-volume signal across all objects.
- **Sequencing (PowerShell):** object-export-to-.txt FIRST, THEN language-extract. The PS language
  cmdlets operate on exported .txt, NOT the live DB. (The Object Designer GUI does both at once,
  which is why "extract before export" felt right — in PS the text export must precede.)
  - Stage 1: `Export-NAVApplicationObject` A,B → .txt; `Export-NAVApplicationObjectLanguage
    -Source A.txt -LanguageId ENZ -Destination A-ENZ.txt` (stash); `Remove-NAVApplicationObjectLanguage
    -Source A.txt -LanguageId ENZ -DevelopmentLanguageId ENU` (strip for clean compare; normalise B too).
  - Stage 5: `Import-NAVApplicationObjectLanguage -Source C.txt -LanguagePath A-ENZ.txt -Destination
    C-final/` (reattach; Import does NOT modify source — writes to Destination, consistent with C-is-output).
  - `-DevelopmentLanguageId` defaults ENU but is inferred (a DEU-base customer needs DEU). Goal is
    COMPILE-CLEAN reattach only; translation correctness is the local dev's job; no drift reports.

### 8.5 KNOWN ROUGH EDGES (current as of §8.14)
1. **scorer↔field attribution** in `diffengine._scorer_verdicts` is keyed by TAG, so every block of
   a tag attaches to every field bearing that tag (verdict still correct — any DEV → field DEV — but
   the detail is noisy/misattributed). FIX: key scorer blocks by LINE RANGE; match each field's code
   blocks to scorer blocks within that field's line span. STILL OPEN. (§8.7 added a separate
   CODE-section code-row path that IS keyed by line/span; the field-TRIGGER attribution issue remains.)
2. **RDLC report layout** (R5025607 "Add header and footer") not surfaced — the change lives in the
   base64 RDLC blob which isn't parsed into nodes. Needs: detect a customer doc entry whose desc
   matches RDLC/layout keywords → DEV with detail. STILL OPEN.
3. ~~No known-answer harness for diffengine~~ **RESOLVED (§8.7)** — `test_diffengine.py` (verdict +
   execution layers). Fixtures now cover T14, T36, T77, T80, T81. T38 bare `WBL` SIGNED OFF: stale VL
   token → IGNORE.
4. ~~Census prefixes hardcoded~~ **RESOLVED (§8.9)** — `census.py` derives `--cust` from Version
   Lists; `cu_gui` runs it automatically. (LANGUAGES still default-driven, not yet census-derived —
   the per-customer language census of §4 / ARCHITECTURE is the remaining piece.)
5. **END; indentation on transplant** — the tool does a VERBATIM block transplant, preserving the
   customer's original indentation; a hand-merge may re-indent (e.g. a block's inner END; to its
   BEGIN scope). Decided: leave verbatim (compiles; tidy later). The diffengine EXEC harness encodes
   the verbatim form. (§8.13)
6. **Local (in-procedure) VAR additions not carried.** §8.14 carries customer GLOBAL var
   declarations (object-level VAR). A customer adding a LOCAL var inside a vendor procedure is a
   different, unhandled case — none seen yet; would surface as an undeclared-local compile error.
7. **Tight-bracket scoring credit widens auto-merge** (§8.13). Intentional and suite-green, but it
   lowers the bar for what auto-merges; user is watching DEV→auto transitions as-you-go.
8. **T270 / T288** (multi-DC5.00 objects) still gate to DEV despite the §8.13 DC5.00 fixes — likely
   a shape those fixes don't cover. Next candidates to investigate if more auto-merge coverage wanted.

### 8.6 Repo state / files (current as of §8.14 — RESTRUCTURED layout, see §8.11)

**Layout (§8.11 restructure):**
```
cuupdate/   the tool (what the .exe is built from), a package with __init__.py
            cu_gui.py    double-click launcher (entry point) — §8.10
            census.py    Stage 0 customer-tag census from Version Lists — §8.9
            run_batch.py callable run() + CLI — drives a whole job
            execute.py   Stage 3 executor (transplant, caption/option+Description
                         carry, global-VAR carry, header, doc-trigger)
            diffengine.py difference-driven classifier
            scorer.py    anchor/confidence scorer (20/20)
            run_one.py, strip_lang_fixture.py   dev utilities
tests/      test_scorer.py, test_diffengine.py, test_census.py
            fixtures/    known-answer data (T14,T36 stripped; T77,T80,T81 EX/CU/MyMerged)
samples/    the flat Cust_*/20206Q1_* pairs (ad-hoc/dev use, NOT runtime)
docs/       ARCHITECTURE.md, CONTEXT.md, BUILD.md, README_run.md
cu.spec     PyInstaller recipe (kept at ROOT; build cmd: `pyinstaller cu.spec`)
README.md   top-level layout overview
```

**Key facts:**
- `structdiff.py` + `test_structdiff.py` were **RETIRED** (§8.11 — dead checkpoint, used by nothing
  live). Do not expect them in the repo.
- Build: `pyinstaller cu.spec` on Windows → single `dist\CUupdate.exe` (no Python on server). The exe
  bundles `cuupdate/` at build time and depends on nothing in the repo at runtime — only the exe goes
  to the server. Confirmed working on the server (§8.12 era). BUILD.md has details.
- Run GUI from source: `python cuupdate/cu_gui.py`. Tests: from `tests/`, `python test_*.py`.
- All three harnesses pass: scorer 20/20, diffengine PASS (T14/T36/T77/T80/T81), census 5/5.
- Test objects `Cust_*` / `20206Q1_*` (now in `samples/`) CONFIRMED OK to remain (no sensitive info).
- PAT note: user is aware; do not re-raise.
- Prototype is Python; production target is PowerShell (must call dev-shell cmdlets).
- "Discuss first, push later" — confirm decisions before coding; no push without explicit approval.

### 8.7 Session log — Stage 3 EXECUTION engine + CODE-section visibility fix + runners
**Outcome: the tool now actually MERGES, not just triages. T14 (the common basic case) auto-merges
to a byte-exact reproduction of the hand-merge; T36 routes to DEV. Pushed (b133b01, 8c145d1).**

**MCP question (the session's opening topic): assessed and REJECTED for now.** Workflow is fully
deterministic with no LLM/agent in it; MCP only adds value when an agent consumes it. Introducing MCP
would mean first introducing nondeterminism into the one place the design's safety argument depends
on. Future seam IF ever wanted: a READ-ONLY MCP server over emitted artifacts for Stage-4 dev review
(query the ledger / pull side-by-side evidence), never a path into differ/scorer/transplant. Not built.

**Workflow captured (user's real manual process being automated):** select by `Modified` field →
export language layer → build xls + pipe-separated number filter → export+split from CU DB via cmdlet
→ prefix `CU-`/`EX-`, fold by type → TortoiseMerge each file by hand → join by type → import + compile
-troubleshoot (defer missing-dependency failures, repeat) → reattach language → hand to consultants.
Weeks per customer. **The bulk of TortoiseMerge time is MECHANICAL** ("merge the block, bump version
list + date, add doc-trigger comment"), not hard judgement — confirming the triage+EXECUTE design.

**Merge conventions FROZEN (from hand-merged T14 + T36, language-stripped):**
- **A-after-B placement** (user's TortoiseMerge habit: A differences placed AFTER B's): customer
  content inserted after the corresponding B content / anchor. This is the locked placement rule.
- Code block: insert verbatim A span at the scorer's validated `chosen` before-anchor +1. Carry the
  block's adjacent blank line on each side (A-after-B spacing).
- Field-graft: insert whole A field node verbatim after its surviving anchor sibling node in B.
- Header: Date = merge date DD/MM/YY; reassert Modified=Yes; PRESERVE B's Time field as-is; append CU
  token to **A's** Version List token list (A carries customer tokens; B is vanilla).
- Doc-trigger: B's changelog stays; then append A's customer-tagged entries not in B (verbatim, with
  continuation lines), in A order; then append ONE CU stamp line LAST:
  `      <CUtoken padded to 11> <DD.MM.YY> <initials> <text>` at 6-space indent.
- Three per-run params (confirmed): CU token (e.g. CU26Q1), initials (e.g. RL), boilerplate ("CU
  upgrade."). merge_date_dots = merge_date with '/'→'.'.
- Normalisation (TortoiseMerge artifacts, NOT convention): CRLF→LF, trailing whitespace, doc-trigger
  leading indent. Harness compares modulo these.

**CRITICAL ENGINE FIX — CODE-section visibility (was a silent code-loss risk):** `classify()` only
modelled FIELD-section nodes; customer code in object-level / `CODE{}` triggers/procedures was scored
by the scorer but NEVER surfaced as a ledger row. So the whole-object gate was BLIND to it — an
executor would ship a half-merged object missing that code. For T14 (the common basic case!) two of
its three customisations (AP001651, WBL code blocks in CODE section) were invisible. FIX: after the
per-node loop, `classify()` now emits a `code` row for every scorer block not already attributed to a
field node (`_scorer_blocks` helper; carries span + `chosen` anchor). Surfaced that T36 ALSO has
CODE-section blocks, some scoring DEV → T36 correctly routes to DEV (was under-reported before).

**Stage 3 executor (`execute.py`) — NARROW PATH:** executes `field-graft` + `code` CARRY rows only
(verbatim transplant + bookkeeping). **Whole-object gate:** auto-execute ONLY if every non-TAKE_B row
is a CARRY executable kind; ANY other row (caption, DEV, doc-graft, property-modify…) routes the WHOLE
object to DEV untouched, no partial merges. Trusts scorer/`_insertion_anchor` for placement (never
recomputes — user: "trust the anchor"). Raises `GateToDev(reasons)` when gating.

**NOT YET in the executor (route to DEV for now):** caption-carry execution (so T36's caption rows
gate it to DEV even though field-grafts are clean); VANILLA_MOD/SUPPRESS (always DEV by scorer rule);
RDLC. **Next obvious execution path = caption-carry** (would let objects like T36 partially qualify).

**Runners (`run_batch.py`, `run_one.py`):** batch walks `<root>/A/<Type>/EX-<stem>.txt` +
`<root>/B/<Type>/CU-<stem>.txt` (stem = TypeChar+Number: C/T/P/R; e.g. Table 14 = T14). Inputs already
language-stripped. Auto-merged → write `<root>/Merged/<Type>/Merged-<stem>.txt` and MOVE both sources
to `AautoMerged/`+`BautoMerged/` (mirror subfolders) so only manual objects remain in A/ and B/ as the
worklist. DEV/error → left in place, reported. `--dry-run` previews. Census prefixes overridable.
Batch output verified byte-identical to validated T14 fixture.

**`strip_lang_fixture.py` (fixture-prep only):** strips ENZ; collapses single-survivor brackets
KEEPING the `ENU=` prefix (cmdlet form: `[ENU=x;ENZ=y]`→`ENU=x`, NOT bare `x` — user caught this bug);
promotes a lone-ENZ caption (no ENU sibling) to ENU ("change ENZ to ENU", user's rule). Handles 4
forms: bracketed single-line, bracketed multi-line, single-quoted TextConst, bare single-language.
cp1252 encoding. NOT production — production language handling stays `Remove-NAVApplicationObjectLanguage`.

**Process note:** user flagged that discuss-first was being over-applied to the point of never pushing.
Calibration: settle DESIGN before building (done thoroughly); once spec agreed + tests green, SHIP by
default — don't gate every commit on another approval. Carry this forward.

**Next session candidates (SUPERSEDED — see §8.8 for current state and next steps)**

### 8.8 Session log — caption/option carry, doc-trigger set-difference, prefix-dependency narrowed
**Outcome: caption/OptionCaption/OptionString now carry customer values on ANY difference (tag-
independent); doc-trigger entries now carry by SET DIFFERENCE (prefix-independent). Two real bugs from
a user test (T77) fixed. Prefix-census dependency now narrowed to code-blocks ONLY. Pushed 25acb10,
8688148. README full run instructions pushed 16947cf.**

**Test case T77 (Table 77 Report Selections) — user ran the batch, reported a wrong auto-merge.**
Now a frozen fixture/known-answer case (first CAPTION/OPTION-carry execution case). Files in `fixtures/`:
`EX-T77.stripped.txt`, `CU-T77.stripped.txt`, `MyMerged-T77.stripped.txt` (user's hand-merge = target).
Two root causes found:
1. Field 1 "Usage" had customer-modified `OptionCaptionML` + `OptionString` (customer APPENDED Direct
   Credit options). Tool took B (dropped them). Caption-carry previously (a) required a customer tag,
   (b) only handled `CaptionML`, not options.
2. Two customer doc entries (`DC9.00`, `DC14.0`) dropped because `DC` wasn't in the customer prefix
   list (`AP,WBL`). DC is this customer's Direct-Credit prefix — a CENSUS gap.

**FIX A — caption/option carry, tag-independent (user decision: "always take customer on any caption
difference — low-risk, easy to identify in testing"):**
- `diffengine.classify()` changed-node branch: `(cap_changed or opt_changed) and not other_changed`
  → CARRY `caption` (NO tag required). Covers CaptionML, OptionCaptionML, OptionString.
- New helpers: `_option_differs`, `_opt_caption`, `_opt_string`, `_vendor_options_are_prefix`.
  `_nonlang_noncaption_differs` extended to also strip option props (so an option-only change is a
  caption carry, not "other change" → DEV).
- **WARN (not gate):** if vendor's OptionString is NOT a prefix of customer's (vendor changed options
  mid-list → ordinal-shift risk), the row gets `warn=True` and the reason notes it. Carry still
  proceeds per user rule; flagged for tester to eyeball. (T77: vendor changed nothing mid-list, clean.)
- `execute.py`: new `caption` executable kind. `_carry_caption(b_lines, engine, node_id)` replaces B's
  CaptionML/OptionCaptionML/OptionString property lines with A's, IN PLACE (line count preserved so
  later graft anchors stay valid). Applied as a first pass before line insertions.

**FIX B — doc-trigger carry by SET DIFFERENCE, prefix-independent (user insight: "the doc trigger
WILL include tags not on the version list; can we just merge the section?"):**
- `_customer_doc_entries` no longer filters on `_layer(tag)=='customer'`. Now carries ANY A changelog
  entry whose exact stripped line is absent from B. Rationale: an entry in A-not-B is a customer
  addition by definition (vendor base can't have entries the older customer object lacks; newer vendor
  entries live in B and are kept since we build on B). Verified on T77: A-not-B = exactly {DC9.00,
  DC14.0}; B-not-A = newer vendor EU entries (correctly kept from B). Exact-line match cleanly
  separates 37 shared / 2 carried, no false dupes.
- This is a UNION merge (keep all B entries incl. newest vendor; append A's customer entries; then CU
  stamp last) — NOT "take A's section wholesale" (would lose vendor's new entries) nor "take B's"
  (would lose customer's).

**PREFIX-DEPENDENCY STATUS (important):** caption/option carry AND doc-trigger carry are now BOTH
prefix-independent. The customer-prefix census now matters in ONLY ONE place: `// Start TAG` customer
CODE BLOCKS (the scorer needs to know TAG is a customer prefix to score the block as customer code).
Objects whose only customisations are fields / captions / options / doc entries are now fully
prefix-independent. **Proven:** T77 output is byte-identical with vs without `DC` in the prefix list
(it has no DC code blocks).

**THE REMAINING DANGER (next session priority):** if a customer has tagged CODE BLOCKS under an
undeclared prefix, those blocks are silently missed AND the doc trigger now faithfully carries the
changelog entry describing them → merged object CLAIMS a change it doesn't contain. So prefix census
still matters for any object with customer code blocks. **The doc trigger is the natural DISCOVERY
source for the prefix list** (it reliably lists every customer tag, incl. undeclared ones).

**Harness now: T14 (field-graft+code, reproduces fixture), T36 (routes to DEV — has DEV-scored code),
T77 (caption/option carry, reproduces fixture). Per-object customer-prefix overrides added
(`CUST_OVERRIDE`, T77→{AP,WBL,DC}). `_norm` now collapses internal doc-trigger tabs (TortoiseMerge
artifact — user's hand-merge had a tab in the CU line; tool emits clean canonical spaces).
scorer 20/20 still green.**

**Commits this session:** 16947cf (README full run steps), 25acb10 (caption/option carry),
8688148 (doc-trigger set-difference).

**NEXT SESSION — agreed direction:** build the **prefix-census helper** using the DOC TRIGGER as the
discovery source. Read the doc trigger across a customer's A-side objects, extract every tag prefix
with counts, present customer-vs-vendor guess for user confirmation → produces the `--cust` list
before a batch. This closes the last silent-loss gap (code blocks under undeclared prefixes) and is
the natural first slice of Stage 0 census.
Other open items still pending: §8.5.1 field-trigger scorer↔field attribution by line range;
§8.5.2 RDLC keyword→DEV; a code-block-heavy 4th fixture to harden multi-insert ordering;
optionally delete superseded structdiff.
Operating procedure UNTIL census exists: before running a customer, pass their FULL customer-prefix
set via `--cust` (e.g. this customer = AP,WBL,DC — confirm there are no others). Wrong/missing prefix
silently drops customer CODE BLOCKS.

### 8.9 Session log — Stage 0 prefix census (`census.py`)
**Outcome: Stage 0 prefix census built and tested. Determines the customer-tag set for a job by
reading Version List headers. `census.py` + `test_census.py` added (5/5 groups pass). scorer 20/20
and diffengine harness still green.**

**CORRECTION to §8.8 framing (important):** §8.8 named the DOCUMENTATION TRIGGER as the prefix
discovery source. That is wrong. The **Version List** header field is the authoritative, curated
source — it is where the customer's declared tags live. The doc trigger is the OPPOSITE: the one
place we merge blind by set-difference precisely because we do NOT mine it for prefixes (§8.8's
caption/doc-trigger carry work stands; only the "doc trigger = census source" claim is superseded).

**The census's one job (user's words):** determine customer tags. Downstream, when the scorer hits a
merge decision on a `// Start TAG` block, it checks whether TAG is a customer tag → if so the customer
code is carried into the merge. The census does NOT make merge decisions, does not know about code
blocks, does not care where a tag appears. It hands the scorer a membership set, nothing more.

**Rules (locked):**
- Read `Version List=...;` from each A-side object's OBJECT-PROPERTIES.
- Split on commas, strip whitespace, drop empties / trailing `;`.
- Prefix = leading `[A-Za-z]+` run, uppercased (NAVW1.x→NAVW, N.7.2.1→N, AP001651→AP, WBL→WBL,
  ESKER1.0→ESKER).
- **Option A vendor filter (user choice):** a token is vendor if the raw uppercased token STARTS WITH
  any exclusion entry. Default exclusions: `PA,EU,PPA,N.7,AR,LA,NAV,INC`. The filter is a CONVENIENCE
  to keep the candidate list clean — NOT a merge-decision set, and deliberately NOT coupled to
  run_batch's `--vend`. A prefix is vendor only if EVERY token under it is vendor; one
  customer-looking token makes the whole prefix a candidate. Nothing auto-runs off the census; the
  human confirms the proposed `--cust`.
- Undeclared-prefix danger (the §8.8 worry) is RESOLVED by convention, not code: mis-tagged customer
  code that escapes the census is removed/identified on test or compile and re-added with correct
  tags. Census authority rests on the Version List being the curated truth; defects surface
  downstream, so this doubles as housekeeping.

**Discovery:** walks `A/<Type>/EX-*.txt` (matches run_batch). `--loose` also scans flat `Cust_*.txt`
under root (pre-A/-tree convenience; used to validate against the repo's 10 sample objects).

**Validated against the 10 repo objects:** customer tags = AP, ESKER, WBL; excluded vendor = N, NAVW.
ESKER (from T38, `ESKER1.0`) confirmed by user as a real customer tag — the census surfaced it, user
made the call (exactly the intended confirm-step behaviour).

**Output:** plain confirmable table (customer tags + counts, excluded-vendor line) + optional JSON
artifact (`--out census_prefixes.json`) carrying `cust` plus per-prefix evidence (tokens/objects) for
audit. NOT auto-consumed by run_batch — kept as an inspectable boundary; user confirms then passes
`--cust`. Wiring a `--census` reader into run_batch is a deferred separate change (not done; awaiting
direction).

**Files:** `census.py` (NEW), `test_census.py` (NEW, 5 groups). Committed + pushed this session.

**Next-session candidates:** optionally wire run_batch `--census` artifact reader; §8.5.1
field-trigger scorer↔field attribution by line range; §8.5.2 RDLC keyword→DEV; code-block-heavy 4th
fixture; optionally delete superseded structdiff.

### 8.10 Session log — double-click launcher (`cu_gui.py`) + freezable exe
**Outcome: GUI launcher wrapping the existing batch, plus PyInstaller spec to freeze a
standalone server .exe. `run_batch` refactored (extract-only) to expose a callable `run()`.
All harnesses green (scorer 20/20, diffengine, census 5/5); CLI output unchanged; end-to-end
GUI code path merges T14 correctly.**

**Driver:** the tool was too disconnected to run end to end. Operator wants a double-click
executable. Server constraint: **no Python on the server**, but a **bundled PyInstaller .exe is
acceptable** (user confirmed). Work happens on the server folders in place — no file moving.

**Decisions (user-confirmed):**
- Operator picks ONE **job folder** that contains `A\` and `B\` (this is what `run_batch` needs —
  do NOT redesign run_batch; match its inputs). Not two independent A/B pickers.
- **Folder-to-folder batch** (run_batch), not single-object.
- Census runs **automatically** off A's Version Lists to fill `--cust` (option a, silent — a
  deliberate departure from the usual confirm-before-acting boundary, accepted for convenience).
- Prompt for CU token, initials, changelog text (default "CU upgrade."), date (default today).
- DEV/manual routing is **already handled** by run_batch: auto-merged → `Merged\` + sources moved
  to `AautoMerged\`/`BautoMerged\`; DEV-gated/errors left in place in `A\`/`B\` = the manual queue.
  GUI adds NO routing logic of its own.
- GUI is a **thin wrapper** — one source of truth; the engine/harnesses still own correctness.

**`run_batch` change is extract-only:** body moved into `run(root, cu, initials, date, text=...,
cust=..., vend=..., langs=..., dry_run=...)` which builds the report as a string and returns
`(report, results_dict)`; `main()` now just parses args and calls `run()`. Behaviour and CLI output
verified identical. `cust/vend/langs` accept comma strings or iterables.

**Files:** `cu_gui.py` (NEW, tkinter; imports census + run_batch), `cu.spec` (NEW, PyInstaller),
`BUILD.md` (NEW, build/run/usage), `run_batch.py` (refactored). tkinter ships with CPython so the
GUI runs locally as-is; freeze with `pyinstaller cu.spec` on a Windows box → single `dist\CUupdate.exe`
for the server (PyInstaller can't cross-compile, so that one build step must run on Windows).

**Deferred / not done:** the full package restructure (modules into a `cuupdate/` package, jobs/
samples off the root) was discussed then set aside to keep this change small and reviewable — can
revisit. Wiring run_batch to consume `census_prefixes.json` artifact still deferred (GUI derives
cust live instead).

### 8.11 Session log — repo restructure (kill the noise)
**Outcome: flat root reorganised into cuupdate/ (tool) + tests/ (+fixtures) + samples/ + docs/.
structdiff retired. All harnesses green from new layout (scorer 20/20, diffengine PASS, census
5/5). Behaviour-neutral; .exe rebuild path preserved. User delegated all structural decisions.**

**Driver:** root held code, tests, fixtures, 20 flat sample pairs and docs in one namespace —
hard to tell tool from test data, and unclear what deploys. (Resolved separately: the .exe is
self-contained post-build and depends on NOTHING in the repo at runtime; only the exe goes to the
server. The "TheTool" stale-copy bug was a non-git folder predating commit 411500b's option-carry
fix — fixed by cloning current code and rebuilding.)

**Decisions (Claude's call, user delegated):**
- `cuupdate/` package (with __init__.py) holds the engine + cu_gui + run_one + strip_lang_fixture.
- `tests/` holds the 3 harnesses; fixtures moved to `tests/fixtures/`.
- `samples/` holds the 20 flat Cust_*/20206Q1_* pairs (ad-hoc/scorer/dev use, not runtime).
- `docs/` holds ARCHITECTURE/CONTEXT/BUILD/README_run; new top-level README.md.
- `cu.spec` STAYS at root so the build command is unchanged (`pyinstaller cu.spec`); spec entry
  repointed to `cuupdate/cu_gui.py`, pathex=['cuupdate','.'], structdiff dropped from hiddenimports.
- `structdiff.py` + `test_structdiff.py` RETIRED (git rm) — dead checkpoint, used by nothing live.
- `diffengine.py` dev `__main__` block REMOVED (superseded by test_diffengine; referenced flat
  samples). `scorer.OBJS/CUST/ALL` KEPT (test_scorer depends on them) but OBJS filenames now
  resolve to ../samples/ via __file__ instead of bare CWD names.
- Test sys.path shims repointed to ../cuupdate (test_scorer had a hardcoded /home/claude path —
  fixed). test_diffengine FIX path already resolves to tests/fixtures correctly.

**Run commands now:** GUI `python cuupdate/cu_gui.py`; tests from `tests/`; build `pyinstaller
cu.spec` (root, unchanged).

**Deferred still:** run_batch consuming census_prefixes.json artifact (GUI derives cust live);
§8.5.1 scorer↔field attribution by line range; §8.5.2 RDLC keyword→DEV; doc-trigger indent is
spaces vs gold's tab (cosmetic, inside a comment — non-blocking; raised, not yet actioned).

### 8.12 Session log — operator-readable DEV report
**Outcome: gate reasons translated from internal `code/DEV node=None` jargon into actionable
operator English (customer tag + line number); multi-block objects now list each block with a
count header. Harnesses green (scorer 20/20, diffengine PASS, census 5/5).**

**Driver (user):** `node=1 / node=None` means nothing to the operator. Real server report showed
the DEV section as walls of `code/DEV node=None; code/DEV node=None; ...` - no way to find the
blocks in TortoiseMerge.

**Root insight:** every classifier row already carries `tag` and `line` (diffengine line 68/_row);
the report was discarding both in favour of the useless `node` id. `node=None` just means the block
isn't in a numbered field (trigger/body) - it still has a tag and a line.

**Change:**
- execute.py: new `describe_blocker(r)` formats a row as operator English -
  `customer code block 'AP001691' at line 2995` (keeps `in field N` when node is set). GateToDev
  now carries structured `.rows` too. Gate at the whole-object check uses describe_blocker.
- run_batch.py: DEV report groups per object - single-block stays one line; multi-block prints
  `N blocks need manual merge:` then one indented `- ...` per block (count = manual workload).
- 'not coherently anchored at execution' messages (T80/T81 DC5.00 graft-anchor failures) left
  as-is - distinct failure class, deliberately not folded in.

**Verified on real DEV objects (T36/T38/T39/T5025400):** tags + lines surface correctly; e.g. T38's
untagged customer field 70000 change now visible (was hidden behind node=). Wording deemed
good-enough by user; refine later if needed.

**Note:** the earlier 17/16 vs 20/13 scare was the stale exe, NOT a regression - user re-ran old vs
new exe, both produced identical results. The 25acb10 DEV->TAKE_B fallback flip is being watched
as-you-go, not reverted.

**Files:** cuupdate/execute.py, cuupdate/run_batch.py.

### 8.13 Session log — T80 (DC5.00) fix: phantom row, anchor, coupled code+option, Description carry
**Outcome: T80 now auto-merges byte-exact to the (tool-completed) hand-merge. Five engine changes,
all suite-green (scorer 20/20, diffengine PASS incl. new T80, census 5/5). T80 added as a permanent
known-answer fixture (verdict + execution layers).**

**Reported symptom:** T80/T81 gated with "code block DC5.00 not coherently anchored at execution".
User: this is the 2nd-simplest, extremely common merge shape - must fix. Files uploaded.

**Root causes (several, compounding):**
1. **Phantom spanless row.** A code block inside a FIELD's trigger was emitted TWICE: once by the
   per-field loop (keyed to the field's line, no span/anchor) and once by the whole-object scorer
   (correct span+anchor). The dedup keyed on line number, which differed (field line vs block line),
   so both survived; the spanless one crashed the gate. Fix: per-field loop no longer emits an
   executable code row - the scorer covers every Start/Stop block (verified). Added a coverage
   safety net: a code-bearing field the scorer produced nothing for -> DEV (never silent-drop).
2. **Anchor mis-selection (two parts).**
   (a) `score_block` picked the FIRST valid (before,after) bracket; with a vendor tag reused
       several times in B it anchored far too early. Fix: pick the TIGHTEST bracket (smallest gap,
       tie -> larger pb nearer pa).
   (b) `_anchor` preferred a vendor tag even when found far past a nearer distinctive code line
       (e.g. '//INC2.00' right above the block). Fix: balance - record nearest code line AND
       nearest vtag; prefer the vtag only when it's at least as near.
   (c) Side-effect: T39@31 (clean unique adjacent code bracket) then scored 0.6 < PURE_T and
       regressed to DEV. Fix: credit a TIGHT chosen bracket (gap <= block_span+2) up to PURE_T -
       the tightest-bracket selection already guarantees the closest valid pair, so a small gap is
       an unambiguous home even with code-type anchors. Re-verified whole scorer suite 20/20.
3. **Coupled code + option in one field.** Field 9 (Type) had BOTH a DC5.00 CASE branch (code) AND
   an extended OptionString/OptionCaptionML + Description tag. The `if has_codeblock:` branch was
   exclusive, so the option carry never ran. Also `other_changed` is necessarily True for such a
   field (the trigger differs by the code), which would have blocked the carry's usual
   `and not other_changed` guard. Fix: in the code-bearing branch, also carry caption/option when
   it differs, WITHOUT that guard (the "other" change is the code, handled by the scorer).
   Factored `_caption_row`.
4. **Description tag-list not carried.** `_carry_caption` replaced CaptionML/OptionCaptionML/
   OptionString but not `Description=` (where the customer's DC tag lives). Fix: carry A's literal
   Description value, SUBSET-GUARDED (only when B's tags are a subset of A's, i.e. customer
   appended; never clobber a vendor-added tag A lacks). Literal carry preserves exact spacing.

**Decisions (user):**
- Anchor option 1 (tightest bracket) chosen over re-doing `_anchor` discovery wholesale.
- END; indent: tool does VERBATIM transplant; the hand-merge had re-indented the block's inner
  END; to its BEGIN scope. User: ignore the indent - it compiles, fixable later. Tool stays
  verbatim. (Screenshot showed TortoiseMerge treating it as 2 changes - the re-position created
  the diff.)
- T80 fixture encoding: REGENERATE gold from the tool, because the user's hand-merge omitted the
  doc-trigger stamp - the tool's output is actually the more complete artifact, and every
  substantive part was independently verified against the hand-merge first.

**Files:** cuupdate/scorer.py (anchor + tight-bracket credit), cuupdate/diffengine.py (phantom-row
removal + coverage net + coupled caption/option), cuupdate/execute.py (Description carry),
tests/test_diffengine.py (+T80 registration, robust failure-sort), tests/fixtures/{EX,CU,MyMerged}-
T80.stripped.txt (NEW).

**Watch:** the tight-bracket scoring credit widens what auto-merges (intentional, suite-green, user
watching DEV->auto as-you-go). T81 was the same "not coherently anchored DC5.00" symptom as T80 -
not separately verified here but should be fixed by the same changes; confirm on next run.

### 8.14 Session log — T81: carry customer global VAR declarations
**Outcome: customer global-variable declarations (present in A's global VAR, absent from B's) now
carry into the merge. T81 auto-merges with VendBankAccG carried. T81 added as a fixture. Suite green
(scorer 20/20, diffengine PASS incl T80+T81, census 5/5).**

**Symptom (user):** T81 MyMerged line 2535 has `VendBankAccG@1101353000 : Record 288` - a global var
the customer added, USED by carried code at lines 401-406, but the tool dropped the DECLARATION.
Merged object wouldn't compile (var used, never declared).

**Why it was invisible:** the node parser only captures object-level field/key `{ N ; ; }` nodes,
not CODE-section VAR declarations. Globals usually carry NO Start/Stop tag, so neither the field
classifier nor the block scorer ever saw it. Silent drop.

**Fix (user decision: option 1 - simplest):** carry any global VAR declaration in A but not in B.
New in execute.py: `_global_var_decls(lines)` locates the object-level (4-space) `    VAR` section
and returns {name: line} for its `      name@id : type;` declarations (stops at first non-decl/
non-blank so it never reaches into a following procedure). `_carry_global_vars(engine)` diffs A vs B
BY VARIABLE NAME (the @id can differ), returns an insertion (added decls, in A's order, at the end
of B's global VAR section) or None. Wired into the existing insertions list so it rides the same
high-to-low application (no index drift). Objects with no customer globals get None -> no change
(verified: T14/T36/T77/T80 untouched).

**Result:** T81 byte-exact to hand-merge except the agreed-cosmetic END; indent (verbatim, per 8.13)
and per-run doc-trigger param text. T80 fix from 8.13 also confirmed working on T81 (same DC5.00
shape) - both auto-merge now; live run showed T80, T81, T5045517 auto-merging.

**Scope note:** carry is by name-diff of the GLOBAL var section only (the single 4-space VAR).
Local procedure VARs are deliberately not touched. If a customer adds a local var inside a vendor
procedure that's a different (unhandled) case - none seen yet.

**Files:** cuupdate/execute.py (+_global_var_decls, +_carry_global_vars, wired into execute),
tests/test_diffengine.py (+T81), tests/fixtures/{EX,CU,MyMerged}-T81.stripped.txt (NEW).

### 8.15 Session log — per-type dispatch layer (Commit 1: Table + Codeunit)
**Outcome: the engine is now object-type-aware via a front-gate in `classify()`. Type is read from
line 1 of the body; Table + Codeunit are validated and run their scoped rule sets; Page/Report/
XMLport route the WHOLE object to DEV until each gets a validated handler. All five existing
fixtures reproduce byte-exact (zero regression); six new type-dispatch assertions added. Suite green
(scorer 20/20, diffengine PASS, census 5/5).**

**Why (user):** "Currently we treat all object types the same." Some rules right for one type misfire
on others — Table-shaped field/caption logic was running against Page CONTROLS / Report DATASET
nodes. Move to per-type functionality.

**Design decisions (user-confirmed before coding):**
1. **Type source: body line 1 ONLY.** `OBJECT <Type> <ID>` is intrinsic and authoritative; filename
   and folder ignored for type. (The old `self.is_report` flag was DEAD — set, read nowhere — so
   nothing depended on it; removed.) A/B type disagreement (or unreadable header) = hard DEV gate.
2. **Rollout order: Table → Codeunit → Page → Report → XMLport.** Table first as it is the proven
   path (T14/T36/T77/T80/T81); Commit 1 really just *formalises* what already works and gates the
   rest. Page is the next real work (nested CONTROLS tree). User will supply Page/Report/XMLport
   real paired samples.
3. **Handler interface:** small per-type scope dict — `fields` / `code` / `doc` / `validated`.

**What changed (`diffengine.py`):**
- `OBJTYPE` regex + `_detect_type()` → `self.obj_type`, `self.type_mismatch` (A vs B). Replaces the
  dead `is_report`.
- `HANDLERS` registry: TABLE=`fields+code+doc,validated`; CODEUNIT=`code+doc,validated`; PAGE/REPORT/
  XMLPORT=`validated=False`. `self.scope` = lookup (unknown type → `_DEFAULT_SCOPE`, not validated).
- `classify()` FRONT-GATE: `type_mismatch` → single `type-mismatch` DEV row, return; not-validated →
  single `type-unsupported` DEV row, return. Both BEFORE any rule runs (no Table rule can touch an
  unvalidated type).
- Field-node sets (`added`/`removed`/`changed`, steps 1–3) gated on `scope['fields']`; step 4 (CODE-
  section scorer pass) stays unconditional (Table + Codeunit both use it). For a Codeunit the field
  sets are empty anyway — gating is belt-and-braces + intent.

**`execute.py`:** `describe_blocker` now renders `type-unsupported` / `type-mismatch` in operator
English ("object type not yet auto-merged by the tool — manual merge").

**`tests/test_diffengine.py`:** new TYPE_CASES against real `samples/` pairs — T14→TABLE(validated),
C80→CODEUNIT(validated), P21/P5025649→PAGE(gated), R790→REPORT(gated) — plus an A/B mismatch case
(Table A + Codeunit B → single DEV row). No new fixtures needed (uses existing samples).

**Verified:** scorer 20/20; diffengine PASS (all 5 exec/verdict fixtures byte-exact + 6 type rows);
census 5/5. Confirmed on samples: T14 runs caption/code/field-graft; C80 runs code only; P21/
P5025649/R790 gate to DEV; Table-A+Codeunit-B gates as mismatch.

**Next (Commit 2): Page handler.** Needs nested CONTROLS-tree parsing (`{ N ; indent ; ControlType }`
parent/child via the indent field — the current flat NODE regex captures id/indent/type but not the
tree), Page-appropriate carries, validated against a new Page known-answer fixture from real pairs.
Then Report (incl. RDLDATA §8.5.2) and XMLport.

**Rough-edge update:** §8.5.2 (RDLC report layout) now sits behind the Report handler — Report gates
to DEV wholesale until that handler is built, so the RDLC blind-spot is no longer a silent-loss risk
(the whole Report is surfaced for manual merge).

### 8.16 Session log — Page handler (Commit 2): doc-graft control add, proven on P14
**Outcome: the Page handler is BUILT and reproduces the P14 hand-merge byte-exact. Two engine/
executor changes (both shared, both Table-suite-green) + doc-graft made executable + the leading-
blank graft spacing Pages need. P14 added as the first Page known-answer fixture (verdict +
execution). PAGE held `validated=False` in PRODUCTION pending P21/P5025649 sign-off (user decision);
the harness temporarily enables PAGE to test P14. Suite green (scorer 20/20, diffengine PASS incl
P14, census 5/5).**

**The P14 example (real pair: Cust_P14 / 2026Q1_P14 / MyMerged-P14):** customer added field
"E-Mail" as Page control `1101353000`, justified ONLY by the doc-trigger entry
`APOP000010 ... Added E-Mail field` (no Description tag on the control itself). Vendor (B)
separately added control `19853700` (EU-tagged) — pure vendor upgrade, taken from B. Merge = B +
E-Mail control grafted after its anchor (control `12` "Phone No.") + header bookkeeping + doc-trigger
carry (APOP000010 + CU26Q1 stamp). Structurally identical to a Table field-graft; only the
node shape (Page control) and inter-node spacing (Pages blank-separate controls) differ.

**Root cause it exposed + fix (shared, Table-green):**
1. `_doc_justifies` only matched names QUOTED IN THE DOC desc against the node. P14's name is quoted
   on the CONTROL (`SourceExpr="E-Mail"`) and bare in the doc ("Added E-Mail field"), so it missed →
   E-Mail wrongly went `untagged-A-only → DEV`. This was a latent Table bug too (a field documented
   "Added Foo field" with no quotes in the changelog would miss identically). FIX: widened the
   matcher to ALSO match a node's own identifier (Field control `SourceExpr` value, or Table field
   Name — the 3rd `;`-column) against the doc text. Added `_node_identifiers()` (len>=2 guard so a
   bare `Code` SourceExpr can't spuriously match). USER-CONFIRMED to widen the SHARED matcher
   (option 1) after verifying the full Table suite stayed green first.
2. `doc-graft` was classified `CARRY` but NOT executable (not in `_EXECUTABLE_KINDS`, no merge-loop
   branch). field-graft and doc-graft are mechanically IDENTICAL (insert whole customer node after
   surviving anchor; only the justification differs — explicit tag vs doc entry). FIX: added
   `doc-graft` to `_EXECUTABLE_KINDS` and folded it into the field-graft branch.
3. Page graft spacing: Pages blank-separate sibling controls; the bare node block produced no blank
   between the anchor and the grafted control. FIX: carry a LEADING blank line on a graft when A had
   one immediately before the node. Guarded on A's actual layout (`e.A[a_line-2]` blank), so Tables
   — which pack fields with NO blank between them — get nothing added (verified suite-green).

**File-convention fixes (user uploaded with a couple of slips — "good reason this tool matters"):**
- First gold `MyMerged-T14.txt` was actually the P14 Page merge mislabelled, AND stamped `CU2601`
  (typo) — discarded. Corrected gold `MyMerged-P14.txt` supplied (stamps `CU26Q1`).
- `Cust-P14.txt` (hyphen) was a copy of the VENDOR object mislabelled as customer — discarded.
- Canonical trio used: `Cust_P14.txt` (A), `2026Q1_P14.txt` (B), `MyMerged-P14.txt` (C).
- Mislabelled files live in the read-only uploads dir; not brought into the repo.

**Customer prefix:** P14's tag is `APOP` (`prefix_of('APOP000010')='APOP'`, not 'AP'); census
classifies it customer, `EU.0200720` vendor. Harness uses `CUST_OVERRIDE['P14']={AP,WBL,APOP}`.

**Fixtures:** `tests/fixtures/{EX,CU,MyMerged}-P14.stripped.txt` (P14 has no ENZ language layer, so
"stripped" == raw normalised). P14 wired into EXPECTED_VERDICTS (1 doc-graft CARRY), EXEC_CASES, OBJ.
New harness machinery: `_validated(type)` context manager + `_type_of(path)` to exercise a
production-gated type's fixture; `PARAMS_OVERRIDE`/`_params_for` (P14's gold was merged 10/06/26, a
different day than the T-fixtures' 08/06/26 — a fixture bakes in its merge date).

**Production state:** PAGE stays gated to DEV (all of P14/P21/P21 verified gating in prod). User
decision: HOLD PAGE-validated until P21 and P5025649 are confirmed against golds — they auto-merge
without error today (18 and 14 caption/doc-graft rows resp.) but carry caption-carry rows not yet
verified on a Page gold; an auto-merge that RUNS is not yet an auto-merge that's RIGHT.

**Next:** obtain P21 + P5025649 golds → verify Page caption-carry on a real gold → flip PAGE to
`validated=True`. Then Report (incl. RDLDATA §8.5.2) and XMLport.

**Files:** cuupdate/diffengine.py (widened `_doc_justifies` + `_node_identifiers`; PAGE stays
validated=False with rationale), cuupdate/execute.py (doc-graft executable + leading-blank graft
spacing), tests/test_diffengine.py (P14 across all layers + `_validated`/`_type_of`/PARAMS_OVERRIDE),
tests/fixtures/{EX,CU,MyMerged}-P14.stripped.txt (NEW).

### 8.17 Session log — Page DEV-routing (P21) + date-format toggle; P5025649 retired
**Outcome: the Page handler now makes the right AUTO vs DEV call on richer Pages. P21 (vendor caption
renames + customer FactBoxes wearing vendor tags + prose-only justification) correctly routes to DEV
for the right reasons instead of making confident-but-wrong decisions. Header date format is now a
per-customer toggle (DDMMYY default / MMDDYY). P5025649 retired, P5025440 added. Suite green (scorer
20/20, diffengine PASS incl P14 auto + P21 DEV-gate + date asserts, census 5/5).**

**Part A — Page DEV-routing (validated against P21).** P21 exposed three issues; all fixed, Table
suite stayed green at each step (changes are shared but guarded):
1. **Caption brace bug.** `_caption_base_differs`/`_opt_*` captured up to `; ] \n` but NOT `}`. A
   Page single-value caption can be the LAST property before the closing brace with no trailing `;`
   (`CaptionML=ENU=General }`), so `}` leaked into the value → 15 FALSE caption-carry positives on
   P21. FIX: add `}` to the stop-class. (Table captions end at `;`, so unaffected — verified.)
2. **Vendor caption rename mistaken for customer override (Issue 2).** P21 controls 1109400039/41:
   the VENDOR renamed 'Quick Customer'→'New Quick Customer' and added tag EU.0200720.199642 in B;
   the customer still had the old caption. The Table-era "always carry customer caption" rule would
   CLOBBER the vendor rename. FIX: `_vendor_touched_node(a,b)` — True when B's Description carries a
   vendor tag A lacks → the caption difference is vendor-driven → suppress the customer caption-carry
   (take B). USER decision: "check the documentation trigger / dev notes and decide" — the new vendor
   tag in B IS that signal.
3. **A-only control with only a vendor tag silently dropped (Issue 3).** P21 FactBoxes 7/9/13/14 are
   customer adds documented under AP-2362 but each control carries `Description=PA035597` (a VENDOR
   tag). Old rule: vendor tag + A-only → silent TAKE_B → DROPPED the customer FactBoxes. From the
   node alone we can't tell "vendor deletion" from "customer add wearing a vendor tag", and the doc
   entry names them by caption (not present in the control props) so prose-matching is unreliable.
   USER decision: route ambiguous-prose Page changes to DEV for now; never silently lose a customer
   element. FIX: vendor-tagged A-only node → DEV (kind still 'vendor-deletion', verdict now DEV).
   No existing fixture used the old silent-TAKE_B path (verified 0 across T14/T36/T77/T80/T81/P14),
   so safe. Net P21: 1 clean doc-graft CARRY + 4 vendor-deletion DEV → whole object gates to DEV.

**Part B — date-format toggle.** NAV writes the header `Date=` in the SOURCE DB's locale. All three
new samples (P14/P21/P5025440) are MM/DD/YY DBs; other customers are DD/MM/YY. The doc-trigger date
is ALWAYS DD.MM.YY (incadea convention, locale-independent — verified across all samples). FIX:
`run_batch.format_merge_dates(date_format, when)` computes today and returns (header per format,
doc-trigger always DD.MM.YY). `run()` gains `date_format='DDMMYY'` (default, NZ/most incadea) and
`date` is now OPTIONAL (defaults to today; explicit override still accepted for fixtures). CLI:
`--date-format {DDMMYY,MMDDYY}`, `--date` no longer required. GUI: radio button (DD/MM/YY default,
MM/DD/YY), date field now blank=today. USER decisions: default DDMMYY; tool computes today (dev only
picks the format). Verified P14 reproduces gold via computed-today MMDDYY.

**Housekeeping (user):** P5025649 "can be deleted from history — not required in the update."
Removed `samples/{Cust_,20206Q1_}P5025649.txt`; added `samples/{Cust_,20206Q1_}P5025440.txt`
(uploaded as 2026Q1_, renamed to repo's 20206Q1_ convention). Type test swapped P5025649→P5025440.
Historical session-log mentions of P5025649 left as a record; current-state refs updated.

**P5025440 — HELD for a paired test (user).** It currently routes to DEV via `property-modify` (the
customer flipped `Visible=FALSE`→`true` on a shared control, tagged WBL). User will add customer tags
and send a tagged version; intent is to run tagged + untagged side by side and prove one FAILS
(routes to DEV) and the other PASSES (auto-merges on the customer tag). Not wired into the harness
yet — awaiting the tagged copy.

**Fixtures:** `tests/fixtures/{EX,CU,MyMerged}-P21.stripped.txt` (NEW; DEV-gate — verdict asserts 1
doc-graft CARRY + 4 vendor-deletion DEV, gate asserts routes to DEV). Harness: P21 in CUST_OVERRIDE
({AP,WBL}), EXPECTED_VERDICTS, OBJ, EXEC_GATED_TO_DEV; `_validated` now also wraps the gate-test loop;
+date-format assertions.

**Production state:** PAGE still `validated=False`. P14 auto-merges (proven); P21 routes to DEV
(proven); date toggle live on CLI+GUI. Flip PAGE on once the Page AUTO/DEV split is signed off across
more objects (incl. the P5025440 tagged/untagged pair).

**Files:** cuupdate/diffengine.py (caption brace fix, `_vendor_touched_node` + caption-carry guard,
vendor-deletion→DEV), cuupdate/run_batch.py (`format_merge_dates`, `date_format` param, optional
`--date`, `--date-format`), cuupdate/cu_gui.py (date-format radio, blank=today, dropped unused
datetime import), tests/test_diffengine.py (P21 DEV-gate across layers, P5025649→P5025440,
date-format asserts), tests/fixtures/{EX,CU,MyMerged}-P21.stripped.txt (NEW),
samples/{Cust_,20206Q1_}P5025440.txt (NEW), samples P5025649 removed, docs/README_run.md (date-format).
