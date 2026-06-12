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
- A code block's insertion point was searched **object-wide**, so a block whose anchor text is vendor
  boilerplate repeated across procedures could be carried into the **wrong procedure** (anchor text
  matches, but the variables it reads are out of scope → non-compiling output). Now **confined to the
  block's enclosing procedure**: A's enclosing proc is matched to B's **by `@id` first, name second**
  (vendors rename-without-renumber), and the anchor search is restricted to that B-proc span (after-
  anchor may reach the following boundary, for tail-of-proc blocks). Enclosing proc absent from B →
  whole object to DEV; global-VAR/trigger blocks left unconfined. Fixes T17 AP001994 — `// Start
  PA036544` recurs in 5 procs; was carried into `CopyPostingGroupsFromDtldCVBuf@94` instead of
  `CopyFromGenJnlLine@4`. Identified via T17, frozen as a fixture.
- `_proc_units` span-walk (in **both** `scorer.py` and `diffengine.py`) rewritten to the 4-space-indent
  `BEGIN`/`END;` invariant; the old token-depth count underflowed on `END ELSE BEGIN` and ended procs
  early. Latent in diffengine (proc-graft presence/absence by key); fixed in both to avoid divergence.

**Result: all known-answer cases pass across 8 objects (T14/T17/T36/C80/R790/T38/T39/T5025400);
scorer self-test 20/0, full engine harness reproduces T17 byte-exact.** No false TRANSPLANT (the only
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
- **Keep the distributed docs in sync.** `docs/USER_MANUAL.md` (+ the generated
  `docs/USER_MANUAL.docx`) is a distribution deliverable for developers and managers, and contains
  the Rules Index by object type (the user-facing statement of every auto-merge-vs-manual rule).
  Whenever a change alters tool behaviour, a rule, the pipeline, the GUI, or the supported workflow,
  UPDATE the User Manual (both .md and rebuilt .docx) AT THE SAME TIME as CONTEXT.md / ARCHITECTURE.md
  — same commit. The manual must never describe behaviour the engine no longer has, or omit a rule
  the engine now applies. The .docx is regenerated from the .md (US Letter, navigable TOC,
  screenshots in docs/img/); do not hand-edit the .docx.

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
the field's `Description=` tag list, subset-guarded). Separately: customer VAR declarations (global +
per-procedure local, A-only in the matching-scope VAR block) are carried EXECUTION-side, silent-but-
logged, so dependent code compiles (keep-over-delete, §8.14/§8.20); an option-string VAR the customer
EXTENDED (B's literal a strict prefix of A's) is carried via a CARRY `var-option` verdict row (§8.20).
Caption/option carry rule: ALWAYS carry customer caption/option on any such difference, tag not
required (§8.8).

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

### 8.18 Session log — P21V2 (tagged FactBoxes) auto-merges; same-anchor ordering fix
**Outcome: the P21 pass/fail PAIR is complete and locked. Untagged P21 routes to DEV; P21V2 (same
object, FactBoxes 7/9/13/14 now tagged AP-2362) AUTO-MERGES byte-exact to its gold. Fixing this
exposed a same-anchor graft-ordering bug, now fixed. Suite green (scorer 20/20, diffengine PASS,
census 5/5).**

**P21V2 (user-supplied):** the original Cust_P21 with two deliberate changes — (1) language layer
stripped to cmdlet-clean ENU form, and (2) the four customer FactBoxes given a customer tag:
`Description=PA035597` -> `PA035597,AP-2362` (control 14 is `AP2362`, no hyphen — a typo, but still
resolves to prefix AP so it classifies fine). With the customer tag present, the FactBoxes flip from
`vendor-deletion -> DEV` (ambiguous, Issue 3) to `field-graft -> CARRY` (confident customer adds).
This is the proof the tag does its job: the SAME object routes to DEV untagged, auto-merges tagged.

**Same-anchor ordering bug (found + fixed):** the four FactBoxes graft in two same-anchor pairs
(7 & 9 both anchor after one surviving B sibling; 13 & 14 after another). The executor applied
insertions high-to-low keyed only on the anchor index; when two blocks shared an anchor the high-to-
low pass INVERTED them (output order was 9,7,14,13 instead of 7,9,13,14). FIX: each insertion now
carries a `source_order` (its A line); the sort key is `(after, source_order)` reverse, so same-
anchor blocks land in A-order. The global-VAR insertion uses `source_order=inf` (applies last within
its anchor). No existing fixture has >1 graft per anchor, so the tiebreaker is a no-op for them
(verified suite-green); P21V2 is the case that needed it.

