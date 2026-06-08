# CAL Upgrade Tool — Architecture & Design Decisions

incadea / BC-NAV v14 cumulative-update integration. Reusable across customers and CU jumps.
Reference scenario: customer on idealer CU202301 → idealer CU2026Q1, with local customisations
and localisations to preserve.

This document is the authoritative spec. It records not just *what* the tool does but *why*,
because each rule was derived from real object evidence (T14, C80, T36, R790, P21, T38, T39,
T5025400, P5025649, R5025607) and the reasoning matters for anyone extending it.

---

## 1. Core terminology

- **A** = customer instance: idealer + customer customisations/localisations, at the *from* CU.
- **B** = idealer 2026Q1 ("idealer" = incadea standard): the vendor target, the *to* CU.
- We do **not** have clean vanilla idealer 202301. The tool never relies on a reconstructed
  baseline — customer changes are identified from **tags** (code objects) or **structural diff**
  (page/report objects), using A and B only.
- Output = a **merged** object set: idealer 2026Q1 with customer customisations carried forward.

## 2. Tag model (incadea convention)

- Grammar: `// Start <PREFIX><id>` … `// Stop <PREFIX><id>`. id may contain digits, dots and
  hyphens (e.g. `PA035804.26149`, `WBL-006`, `AP-2362`). Match **registry-anchored, longest
  prefix first** (so `PPA` is never read as `PA`).
- **Layers**: every prefix is vendor or customer.
  - vendor/keep: idealer's own (observed: PA, EU, INC, PPA, IMM, PS).
  - customer/carry: the customer's (observed: AP, WBL).
- Nothing is hardcoded. Prefixes + layers come from the **tag census** (§4).

## 3. Object-type routing (THE key architectural split)

Customisation manifests differently by object type, so routing is type-aware:

### Code-bearing objects — Codeunit, Table
C/AL code; customisations are tagged inline. Tags are reliable here (evidence: T36, C80, T38,
T39 all tag code cleanly). The tag-driven transplant model applies.

**Tables are hybrid** — code (triggers, tagged) AND structure (the FIELDS section, where a customer
field can be added with NO code block, only a doc-trigger entry). So tables ALSO use the
documentation-trigger + structural-diff path (§7) for field-level adds. Evidence: T36 fields
50090/50091/50096/50097 added untagged, recorded as `AP001651 ... Added Consignment fields 50090,
50091, 50096, 50097`; T38 field 70000 "RUID". A customer field added to a vendor table must be
**grafted into B's FIELDS section**, not lost.

> **Scope clarification:** "exclude 50000–99999" means exclude customer-range *objects*. Customer
> fields *inside an in-scope vendor object* (e.g. field 50090 in Table 36) are part of that object's
> customisation and MUST be carried forward, not dropped when taking B.

### Structure-bearing objects — Page, Report
Mostly control trees / dataitems / layout, not procedural code. Customisations (added fields,
caption localisations, layout) are **frequently untagged** because there is no natural place for
an inline tag (evidence: P21 — added ENZ caption localisations + minor code, zero body tags).
Absence of tags here is NOT evidence of "unchanged". These use a structural diff, not tag logic.

## 4. Stage 0 — Tag census (agentic, per customer)

Scan all in-scope objects; for each distinct alpha-prefix gather evidence and infer layer:
- present in **both A and B** → vendor (it shipped in idealer). [Validated: PA/EU/INC/PPA/IMM/PS]
- present in **A only** → customer. [Validated: AP/WBL]
- corroborating signal: customer **Version List** tokens (A header) promote confidence toward
  customer. (Version-list absence is NOT evidence of vendor — vendor prefixes are never listed.)

**Language-code discovery (same mechanism, same run).** The census ALSO scans caption/TextConst
language codes and infers them by the identical A-vs-B presence test — because the localisation
language layer is per-customer and must never be hardcoded (one customer ENZ, another DEU/FRA/NLD,
possibly several at once):
- code present in **both A and B** → **base/development language** (idealer ships it). Do NOT
  assume this is ENU — infer it. The inferred base becomes `-DevelopmentLanguageId` for the
  language cmdlets (§7d).
