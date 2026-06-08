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

## 6. Open work (UPDATED — see §8 for the latest session's detail)

1. **Structural differ** — DONE as the *difference-driven engine* (`diffengine.py`). See §8.
   Remaining polish: scorer↔field line-range join, RDLC report handling, known-answer harness.
2. **Scorer threshold tuning** — current PURE 0.75 / VMOD 0.90 conservative defaults, validated on
   22+ blocks; tune from real-run logs. VANILLA_MOD auto-transplant path implemented but
   **unexercised in the TRANSPLANT direction** (all real VANILLA_MOD scored to DEV).
3. **Language extract/reattach** — wire the native cmdlets into the pipeline (compile-only).
   Mechanics fully resolved this session — see §8.4.
4. **PowerShell port** — port scorer + engine; build the instance-based wrapper around the v14
   dev-shell. Earlier PS scaffold predates this design.
5. **Merge-assist tool** (separate) — ingests dev-resolved objects into the merged set.
6. **Two-phase orchestration & reporting** — auto → pause at side-by-side review → resume; ledger.

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

### 8.5 KNOWN ROUGH EDGES (next session's first tasks)
1. **scorer↔field attribution** in `diffengine._scorer_verdicts` is keyed by TAG, so every block of
   a tag attaches to every field bearing that tag (verdict still correct — any DEV → field DEV — but
   the detail is noisy/misattributed). FIX: key scorer blocks by LINE RANGE; match each field's code
   blocks to scorer blocks within that field's line span.
2. **RDLC report layout** (R5025607 "Add header and footer") not surfaced — the change lives in the
   base64 RDLC blob which isn't parsed into nodes. Needs: detect a customer doc entry whose desc
   matches RDLC/layout keywords → DEV with detail (the differ can't parse binary layout).
3. **No known-answer harness** for `diffengine.py` yet (scorer has `test_scorer.py`, 20/20; the old
   `test_structdiff.py` tests the SUPERSEDED tag-driven differ). Build `test_diffengine.py` freezing
   the §8.3 validated verdicts. Get user sign-off on the verdict list first (was mid-review:
   T38 bare `WBL` "declared-in-VL-but-located-nowhere"→DEV still needs user confirmation of whether
   it's real customisation or a stale VL token).
4. Census prefixes/languages are hardcoded in `diffengine.py __main__` (CUST/VEND/LANGS) — these
   come from Stage 0 census in production; fine for prototype.

### 8.6 Repo state / files
- `scorer.py` + `test_scorer.py` — anchor scorer, 20/20. COMMITTED+PUSHED (commit 7ade8fb).
- `diffengine.py` — difference-driven engine, verdicts correct. COMMITTED (f70773a).
- `structdiff.py` + `test_structdiff.py` — SUPERSEDED tag-driven differ; kept in history (4443612).
  Can be deleted once `diffengine.py` has its harness; left for now as reference.
- Test objects `Cust_*.txt` / `20206Q1_*.txt` committed (NOTE §5 confidentiality flag — confirm
  these are OK to remain in the repo).
- PAT used this session should be revoked/regenerated (was pasted in chat).
- Prototype is Python; production target is PowerShell (must call dev-shell cmdlets).