**Gold note:** MyMerged-P21 (V2 gold) has header `Date=06/10/25` (hand-typed year-25 slip) but
doc-trigger `10.06.26` — internally inconsistent on the year. The tool stamps consistently from its
params; the fixture's PARAMS_OVERRIDE matches the gold's literal values so it reproduces byte-exact.
Another small slip the tool would standardise away in practice.

**Fixtures:** `tests/fixtures/{EX,CU,MyMerged}-P21V2.stripped.txt` (NEW; auto-merge fixture). Harness:
P21V2 in CUST_OVERRIDE ({AP,WBL}), PARAMS_OVERRIDE (header 06/10/25, doc 10.06.26, 'CU Upgrade.'),
EXPECTED_VERDICTS (1 doc-graft + 4 field-graft CARRY), EXEC_CASES, OBJ. P21 (DEV) + P21V2 (auto) now
stand as the canonical tagged/untagged pair.

**Production state:** PAGE still `validated=False`. The Page handler now has: clean control add
(P14 auto), vendor caption rename -> take B, ambiguous vendor-tagged add -> DEV (P21), and tagged
add -> auto-merge with correct multi-FactBox ordering (P21V2). Strong basis to consider flipping
PAGE on, pending Rich's sign-off across more real objects.

**Files:** cuupdate/execute.py (source_order tiebreaker on insertions),
tests/test_diffengine.py (P21V2 across all layers),
tests/fixtures/{EX,CU,MyMerged}-P21V2.stripped.txt (NEW).

### 8.19 Session log — PAGE flipped to validated=True (production)
**Outcome: PAGE is now `validated=True` in the production registry. Confident Pages auto-merge;
uncertain ones still route to DEV via the whole-object gate. Rich is taking it for live testing.
Suite green (scorer 20/20, diffengine PASS, census 5/5).**

**What flipping PAGE on does:** every Page now ATTEMPTS auto-merge instead of being gated wholesale.
The gate still protects uncertain cases - flipping does NOT disable safety:
- AUTO-MERGE: clean doc-justified control add (P14); customer-tagged control add incl. multi-add
  same-anchor ordering (P21V2); vendor-driven caption rename -> take B.
- DEV (whole-object gate): ambiguous vendor-tagged add (P21 - vendor deletion vs customer add
  wearing a vendor tag); customer property modification on a shared control (P5025440 property-
  modify). Verified in production-path: P14 auto, P21V2 auto, P21 DEV, P5025440 DEV.

**Harness change:** TYPE_CASES now expects PAGE `validated=True`; P14/P21V2 exec fixtures now run
through the REAL production path (the `_validated` test helper is a no-op for Pages now but kept for
any future gated-type fixture). P21 still asserted to gate to DEV - now via the production path, not
an override. No behavioural test weakened.

**Report/XMLport** remain `validated=False` (gate to DEV) - next handlers to build.

**Files:** cuupdate/diffengine.py (PAGE validated=True + rationale comment),
tests/test_diffengine.py (TYPE_CASES PAGE=True), docs/ARCHITECTURE.md (PAGE production status).

### 8.20 Session log — VAR carry generalised: local scope + option-string append (P347)
**Outcome: the VAR-declaration carry, previously global-only and add/drop-only, now (1) covers
LOCAL procedure VAR blocks as well as the object-level block, and (2) carries an option-string VAR
the customer EXTENDED (B's literal a strict prefix of A's). P347's `ReportUsage2` global option list
now reproduces the hand merge. New frozen fixture P347. Suite green.**

**Driver (Rich):** P347 (Page 347, customer tag DC). Tool output dropped the customer's extension of
the `ReportUsage2@1109400000` inline option list (`...ADR Document` in B vs
`...ADR Document,,,,,Direct Cr. EDI File,...` in A). The old `_carry_global_vars` only ADDED
A-only declarations to the global block; it never inspected values, and never looked inside
procedures. The value-diff was invisible to both the gate and the carry - B's shorter value rode
through silently.