- code present in **A only** → **customer localisation layer** to extract/reattach. There may be
  more than one; collect all (the language cmdlets take a `LanguageId` array).
  [Validated on batch: ENU in-both = base; ENZ A-only = customer layer; C80 has no captions = none.]

Autonomy: **auto-classify high-confidence** prefixes/codes (signals agree), **prompt the dev only
on ambiguous** ones (prefix A-only but not in any version list; in a version list yet in both;
B-only; very low occurrence; a language code in only SOME B objects). On the validated data this
yields zero prompts.

The census emits a confirmed **registry** containing both the tag-prefix layers AND a `languages`
block (inferred base language + customer layer code[s]). Everything downstream reads from it;
nothing about specific prefixes or language codes is hardcoded.

Grammar is hardcoded incadea-style for now, with a guard: if the census finds **no tags at all**
across the object set, stop and report "grammar likely doesn't match" rather than treating the
customer as un-customised.

## 5. Pipeline (per object), cheapest filters first

1. **Killme** — object Name contains `kill` (case-insensitive; e.g. `Killme P5005350`) →
   **RETIRE** (never written to merged set; logged).
2. **Modified=No** (A header) → take **B** (customer never touched it). Trusted per decision.
3. **Normalised equality** — strip header fields `Date/Time/Modified/Version List`, trailing
   whitespace, line-endings, **and customer-added language layers (§7d)**; if A == B → take **B**.
4. **Type-aware difference handling** (A ≠ B):

   **Code objects (Codeunit/Table):**
   - For each **customer-tagged block** (AP/WBL…): classify + route (§6).
   - **Untagged A≠B region** → take **B**. *(Scoped to code objects only: tag discipline is
     trustworthy for code, so an untagged code diff is most likely idealer's own change. This is
     the one remaining silent-overwrite path — accepted deliberately for code objects.)*

   **Page/Report objects:**
   - Structural diff of the control/dataitem tree (§7). Never infer "unchanged" from "no tags".
   - Simple structural **addition** with surviving insertion point → auto-graft onto B.
   - Anything else (modified control, property/caption change, layout/RDLC) → **DEV**.

## 6. Code-object block routing (tag-driven transplant)

**Documentation-trigger enrichment (all object types):** the changelog also carries customer code
entries (e.g. T39 `WBL-009 21.08.23 RL "Purchaser code" mandatory on lines.`). These map by tag to
the body blocks and give the dev plain-English intent per block in the worklist. For code objects
the body tag remains the routing gate (it marks exact line ranges); the doc entry enriches, it does
not gate.

Per customer-tagged block in A:

- **Content class** (three-way — validated on real blocks):
  - `PURE_ADD` — only added lines inside the block. → eligible for auto-transplant.
  - `VANILLA_MOD` — commented-out original idealer line PLUS replacement lines (customer overrode
    vanilla). Evidence: C80 AP2308/WBL10. → auto-transplant only on high score + positional
    original-survival; else DEV. (In practice all real VANILLA_MOD blocks scored to DEV.)
  - `VANILLA_SUPPRESS` — commented-out vendor line(s) with NO replacement (customer disabled vendor
    logic). Evidence: R790 AP002098@696, T39 WBL-006@3523/@3540 ("Remove short VIN check"). →
    **always DEV** — re-suppressing vendor logic on the upgraded B is a semantic human decision.
- **Anchor survival** — does the block's insertion point still exist, *positionally coherent*, in
  B? Anchors = nearest distinctive context, **preferring the enclosing vendor tag** (globally
  unique), falling back to a distinctive code line; boilerplate (`BEGIN`/`END;`/braces/blank) is
  never an anchor. Validity requires the before- and after-anchors to be found in B *and* the
  region between them to match — existence alone is insufficient (see §9 known bugs).
- **Confidence score** (0–1) from anchor type, match quality (exact > fuzzy), positional
  coherence, both-sides-found.
- **Verdict**:
  - `PURE_ADD` & score ≥ `pureAddThreshold` → **AUTO_TRANSPLANT** (graft block onto B at anchor).
  - `VANILLA_MOD` & score ≥ `vanillaModThreshold` (higher) **and** the overridden original line
    still survives *at the anchored position* in B → **AUTO_TRANSPLANT**.
  - else → **DEV**.
- Thresholds: conservative defaults; **every verdict logged with full score breakdown + matched
  anchors** so thresholds can be tuned from real dev outcomes later.

