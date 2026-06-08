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

### 8.5 KNOWN ROUGH EDGES
1. **scorer↔field attribution** in `diffengine._scorer_verdicts` is keyed by TAG, so every block of
   a tag attaches to every field bearing that tag (verdict still correct — any DEV → field DEV — but
   the detail is noisy/misattributed). FIX: key scorer blocks by LINE RANGE; match each field's code
   blocks to scorer blocks within that field's line span. STILL OPEN. (§8.7 added a separate
   CODE-section code-row path that IS keyed by line/span; the field-TRIGGER attribution issue remains.)
2. **RDLC report layout** (R5025607 "Add header and footer") not surfaced — the change lives in the
   base64 RDLC blob which isn't parsed into nodes. Needs: detect a customer doc entry whose desc
   matches RDLC/layout keywords → DEV with detail (the differ can't parse binary layout). STILL OPEN.
3. ~~No known-answer harness for diffengine~~ **RESOLVED (§8.7)** — `test_diffengine.py` built (verdict
   + execution layers, both passing). T38 bare `WBL` SIGNED OFF: stale VL token (declared in Version
   List, zero body occurrences; real customisation is `WBL009`, manifests separately) → IGNORE: emit
   no row, no DEV. Earlier "→DEV" was over-conservative noise.
4. Census prefixes/languages still hardcoded (now in `run_batch.py`/`run_one.py` defaults, overridable
   via `--cust/--vend/--langs`). Stage 0 census feeds these in production. STILL OPEN.

### 8.6 Repo state / files (current as of §8.7 session)
- `scorer.py` + `test_scorer.py` — anchor scorer, 20/20. COMMITTED+PUSHED. §8.7 added a `chosen`
  field to `score_block`'s return (the validated before/after anchor positions) — additive, no
  verdict change, harness still 20/20.
- `diffengine.py` — difference-driven engine. §8.7 added CODE-section visibility (see §8.7) +
  `_scorer_blocks` helper. PUSHED (commit b133b01).
- `execute.py` — NEW (§8.7). Stage 3 narrow-path executor. PUSHED (b133b01).
- `test_diffengine.py` — NEW (§8.7). Known-answer harness, PASSES. PUSHED (b133b01).
- `strip_lang_fixture.py` — NEW (§8.7). FIXTURE-PREP ONLY (not production language handling — that
  stays the native cmdlet). PUSHED (b133b01).
- `fixtures/` — NEW (§8.7). Frozen language-normalised known-answer set (T14, T36 stripped A/B/Merged,
  plus raw Merged uploads). PUSHED (b133b01).
- `run_batch.py` + `run_one.py` — NEW (§8.7). Job/single-object drivers. PUSHED (commit 8c145d1).
- `README_run.md` — NEW (§8.7). Quick-start for the runners. (Presented to user; commit if not yet in.)
- `structdiff.py` + `test_structdiff.py` — SUPERSEDED tag-driven differ; still in repo, still passes
  (2/2). Safe to delete now that diffengine has its harness; left as reference.
- Test objects `Cust_*.txt` / `20206Q1_*.txt` — CONFIRMED OK to remain in repo (no customer-sensitive
  info; §5 confidentiality flag CLEARED by user).
- PAT note: user is aware; do not re-raise.
- Prototype is Python; production target is PowerShell (must call dev-shell cmdlets).

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