**Design (agreed, discuss-first):**
- **Variables carry NO customer tag** (Rich's correction) - there is no provenance to reason from on
  a declaration line. So carry decisions cannot be "identity match -> take A".
- **RULE 1 — keep over delete (all scopes).** Union of declarations per matching scope (global block;
  each procedure's local block, scoped by owning procedure @id). Any name in A's block absent from
  B's -> carry it. Never drop. Justified purely by the compile-break asymmetry: referenced-but-
  undeclared fails to compile; declared-but-unused is harmless. Silent-but-logged (no classify row,
  no gate) - it only ever ADDS, no judgement.
- **RULE 2 — option-string append carry (all scopes).** Declaration present in BOTH matching blocks
  (same name) where both values are single-quoted literals and **B's literal is a STRICT (character)
  prefix of A's** -> take A's line. This is the option-string-as-text-constant case. LITERAL prefix,
  not token prefix: a customer rename/re-order is NOT a prefix, so it fails the test and falls to the
  whole-object DEV gate (no tag to attribute it -> we don't guess). Surfaced as a CARRY `var-option`
  classify row (gate + DEV-report visibility), consistent with caption carry.
- **Matching:** by variable NAME within a scope (the @id may differ). Name match across A/B in the
  same scope. Locals scoped PER PROCEDURE - never pooled.

**Implementation:**
- `diffengine.py`: `_var_blocks` (scans object-level + every LOCAL/PROCEDURE VAR block, keyed by
  scope), `_var_option_carries` (Rule 2 detection), new step 5 in `classify()` emitting CARRY
  `var-option` rows.
- `execute.py`: `_var_blocks` + `_carry_vars` (Rule 1, all scopes, returns insertions + log) REPLACES
  `_carry_global_vars`; `_carry_var_options` (Rule 2 application - single-line replacement on
  B-derived text, like caption carry, line count preserved). `var-option` added to
  `_EXECUTABLE_KINDS`. Rule 2 applied before insertions shift indices; Rule 1 rides the insertions
  list (apply-last within its anchor).

**Out of scope (deferred, separate fix):** P347 line 118 Description tag drop (`...EU.0074599` vs
hand `...EU.0074599,DC`) - the field-11 OptionString carries correctly via caption carry, but its
Description tag-list `,DC` is not carried on a control whose OptionString changed. The frozen P347
gold therefore reverts that one line to B's value so the fixture is tool-reproducible; the Description
tag carry on option-changed controls is its own item.

**Verification:** P347 reproduces the hand merge byte-exact (modulo agreed normalisation + the two
out-of-scope/cosmetic lines: Description ,DC and the operator stamp wording). T81 (old global-VAR
case) still passes through the generalised `_carry_vars`. Full suite green: diffengine PASS (incl.
P347 verdict + exec), scorer 20/20, census 5/5.

**Files:** cuupdate/diffengine.py (+_var_blocks, +_var_option_carries, +classify step 5),
cuupdate/execute.py (-_carry_global_vars, +_var_blocks, +_carry_vars, +_carry_var_options, +var-option
executable kind, rewired execute), tests/test_diffengine.py (P347 across verdict + exec layers),
tests/fixtures/{EX,CU,MyMerged}-P347.stripped.txt (NEW).

### 8.21 Session log — User Manual + Rules Index deliverable; reproducible docx build
**Outcome: a distribution-quality User Manual now exists at `docs/USER_MANUAL.md` (source) +
`docs/USER_MANUAL.docx` (generated), with section 8 = the Rules Index by object type (the
user-facing statement of every auto-merge-vs-manual rule, with object evidence). Regenerated from
the .md by a single committed script `docs/build_manual.js`. No engine change this session.**

**Audience/scope (agreed, discuss-first):** developers + managers, English-second-language. The GUI
exe is the ONLY supported run path presented to users — the CLI (`run_batch`/`run_one`) is NOT
surfaced in the manual; §7 is just a brief "what's inside the application" overview. Professional
register: full words (no "doc"/jargon/slang). Four real screenshots embedded (`docs/img/`:
gui-launch, gui-running [census line], gui-report [DEV report], folders-after-run).

**Domain corrections captured in the manual (Rich):**
- Language layer is stripped IN THE NAV/GUI DEV ENVIRONMENT BEFORE export (not via standalone
  cmdlet steps); the cmdlets are mentioned only "for reference". Same for re-applying the language
  layer after merge — done in the GUI dev environment as part of import/compile.
- Customer tags are stated as automatic with NO "older instructions had you pass them by hand"
  framing (new users, no history). A new dev CANNOT confirm the full tag set, so the manual does
  NOT ask the operator to verify the census `customer tags` line — it only explains what the line
  reports.
- §8.20 deferred Description-tag item is intentionally LEFT OUT of the user manual (open bug, not
  user-facing behaviour).

**Build mechanics (the one gotcha for future regeneration):** docx-js emits the Table of Contents
as an EMPTY field — so until Word repaginates (F9), EVERY TOC entry shows "page 1", and a non-Word
viewer shows it wrong permanently. `docs/build_manual.js` therefore (1) generates the docx from the
.md, then (2) BAKES real page numbers into the TOC: renders a PDF (LibreOffice via the docx-skill
office helpers), maps each heading to its page (pdfplumber), injects a bookmark per heading, and
replaces the empty TOC field with pre-built hyperlink+page-number entries (dot leaders, level
indent). Result is correct on first open in any viewer and still updatable in Word.
- **DO NOT hand-edit the .docx.** Edit `docs/USER_MANUAL.md`, then run `node docs/build_manual.js`
  (needs: `npm i -g docx`, python3 `pdfplumber`, and the docx-skill office helpers for the bake
  step; if the helpers are absent the script still writes a valid docx but skips the bake and the
  TOC reverts to the page-1 problem until F9).

**Standing rule (added to §7 working principles this session):** keep `docs/USER_MANUAL.{md,docx}`
in sync — update it (and rebuild the docx) IN THE SAME COMMIT as CONTEXT.md/ARCHITECTURE.md whenever
a change alters behaviour, a rule, the pipeline, the GUI, or the supported workflow. The manual must
never describe behaviour the engine no longer has, nor omit a rule the engine now applies.

**Files:** docs/USER_MANUAL.md (NEW), docs/USER_MANUAL.docx (NEW, generated), docs/build_manual.js
(NEW, reproducible builder), docs/img/{gui-launch,gui-running,gui-report,folders-after-run}.png
(NEW), docs/CONTEXT.md (§7 maintenance rule + this §8.21 entry).

---

**§8.22 — Structural ownership before tag-justification; T36 now auto-merges (v1.9)**

Origin: compile errors in the dev env from auto-merged objects (`ShowStatusHistory`,
`GetPostingActionAccessPermission` etc. "unknown variable"). Investigation showed these were
NOT merge defects — they were cross-object compile-ORDER ghosts: a page calling a NEW vendor
function on its source table (T18, T36) before that table was merged/compiled. Clearing T18 then
T36 (recompiling dependents) resolved them. The real lesson for the tool: nothing forces "tables
green first, then unconditionally recompile every dependent page" — a Stage-6 compile-orchestration
gap (two-pass compile script still TODO, independent of this change).

The substantive engine change came from T36 itself, which correctly gated to DEV on 3 blocks but
was in fact safely auto-mergeable:
- Fields **50090/50091** (Consignment, 50000-range, absent from B) carry whole as field-grafts; their
  `OnValidate` code is tagged **AP001691**, a ticket number NOT in the Version List census
  (`AP001651,AP2263,AP2308`). The scorer independently found those blocks, couldn't anchor them
  (no vendor neighbour — the enclosing field is customer-added), scored 0 → DEV, gating the object.
- **GetConsignmentBranchShipmentLines@39** (absent from B, body tagged AP001651) likewise had no
  vendor anchor → scored 0 → DEV.

Fix (agreed rule): **establish structural ownership of the enclosing unit FIRST; only fall back to
census tag-justification for blocks landing inside vendor-owned units.**
- **50000-range fields carry regardless of tagging** (confirmed standing rule). Vendor-range fields
  check `Description=` for an **AP######** customer marker (narrowed to AP — a customer-local ticket
  prefix, never used by the vendor).
- **proc-graft**: a procedure whose `name@id` is absent from B is a customer addition → carry the
  whole unit verbatim (incl. `[Internal]` attr) at end of CODE section. Require a customer tag in the
  unit (guards against a vendor proc renamed in B looking "absent").
- **scorer suppression**: code blocks inside an already-owned atom (added field / proc-graft) are
  carried with it; the scorer no longer emits competing DEV rows for them.

Result: T36 auto-merges (4 field-grafts, 2 captions, 1 code AP2263, 1 proc-graft; **zero DEV**),
reproducing the hand-merge byte-for-byte (procedure at end-of-CODE — the safe unambiguous anchor;
field 7001 ordering is developer-discretion and not load-bearing). P21 still gates (proves no
over-carry). Frozen as an EXEC fixture (`Merged_T36.stripped.txt` regenerated — the prior hand-merge
gold had a dropped `END;` that would not compile; the tool output is the corrected gold).

**Versioning (new standing convention):** tool version is tracked in `cuupdate/__init__.py`
(`__version__`), starting **1.9**, +0.1 per release to whole numbers. `cu.spec` names the frozen exe
`CUupdate_<version>.exe`; the GUI title shows `v<version>`.

**Files:** cuupdate/diffengine.py (`_proc_units`, `_unit_tags`, proc-graft + scorer-suppression in
classify), cuupdate/execute.py (proc-graft insertion, `_b_code_trailer_idx`, `proc-graft` executable
kind), cuupdate/__init__.py (NEW `__version__`), cu.spec (versioned exe name), cuupdate/cu_gui.py
(version in title), tests/test_diffengine.py (T36 → EXEC; verdict expectation updated),
tests/fixtures/Merged_T36.stripped.txt (regenerated correct gold).

---

**§8.23 — Procedure-scope anchor confinement + proc span-walk fix; v2.0**

Identified via **T17 (G/L Entry)**, but the change is to the **behaviour**, not to T17: a customer
code block whose anchor text is vendor boilerplate repeated across several procedures could be
carried into the wrong procedure. T17's `// Start AP001994` block (sets "Posted Description", reads
the `GenJnlLine` parameter) lives at the tail of `CopyFromGenJnlLine@4`; its `// Start PA036544`
after-anchor recurs at the tail of 5 procedures. The tightest-gap heuristic bracketed it into
`CopyPostingGroupsFromDtldCVBuf@94` (param `DtldCVLedgEntryBuf`, no `GenJnlLine` in scope) → output
that does not compile.

Fix (agreed): **resolve the block's enclosing procedure and confine anchoring to it.** A's enclosing
proc → B's by **`@id` first, name second** (vendors rename-without-renumber; a name change alone is
the *expected* case and must not gate). Anchor search restricted to that B-proc span; before-anchor
strictly inside, after-anchor may reach the following boundary (tail-of-proc blocks). Enclosing proc
**absent from B** → no valid anchor → whole object to DEV. Global-VAR / object-trigger blocks (no
enclosing proc) left unconfined — their existing object-scope paths are untouched.