## 7. Documentation-trigger + structural-diff path (Pages, Reports, AND table field-adds)

Applies to Pages, Reports, and the FIELDS section of Tables — anywhere customisation is structural
(added field/control/part) rather than tagged code. The **documentation trigger** is the customer's
change manifest and is the primary signal here.

### 7a. The documentation trigger
A changelog comment block at the **tail of the CODE section** (between the final `}` and `END.`),
one entry per line:  `<TAG>  <DD.MM.YY> <initials> <free-text description>`.
Vendor entries (EU/PA…) first, customer entries (WBL/AP…) appended. Same format whether located
at end-of-CODE (P21) or as a named block (T36/T39). Examples (P21):
  `WBL10    07.08.23 RL Add field 'Purchase Order No. Mandatory'.`
  `AP-2362  09.04.26 LU Created and Added the FactBox "...FactBox2/3"; Divided fields from ...`

Parse it; split entries vendor-vs-customer by the registry tag layer.
- **Customer entries** = a human-readable list of what the customer changed, each with tag, date,
  author, intent. This is the page/report analogue of code body tags.
- **A-vs-B doc diff** (idealer's added entries) = the vendor-change narrative — incadea's own words
  for what changed between the customer's CU and 2026Q1. Surface in the dev worklist.

### 7b. Routing (cross-reference doc entry × structural diff)
Parse A and B into control/dataitem/part nodes; cross-reference each customer doc entry against the
structural diff:
- **Clean addition** — doc says "add[ed] <X>" AND structural diff confirms node <X> exists in A,
  not in B, with unchanged sibling context → **AUTO_GRAFT** onto B. (Validated: P21 WBL10
  "Purchase Order No. Mandatory" — present A1162, absent B, doc-confirmed.)
- **Restructure / modification / ambiguous** — description is not a clean add (e.g. P21 AP-2362
  "Divided the fields from FactBox into FactBox2/3"), or diff shows changes beyond additions →
  **DEV**, with the doc entry shown as the change description.
- **Structural diff present but NO doc entry explaining it** → **DEV** (untagged & undocumented;
  do NOT silently take B for pages/reports — this is where pervasive untagged property/caption
  changes hide, e.g. ENZ localisations).
- **No doc entry AND no structural diff** → genuinely unchanged → take **B**.

### 7c. Limits
The description is free text and discipline-dependent. It reliably distinguishes "add" from
"restructure" enough to gate auto-graft vs dev, but is never trusted to be complete: the structural
diff is the confirming check. Doc entry + diff agreeing = high confidence; disagreement = dev.

## 7d. Language / localisation layer (extract → compare → reattach)

The customer adds a localisation language layer to captions/text. **The specific codes are
discovered per customer by the census (§4), never hardcoded** — `<CUSTOMER_LANG>` and
`<BASE_LANG>` below are placeholders for the inferred values (this customer: ENZ customer layer,
ENU base; another customer could be DEU/FRA/NLD, possibly several). This layer pollutes comparison —
much of P21's apparent "240 changed lines" was just customer-layer captions, not behavioural change.

Handling — **native NAV cmdlets** (same `Microsoft.Dynamics.Nav.Model.Tools` module as
Merge/Import/Compile), NOT hand-rolled regex on caption lines. **Goal is compile-clean reattach,
NOT translation correctness** — local developers own translation accuracy and fix it as normal work.

1. **Capture (stash for reattach):** `Export-NAVApplicationObjectLanguage -Source A -LanguageId
   <CUSTOMER_LANG>` → a language file holding the customer's translations (LanguageId accepts an
   array if there are multiple customer-layer codes).
2. **Strip before compare:** `Remove-NAVApplicationObjectLanguage -Source A -LanguageId
   <CUSTOMER_LANG> -DevelopmentLanguageId <BASE_LANG>` → language-normalised A (base kept) for the
   A-vs-B diff, so the localisation layer doesn't pollute the comparison. Normalise B the same way
   for symmetry.
3. **Reattach after merge:** `Import-NAVApplicationObjectLanguage -Source <merged> -LanguagePath
   <lang file>` → customer captions re-applied onto the merged-from-B object (matched by caption
   key, so placement survives the merge moving code).

