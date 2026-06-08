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

## 6. Open work

1. **Structural differ (§7b)** — page/report/table-field path. Parse A & B control/dataitem/field
   trees, cross-reference doc-trigger entries, classify clean-add (auto-graft) vs restructure/modify
   (DEV). **Greenfield — not started.** Test cases ready: P21 WBL10 field-add (graft-eligible),
   P21 AP-2362 FactBox restructure (DEV), T36 fields 50090-50097.
2. **Scorer threshold tuning** — current PURE 0.75 / VMOD 0.90 conservative defaults, validated on
   22 blocks; tune from real-run logs. VANILLA_MOD auto-transplant path is implemented but
   **unexercised in the TRANSPLANT direction** (all real VANILLA_MOD scored to DEV).
3. **Language extract/reattach** — wire the three native cmdlets into the pipeline (compile-only).
4. **PowerShell port** — port scorer + differ; build the instance-based wrapper around the v14
   dev-shell (`Export/Import/Compile/Merge-NAVApplicationObject` + the language cmdlets). Provision
   the merged tier (non-prod gated). Earlier PS module scaffold exists (CalUpgrade.psd1/.psm1 +
   Config) but predates the type-aware/doc-trigger design and needs revising to match this spec.
5. **Merge-assist tool** (separate) — ingests dev-resolved objects into the merged set.
6. **Two-phase orchestration & reporting** — auto → pause at side-by-side review (download
   decisions.json) → resume; running ledger of every object's verdict + reason.

## 7. Working principles (consistent throughout)

- Discover what varies (tags, languages); infer from evidence; auto-proceed when confident; prompt
  only on genuine ambiguity.
- Do the confident mechanical work; route every uncertain/semantic call to a human.
- Never silently lose customer code (the one scoped exception — untagged CODE diffs → take B — is
  explicit and on record).
- Prefer native NAV cmdlets over re-implementing (language layers, merge, compile).
- Validate against real objects with known answers before trusting any heuristic.