Second, latent bug found en route: `_proc_units` token-depth span-walk underflowed on
`END ELSE BEGIN` and mis-terminated procedures early (T17 `CopyFromGenJnlLine@4` bounded to its first
inner `IF..THEN BEGIN`). Rewritten to C/AL's 4-space-indent `BEGIN`/`END;` invariant. Fixed in
**both** `scorer.py` and `diffengine.py` (was latent in diffengine — used for proc-graft
presence/absence by key — but fixed to stop the two copies diverging).

T17 frozen as a known-answer fixture (verdict + byte-exact EXEC). Harness change: header `Date` and
the CU-stamp doc-trigger line are PARAM-driven, not merge logic, so they are now **masked in `_norm`**
before exec comparison across **all** objects; the per-object date/text `PARAMS_OVERRIDE` entries that
only existed to chase each fixture's baked-in hand-merge date were removed.

**Version bumped 1.9 → 2.0** (standing rule: a change that alters merge output bumps the version, for
exe-name + GUI merge traceability). `CUupdate_2.0.exe`. USER_MANUAL.md updated (new §8.1.5a worked
example; exe references) and USER_MANUAL.docx regenerated via `build_manual.js`.

**Files:** cuupdate/scorer.py (proc-unit maps, `_a_enclosing`/`_b_match`, confinement in
`score_block`, indent-anchored `_proc_units`), cuupdate/diffengine.py (`_proc_units` span-walk),
cuupdate/__init__.py (2.0), tests/test_diffengine.py (T17 wired in; `_norm` param-masking; overrides
removed), tests/fixtures/{EX,CU,MyMerged}-T17.stripped.txt, docs/{ARCHITECTURE,CONTEXT}.md,
docs/USER_MANUAL.{md,docx}.