**The only obligation is that the object COMPILES after reattach.** Stale translations, new
idealer captions lacking ENZ, and skipped reattaches on renumbered keys are all acceptable — they
compile, and the local developer corrects them later. The tool does NOT produce translation-review
or drift reports. The only language-related thing the tool flags is a hard failure: if Import or the
subsequent compile errors, that surfaces as a normal compile error (§ pipeline), not a translation
concern.

## 8. Integrity (layer-aware)

- Defect (unbalanced/malformed tag) in a **customer** block → **STOP** (can't safely strip/transplant).
- Defect in a **vendor** block → **WARN + continue** (idealer ships its own defects: real examples
  `// Srop PA035804`, `// Stat EU...`, dangling opens — present identically in A and B, so they are
  idealer's, not the customer's). We don't modify vendor blocks, so we don't block on them.

## 9. Anchor scorer status (FIXED & validated; Python prototype)

The two "existence vs position" false-positive bugs are FIXED and verified:
1. **Vendor-tag anchor** now requires **positional coherence** — before- and after-anchors found in
   B with the after FOLLOWING the before within a bounded window (block span + slack), not mere key
   existence. Plus **structural-boundary-aware walking**: the anchor search stops at procedure /
   trigger / field-definition / section boundaries, so it cannot wander out of a customer-authored
   procedure onto an unrelated surviving region. (Fixes T36 AP001651 — was false TRANSPLANT, now
   correctly DEV.)
2. **Overridden-original survival** for VANILLA_MOD now validated **only within the anchored region**
   (pb..pa), not globally. (Fixes C80's coincidental `TESTFIELD` matches.)

Validation: **22 blocks across 7 objects (T14/T36/C80/R790/T38/T39/T5025400), 19 explicit
known-answer cases all PASS**, covering pure-add, vanilla-mod, vanilla-suppress, nested, field-
trigger-anchored, and customer-procedure patterns. Safety properties hold: **no false TRANSPLANT**
(the only dangerous direction); false DEVs are correct-conservative (e.g. T38 WBL-009@1441, first
statement in field 43's OnValidate — correctly needs confirmation of trigger survival in B).

Remaining caveats:
- Sample is 7 objects / 22 blocks — covers the patterns well but thresholds (PURE 0.75 / VMOD 0.90)
  are not volume-tuned. Every verdict is logged with score breakdown for calibration on real runs.
- The VANILLA_MOD auto-transplant path is implemented but **unexercised in the TRANSPLANT direction**
  by real data (all real VANILLA_MOD blocks scored to DEV). Safe, but untested live.
- Prototype is Python (`/scorer.py`, `/test_scorer.py`); PowerShell port pending.

## 10. Scope

- Exclude object IDs **50000–99999** (customer licence range) from processing. Note: idealer's own
  5025xxx objects are IN scope (different range).
- Object types in scope: Table, Page, Report, Codeunit, plus others as encountered.

## 11. Output / audit (company-wide use)

- **Running ledger**: every object — verdict (RETIRE / take-B / transplant / dev / auto-graft),
  reason, evidence. Per-block detail for code objects.
- **Dev worklist**: the DEV-routed objects/blocks with side-by-side A | B (and matched anchors /
  structural diff) so resolution is fast and auditable.
- A separate **merge-assist tool** (future) ingests dev-resolved objects into the merged set.

## 12. Implementation status

- Settled & validated on real data: type-aware routing (incl. **tables as hybrid** — FIELDS-section
  field-adds via doc-trigger, e.g. T36 50090-50097); tag census + layer inference; grammar
  (incl. hyphen ids, longest-prefix anchoring); content classification (pure-add vs vanilla-mod);
  pipeline ordering; layer-aware integrity; Killme retire; documentation-trigger parsing as the
  primary page/report/table-field signal + worklist enrichment; **language-layer extract/reattach
  via native cmdlets (compile-only; translation correctness is the local dev's job, no drift
  reporting)**.
- Prototype, not production: anchor/confidence scorer (§9 bugs open).
- Not started: page/report structural differ; PowerShell port; merge-assist tool.
- Environment: instance-based (read A & B tiers; tool creates merged tier, non-prod gated).
  PowerShell module wrapping the NAV v14 dev-shell (Export/Import/Compile/Merge-NAVApplicationObject).