---

**§8.24 — END-bracketed code blocks at procedure tail; END-count replay; v2.1**

Identified via **C231 (Gen. Jnl.-Post)**, but the change is to the **behaviour**, not to C231: a customer
code block whose nearest distinctive neighbours on *both* sides are `END;` lines could not be
forward-anchored and false-gated to DEV. C231's customer customisation (`DC5.00`, Direct Credit NZ) is
two `// Start DC5.00` code blocks in `Code@1`. The second sits at the **tail of the procedure body**,
immediately before the `WITH`/proc `END;` lines. `END;` is non-distinctive boilerplate (excluded as an
anchor, BOILER), so the scorer's forward walk skipped past it, overshot the procedure onto the object-
trigger changelog (`PA-Number Date`), and procedure-scope confinement (§8.23) then stripped that out-of-
proc anchor → `apos` empty → coherent=False → DEV. The block has a legitimate home but the string-
matching scorer had no anchor to express it.

Fix (agreed, **Option A′**): when a confined block has no string-anchorable forward anchor, recover its
home **structurally, not by indentation** (operators' indent discipline varies; indentation is a
developer skill, not a guarantee). Count the `END`-class lines between the before-anchor and the block
in A, then **replay that exact count forward from each matched before-anchor in B** (`_walk_ends`); the
block anchors after the n-th `END;`. Balanced `END` nesting is guaranteed by compilation, so the count
transfers even when whitespace does not. Scoped to the confined, otherwise-anchorless case: it cannot
perturb any block that already anchors, nor any unconfined object-scope block (`a_unit is None`).

Two coupled execution fixes were needed to reproduce the hand-merge byte-exact:
- **`insert_after` (explicit insertion point).** The executor previously always inserted after
  `chosen[0]` (the before-anchor). An END-replay block sits *after* the `END;` it was bracketed against
  (`chosen[1]`), not after the before-anchor. The scorer now emits an explicit `insert_after` (= `chosen[1]`
  for END-replay blocks, else `chosen[0]`), plumbed scorer → diffengine → executor; the executor honours
  it and never re-derives placement from `chosen[0]` alone. Default preserves prior behaviour for every
  existing block.
- **Trailing-blank collision.** When a carried block ends in a blank AND B already has a blank at the
  insertion point, the two doubled. The executor now drops the carried trailing blank in that case (B's
  own blank already separates the block from the following vendor line). Fires only on a real collision;
  no existing fixture hits it.

C231 frozen as a known-answer fixture (verdict: two `code`/CARRY rows; byte-exact EXEC). Global VAR
`DCRegNoG` and Version List / doc-trigger carries are execution-layer (cf. T81). No language layer to
strip (object carries only the ENU base), so `.stripped` fixtures equal the source.

**Version bumped 2.0 → 2.1** (standing rule: a change that alters merge output bumps the version, for
exe-name + GUI merge traceability). `CUupdate_2.1.exe`. USER_MANUAL.md updated (Codeunit capability +
END-bracketed transplant note) and USER_MANUAL.docx regenerated via `build_manual.js`.

**Files:** cuupdate/scorer.py (`_a_index_of_anchor`/`_end_count_between`/`_walk_ends`, END-replay in
`score_block`, `insert_after`), cuupdate/diffengine.py (`insert_after` plumbed through code row +
`_scorer_blocks`), cuupdate/execute.py (honour `insert_after`; trailing-blank collision suppression),
cuupdate/__init__.py (2.1), tests/test_diffengine.py (C231 wired in: CUST_OVERRIDE, EXPECTED_VERDICTS,
EXEC_CASES, OBJ), tests/fixtures/{EX,CU,MyMerged}-C231.stripped.txt, docs/{ARCHITECTURE,CONTEXT}.md,
docs/USER_MANUAL.{md,docx}.

---

**§8.25 — Depth-aware insert correction (climb-out); C232 auto-merges; test-gate hardened; v2.2**

**One-liner:** *Generalised §8.24's END-count replay into the real invariant — a customer block belongs
at a specific brace-nesting DEPTH, and its insert point in B must sit at that depth. C232's first
`DC5.00` block was being dropped INSIDE the Posting-Report-ID branch because its before-anchor sits two
`END;`s deeper than the block; the depth correction now lands it after `END;END;` (outside the branch),
reproducing the hand merge byte-exact. New frozen fixture C232. Suite green.*

**Driver (Rich):** C232 (Codeunit 232, Gen. Jnl.-Post+Print, customer tag DC — Direct Credit NZ). Files
EX (A, customer) / CU (B, new vendor base) / MyMerged (gold). Tool output (Merged) placed the first
`// Start DC5.00 .. DCRegNoG := "Line No."; .. // Stop DC5.00` block one nesting level too deep: inside
`IF GenJnlTemplate."Posting Report ID" <> 0 THEN BEGIN .. END`, immediately after `REPORT.RUN(...GLReg)`.
Behaviourally wrong — `DCRegNoG` would then be assigned only when a posting report runs, not on every
post.

**Root cause.** Placement was decided by mapping the block's nearest distinctive neighbours into B and
inserting after the before-anchor (`chosen[0]+1`). The before-anchor `REPORT.RUN(...GLReg)` is depth 4
(inside `WITH..DO BEGIN` → `IF GLReg.GET..BEGIN` → `IF "Posting Report ID"..BEGIN`); the block in A is
depth 2 (inside `WITH`, outside the GLReg.GET block). The scorer had **no model of nesting depth** — it
knew the anchor line matched B at 100% but not that the block lived two `END;`s shallower. So it inserted
right after the anchor, dropping the block into the branch. §8.24's END-replay would have fixed it but
only fires in the `not apos and bpos` case (block has NO forward anchor); C232's block has a valid
forward anchor (`IF "Line No." = 0 THEN`), so that path never triggered.

**Fix (agreed, depth-as-invariant).** Express the rule as DEPTH, not END-counting (Rich: *"the END END
is not always going to be the reason… there should be some logical way to determine if the customer
code is within another block of code or not. This went from being outside a nest, to being inside"*).
- New structural-depth primitives in `scorer.py`: `_strip_opaque` (removes `{ }` block-comment interiors
  — multi-line state carried —, `//` comments, and `'...'` string literals so block keywords inside them
  are never counted), `_line_delta` (net `BEGIN`/`CASE`/`REPEAT` openers minus `END`/`UNTIL` closers on
  a line's visible text), `_depth_at` (running depth from the enclosing proc `BEGIN` to a target line —
  a count of unmatched openers, invariant to lines added/removed above), and `_depth_correct_forward`.
- In `score_block`, after `chosen`/`insert_after` are set (and only for confined, non-END-replay blocks):
  measure the block's OWN depth in A (`depth_A` at `b['start']`); if the naive B insert point sits
  DEEPER than `depth_A`, walk forward from it consuming closers until depth returns to `depth_A`, and
  insert there. Equal depth → no correction. The executor already honours `insert_after`, so no exec
  change was needed.

**The trap that made me run the full suite (caught + fixed before commit).** First implementation
measured `depth_A` from the block's *trailing sibling* (first live line after the block). That broke
**P347**: its `DC6.00` block is the TAIL arm of a `CASE ReportUsage2 OF`, so the first live line after it
(`SETRANGE("Make Code"...)`) is one level SHALLOWER — outside the CASE. Measuring there walked the insert
past the CASE's closing `END;` and displaced it. Fix: measure `depth_A` from the block's **own** line, not
its successor. P347 then has naive-B-depth == block-A-depth → no correction (correct); C232 has
naive 4 ≠ block 2 → corrected. Both right. (This is exactly the regression the unconditional-`PASS`
harness would have hidden — see below.)

**Test gate hardened (same release).** `test_diffengine.py` built a `fails` list but printed `PASS`
**unconditionally** and never exited non-zero — the P347 regression above showed `PASS` with a diff dump.
`test_scorer.py` had the same shape (`PASS=N FAIL=M` then exit 0 regardless). Both now exit 1 on any
failure. Verified the gate genuinely fails (rc=1) on a deliberately-broken C232 fixture and passes
(rc=0) restored. `test_census.py` already exited correctly.

**Verification.** C232 reproduces the hand merge byte-exact (modulo agreed `_norm` masking of header
`Date=` and the CU-stamp doc-trigger line). Full suite green: scorer 20/20, census 5/5, diffengine PASS
(now incl. C232 verdict — two `code`/CARRY rows — + byte-exact EXEC, and P347 still byte-exact). Second
`DC5.00` block (END-bracketed at proc tail) continues to anchor via §8.24 END-replay — untouched. No
language layer to strip (ENU base only), so `.stripped` fixtures equal source.

**Version bumped 2.1 → 2.2** (merge-output-altering change). `CUupdate_2.2.exe`.

**Files:** cuupdate/scorer.py (`_strip_opaque`/`_line_delta`/`_depth_at`/`_depth_correct_forward`,
depth-aware correction in `score_block`), cuupdate/__init__.py (2.2), tests/test_diffengine.py (C232
wired in: CUST_OVERRIDE, EXPECTED_VERDICTS, EXEC_CASES; fails-checked exit), tests/test_scorer.py
(non-zero exit on failure), tests/fixtures/{EX,CU,MyMerged}-C232.stripped.txt (NEW),
docs/{ARCHITECTURE,CONTEXT}.md.

---

**§8.26 — No-CU-change detection: skip the merge when the vendor changed nothing; v2.3**

**One-liner:** *A merge is not always required. When the vendor shipped NO change to an object in the
CU, A is already correct against the new CU — there is nothing to carry the customer's code INTO. New
Stage-2 short-circuit (`diffengine.no_cu_change`) detects this difference-first and skips the merge:
copy A verbatim to `NoCuChangesDetected/`, move sources out of the dev queue as `Unchanged_*`. Fires
C1201/C231/C232; T14/T36/T77/P14/P347 still merge. Suite green.*

**Driver (Rich):** confirmed C1201 (Codeunit 1201, customer tag WBL — the `Evaluate`→`Evaluate_WBL`
swap) and C231/C232 (Direct Credit, DC) are genuine no-vendor-change cases that should NOT produce a
merge. The manual process still TortoiseMerges them per object pair to confirm "nothing to do" — pure
noise. The tool should recognise the case and skip it.

**The detection (difference-first, mirror of pipeline step 3).** Step 3 ("normalised equality → take
B") fires when A == B (no customer side). No-CU-change is its mirror: it fires when the customer layer
is the ONLY difference (no vendor side) — and KEEPS A (not B; A holds the customisations). Diff A vs B
over the object body; fire iff EVERY differing line is customer-attributable. Scope = whole body minus
OBJECT-PROPERTIES header minus doc-trigger (both carry customer churn by construction; neither can
count as a vendor change). Whole-body, NOT CODE-only — see trap 1.

**Attribution contract (the customer-layer test).** A body line is customer-attributable when any of:
(1) live code carrying a `//<cust>` marker (trailing-tag live-line idiom); (2) any line in a customer
`Start..Stop` block, anywhere; (3) a comment line beginning `//<cust>` OR strictly contiguous to a
cat-1/2 line (comment-out and comment-out-with-replacement idioms — C1201's dead `//IF…Evaluate(` twin
is attributed by adjacency to the live `//WBL` line below it); (4) a VAR declaration present in A but
absent from B (structural customer ownership — C231/C232's `DCRegNoG@…`; the customer tags the code
BLOCK that uses the var, not the decl line). Marker forms are a documented, per-customer-extendable set,
NOT exhaustive. Safe error is always "don't fire": an unrecognised idiom leaves a residual → merged as
before → never skipped wrongly.

**Trap 1 — CODE-only scope (caught before commit).** First cut compared only inside `CODE{}`. That
fired wrongly on T14: a Table's customer work (the `Webbline Location` field, captions, OptionString)
lives in field nodes ABOVE `CODE{}`, so a CODE-only view saw "code identical" and would have skipped a
real merge. Fix: scope is the whole object body (minus header + doc-trigger). T14/T36 then correctly do
NOT fire.

**Trap 2 — vendor blocks read as customer (caught before commit).** `_nocu_attribute` first reused the
engine's `self.OPEN`/`self.STOP`, which are built from the COMBINED customer+vendor prefix set — so
`// Start PA036544` (vendor) matched as a customer block. On T14 this flagged 881/893 lines (an
unclosed vendor block runs the depth counter away) and fired no-CU-change on a real merge object. Fix:
build customer-ONLY `Start/Stop` regexes from `self.CUST` inside the attributor. A vendor Start/Stop
block is a vendor change and must surface, not be attributed away.

**Verification.** Fires: C1201/C231/C232 (zero unattributed). Does NOT fire: T14 (customer field add,
no inline marker), T36 (real vendor `// Start EU…` code blocks B has and A lacks — the dangerous case
that must never be skipped), T77, P14, P347 (vendor option/desc extensions). C1201 output is byte-
identical to the source A (verbatim, no stamp — confirmed by `cmp`). End-to-end batch verified: A/ and
B/ emptied to `AnoCuChange/`+`BnoCuChange/` as `Unchanged_*`, copy in `NoCuChangesDetected/`, report
section + GUI count present. Existing fixtures all still reproduce byte-exact (the method is additive —
it does NOT touch `classify()` or `execute()`); C231/C232 merge path unchanged if ever reached. Full
suite green: diffengine PASS (incl. 7 new no-CU-change assertions), scorer 20/20, census 5/5.

**Version bumped 2.2 → 2.3.** Not strictly merge-output-altering (additive short-circuit; no existing
merge changes), but it changes externally-visible behaviour (new outcome, new folders, objects now
skipped rather than merged-then-discarded) and the bump keeps local build differentiation clear in the
GUI title / exe name. `CUupdate_2.3.exe`.

**Files:** cuupdate/diffengine.py (`no_cu_change` + `_nocu_body`/`_nocu_attribute`, customer-only
attribution; additive), cuupdate/run_batch.py (pre-merge check, `nocu` bucket, `NoCuChangesDetected/`
copy, `_moved_unchanged` → `Unchanged_*`, report section, results dict), cuupdate/run_one.py
(short-circuit print), cuupdate/cu_gui.py (summary count), cuupdate/__init__.py (2.3),
tests/test_diffengine.py (no-CU-change known-answer layer: 3 fire + 4 no-fire),
tests/fixtures/{EX,CU}-C1201.stripped.txt (NEW), docs/{ARCHITECTURE,CONTEXT,USER_MANUAL}.md.
