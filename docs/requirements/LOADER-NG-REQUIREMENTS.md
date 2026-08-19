# Castletronics Product Loader — Next Generation
## Requirements Specification

| | |
|---|---|
| **Document ID** | `CT-LOADER-NG-SRS-001` |
| **Status** | Draft for design — **not baselined** |
| **Date** | 2026-08-17 |
| **Author** | Design AI (Castletronics) |
| **Audience** | The AI (or engineer) who will **design and build** the next-generation loader |
| **Supersedes** | Nothing. The current loader stays in service until this one is accepted. |
| **Standard** | ISO/IEC/IEEE 29148 structure · EARS phrasing · INCOSE singularity |

---

## 0. How to read this document

Every requirement is numbered, singular and verifiable, and carries:
**ID · statement · WHY (with provenance) · VERIFY · priority.**

**`WHY` is not decoration.** Nearly every requirement exists because something failed in production
or in a spec, and the failure is cited to a file so you can read the original rather than trust this
summary. **If you are tempted to drop a requirement, read its WHY first.**

**Priority:** `M` mandatory (v1) · `S` should · `C` could (v2) · `W` won't (recorded so it is not re-proposed).

> ### ⛔ The most important section in this document is §7 — Gates and Controls.
> **Every catastrophic defect in this program's history was silent** — a check that could only report
> success. If you implement the data model beautifully and skip §7, you will rebuild the same class of
> failure with better structure.

---

## 1. Purpose and scope

### 1.1 Purpose
Define requirements for a **vendor-agnostic product loader** that ingests supplier data and writes it
to BigCommerce such that the Castletronics storefront renders correct, filterable, truthful product
pages — **for any product line, not only Lindström**.

### 1.2 Why replace the current loader
It works and is in production (292 Lindström SKUs live, v1.21.0). But it is **Lindström-shaped**:
chapter names, facet keys, derivation rules, family logic and vendor column names are woven into the
pipeline rather than declared as configuration. Adding a second vendor line today means **editing the
pipeline, not describing the line**.

### 1.3 Scope
**IN** — ingestion, normalization, derivation, facet/spec packing, the BigCommerce write (products,
custom fields, images, categories, relations, template routing), verification, rollback.

**OUT** — storefront rendering (Impl owns the theme), content authoring, pricing decisions, category
tree design, and any judgement about what is *true* of a product (see `FR-TRUTH-004`).

### 1.4 Definitions
| Term | Meaning |
|---|---|
| **Line** | A vendor product line loaded as a unit. **The unit of configuration.** |
| **Chapter** | A grouping within a line that gets its own filter rail (Cutters, Tweezers…). Maps to a BC L2 category. |
| **Facet** | A filterable/displayable per-SKU attribute, packed into `filter_metadata`. |
| **Spec** | A display-only per-SKU attribute, packed into `spec_display`. |
| **Family** | The SKU set a product's "In this series" table lists. |
| **Packed field** | A BC custom field carrying `key=value;key=value`. |
| **Control** | A check that proves a measuring instrument is able to report failure. |

---

## 2. Context — the contracts the storefront imposes

These are **contracts, not preferences**. The theme fails closed against all of them.

| The theme reads | From | Contract |
|---|---|---|
| Filter rail + card `data-*` attributes | `filter_metadata` | `key=value;…`, **ASCII slugs** |
| PDP spec table · card chips · series compare columns · BC compare page | `spec_display` | `key=value;…`, **finished display strings** |
| Document links (datasheet, warranty) | `spec_docs` | packed; uses `= ; \|` internally |
| ESD badge | `esd_safe` | folding into `filter_metadata.esd` in Phase 2 |
| **Which PDP template renders** | `ct_page_type` | value `tool`; **absent ⇒ equipment** (fails closed) |
| "In this series" table | BC native `related_products` | array of product ids |

**Field-count budget: 5 custom fields today, 4 after the `esd_safe` fold**
(`DESIGN-TOOL-LOADER-SPEC §5`; `RULING-LEDGER CT-6`).

---

## 3. Generalization — the core of this rewrite

> Everything else in this document is a better version of something that already works. **This section
> is the actual reason to rebuild.**

**FR-GEN-001 · M** — The loader **shall** treat a product line as **declarative configuration**, such
that adding a new vendor line requires **no change to pipeline code**.
**WHY:** Tony is adding further lines. Each must not be a fork of the pipeline.
**VERIFY:** add a synthetic second line by config alone; it loads end-to-end with zero diffs to pipeline modules.

**FR-GEN-002 · M** — A line configuration **shall** declare at minimum: source files and sheets; a
column→canonical-field map; the chapter set; per-chapter facet definitions; per-chapter spec
definitions; family rules; the `ct_page_type` value; and the BC category mapping.
**VERIFY:** schema-validate the config; one missing required section is rejected **before any file read**.

**FR-GEN-003 · M** — The loader **shall** separate **canonical fields** (vendor-neutral, e.g.
`length_mm`) from **vendor columns** (e.g. `Total length`), and all derivation **shall** operate on
canonical fields only.
**WHY:** derivation coupled to a vendor's column names cannot be reused. **This is the single change
that makes line #2 cheap.**
**VERIFY:** derivation unit tests run against canonical fixtures with no vendor file present.

**FR-GEN-004 · M** — Where a line does not supply an attribute, the loader **shall** omit it and
**shall not** substitute a default, placeholder or empty value.
**WHY:** `DATA-MODEL §4.3` — *"A key with no value is NOT PACKED AT ALL — never `key=`."* An empty value
renders a blank spec row that reads as **missing data** rather than not-applicable.
**VERIFY:** null-attribute fixture ⇒ key absent from the packed string.

**FR-GEN-005 · M** — The loader **shall not** infer a line's structure from its data. Chapters, facets
and families are **declared**.
**WHY:** inference drifts silently when a vendor reorganises a sheet. The `head` key already needs a
**declared** per-chapter source (`head_type` ELSE `group`) because the two taxonomies agree on only
**5 of 155 rows** (`DATA-MODEL §3.2`).
**VERIFY:** a vendor column rename produces a loud config-validation failure, not a silent re-derivation.

**FR-GEN-006 · S** — Multiple lines **shall** coexist in one store without interference; facet
vocabularies, families and exclusions are **line-scoped**.
**VERIFY:** load two lines; no line-A product appears in any line-B family or facet count.

---

## 4. Ingestion and normalization

**FR-ING-001 · M** — The loader **shall** merge source columns from **multiple files** into one
canonical row per SKU.
**WHY:** `LOADER-SPEC §1` — three required vendor columns come from **two different files**.
**VERIFY:** merged row count = distinct SKU count; per-field provenance recorded (`FR-OPS-003`).

**FR-ING-002 · M** — Where a canonical field declares **alias columns**, the loader **shall** read the
primary and **shall** fall back to an alias **only when the primary is empty**.
**WHY:** `RULING-LEDGER AL-1/AL-2`. **138 lengths and 112 tip widths come from alias columns** — those
products ship blank without the chain.
**VERIFY:** primary populated ⇒ alias ignored; primary empty ⇒ alias used.

**FR-ING-003 · M** — Where primary and alias are **both populated and disagree**, the loader **shall**
load **neither** and **shall** report the conflict.
**WHY:** `RULING-LEDGER AL-3`. A silent pick between disagreeing sources is a guess presented as data.
**VERIFY:** synthetic conflict fixture ⇒ value blank **and** conflict logged.
⚠ **This has never fired on real data** (0 of 322 rows populate both) — the test is the only proof it works.

**FR-ING-004 · M** — The loader **shall** parse a unit from **inside a value** where the vendor embeds
it, and **shall not** assume the unit from the column header.
**WHY:** `RULING-LEDGER AL-4`; `LOADER-SPEC §5` — `bh`/`bw` arrive as `'0.39 in'` **inside the cell**.
Assuming the header unit manufactures a wrong number.
**VERIFY:** one column yields `130 mm` and `4.72 in` correctly from two rows.

**FR-ING-005 · M** — The loader **shall not** normalize vendor column **headers**.
**WHY:** `LOADER-SPEC §1.2a` — **three legitimate column names contain commas.** Header normalization
silently split them.
**VERIFY:** a header containing `,` resolves to the correct canonical field.

**FR-ING-006 · M** — The loader **shall** inspect encoding-sensitive values **by codepoint**, never by
rendered appearance.
**WHY:** `DATA-MODEL §3.2a` — a terminal that could not print non-ASCII substituted `U+FFFD`, and a
repair was nearly specced **for clean data**. The same check found a real defect: `45º` uses `U+00BA`
(masculine ordinal) where `U+00B0` (degree) is meant.
**VERIFY:** codepoint sweep; console appearance is **not** acceptable evidence.

**FR-ING-007 · M** — The loader **shall** maintain a per-line **exclusion list** and skip those SKUs on
every run.
**WHY:** `RUNBOOK §8` — without it, **deleting a product in BC does not stick**: the next run finds no
SKU match and recreates it.
**VERIFY:** delete a product, exclude it, re-run ⇒ not recreated.

---

## 5. Derivation, vocabulary and packing

**FR-DRV-001 · M** — The loader **shall** derive each facet value by the **declared** rule for that key
in that chapter, and emit **ASCII slugs**, never display labels.
**WHY:** `DATA-MODEL §3.2` — labels live in the theme's rail config so wording can change without a reload.
**VERIFY:** every emitted value matches `^[a-z0-9][a-z0-9-]*$`.

**FR-DRV-002 · M** — The loader **shall** validate every packed facet value against a **declared
controlled vocabulary** and **shall HALT** on any value outside it.
**WHY:** `RUNBOOK G2` — the rail compares **literal strings**. A mismatched value **matches nothing and
renders "no products". It does not error.**
**VERIFY:** inject an out-of-vocabulary value ⇒ run halts naming SKU, key, value.

**FR-DRV-003 · M** — The loader **shall** emit every facet key its chapter declares for **every SKU in
that chapter**, including display-only keys the rail does not filter on.
**WHY:** `DATA-MODEL §3.1` (revised 2026-07-15) — under the old "only the keys its category defines"
rule a plier carried no `esd` key, forcing the card to read a **second** custom field. Under this rule
**the card reads exactly one**, so a Stencil cap of 1 is survivable.
**VERIFY:** per chapter, SKUs missing each declared key = **0**.

**FR-DRV-004 · M** — Where a SKU lacks a value for a key its rail **filters on**, the loader **shall**
report it as a **blocking** completeness failure.
**WHY:** ⛔ `DATA-MODEL §3.3` — filtering **fails closed**. A card without the key is **hidden the moment
that facet is used** — *unfindable, silently*. Measured: **15 unpriced cutters vanish under any price filter.**
**VERIFY:** completeness report per filtering key; non-zero ⇒ run fails.

**FR-DRV-005 · M** — Banding thresholds (capacity, price, tip width…) **shall** be **configuration
constants**, in one place per line.
**WHY:** `DATA-MODEL §3.2a` — *"bucket thresholds are config constants — one place to retune."*
**VERIFY:** change a threshold in config ⇒ band membership changes with no code edit.

**FR-DRV-006 · M** — Where the vendor publishes a real measurement, the loader **shall** emit both a
**band** key and a **display** key (e.g. `cap` + `cap_disp`) and **shall not** substitute the band on a
display surface.
**WHY:** `DATA-MODEL §3.2a` — rendering our invented band where the vendor publishes a figure is weaker
truth, and a band is meaningless to a shopper without its scale.
**VERIFY:** both keys present for every SKU in the applicable set.

**FR-PACK-001 · M** — Packed fields **shall** use `key=value;key=value`, absent keys omitted.
**VERIFY:** parser round-trip equals the source mapping.

**FR-PACK-002 · M** — The loader **shall HALT** if any packed value contains `;` or `=`, and **shall
not** escape, substitute or drop it.
**WHY:** `DATA-MODEL §4.3` — the theme splits on those characters; an escaped value corrupts every key after it.
**VERIFY:** inject a value containing `;` ⇒ halt.

**FR-PACK-003 · M** — The loader **shall** assert every packed value is **≤250 characters** before
writing, **shall** report the maximum and the SKU producing it, and **shall** split into an overflow
field by pack order rather than truncate.
**WHY:** `LOADER-SPEC §5`; `BC-API-REFERENCE §3` — **250 is the safe intersection** of BC's own
conflicting docs (250 vs 255), and exceeding it is a hard **422**, not a truncation.
**VERIFY:** report the max across the whole line; a >250 fixture splits, never truncates.

**FR-PACK-004 · M** — The loader **shall not** nest one packed field inside another.
**WHY:** `LOADER-SPEC §5` — `spec_docs` uses `= ; |` internally. Nesting corrupts both.
**VERIFY:** static check — no packed value contains another packed field's delimiters.

**FR-PACK-005 · M** — Spec values **shall** be **finished display strings**; the theme **shall not** be
required to parse, convert, round or format.
**WHY:** `DATA-MODEL §4.3`. Dual unit → `0.2–1.0 mm / 0.008–0.04 in`; range separator is **en-dash U+2013**.
**VERIFY:** the rendered value is byte-identical to the packed value.

**FR-PACK-006 · S** — When new keys are added, pack order **shall** be **append-only** for existing keys.
**WHY:** `LOADER-SPEC §5` — appending leaves every already-correct product's prefix undisturbed. **Pack
order is not render order** — render order belongs to the theme.
**VERIFY:** diff packed strings before/after adding a key; existing prefix unchanged.

---

## 6. Families and relations

**FR-REL-001 · M** — The loader **shall** compute each product's family from **declared line rules** and
write it to BC `related_products` as an array of product ids.
**WHY:** `ADR-TOOL-FAMILY-LINKING` chose BC-native relations — the only option Google's guidance
endorses, server-rendered and crawlable. Lindström's rule is **`PRODUCT BLOCK` ladder ∪ handle twins**
(`DATA-MODEL §270`); block alone excludes the twins, and further filtering to "same cut-type" yields
2 rows and risks pulling tapered-head SKUs.
**VERIFY:** membership matches the declared rule on a sampled set.

**FR-REL-002 · M** — The loader **shall** write `related_products: []` for a family-less product
**unconditionally**, and **shall not** skip the write.
**WHY:** ⛔ **THE LIVE DEFECT.** `LOAD-TO-DESIGN [OPEN] 2026-08-17` — **163 products carry `[-1]`**,
BigCommerce's **V2 "auto-determine" sentinel**, so BC **invents** the series table. The current code's
own comment predicted exactly this; a `if not linked and not had: continue` guard meant `[]` was never
sent. `[-1]` also has **length 1**, so the theme's `{{#if related_products.length}}` gate opens.
**VERIFY:** store-wide count returning `[-1]` = **0**, quoted **against the before-count of 163**.

**FR-REL-003 · M** — On any change affecting a family, the loader **shall** recompute the family and
rewrite `related_products` on **every member**, not only on changed products.
**WHY:** **BigCommerce does not mirror the relation.** A delta that writes only new SKUs leaves every
pre-existing sibling holding a pre-delta list — the new model is missing from *their* pages while its
own looks correct. This is the defect Tony reported 2026-08-17.
**VERIFY:** **pairwise symmetry** — for every pair (A,B), A lists B **and** B lists A; report the pair
count. Prove the check can fail by breaking one side in a dry run.

**FR-REL-004 · M** — Family members **shall** be restricted to SKUs **actually present in BC**.
**WHY:** `RUNBOOK §8 PASS 2` — this is what makes a partial load render correctly and a re-run
**self-heal** stale pointers after a delete.
**VERIFY:** no relation entry resolves to a missing product.

**FR-REL-005 · M** — The loader **shall** write family members in the **intended reading order**.
**WHY:** the theme prints the list in BC's returned order and **does not sort** — sorting is recorded
as owed and unbuilt (`product-view-tool.html:533`). Tony read `105 · 106 · 117 · 109 · 110` as wrong
because it **is** unordered.
**VERIFY:** rendered row order equals the configured sort on a sampled family.

**FR-REL-006 · M** — The loader **shall** measure and report whether BigCommerce truncates long
relation lists, and **shall not** design around an unmeasured cap.
**WHY:** `ADR-TOOL-FAMILY-LINKING:114`, open since written: *"Blocks run to 12+; **truncation would be
silent**."* Never answered.
**VERIFY:** write the largest family, GET it back, report **written vs returned** counts.

**FR-REL-007 · M** — Relations **shall** be written in a **second pass**, after products exist.
**WHY:** relations are by product **id**, and ids do not exist until pass 1 creates the products.
**VERIFY:** pass 2 runs against a complete id map; no write attempts an unknown SKU.

---

## 7. ⛔ Gates and controls — do not trim this section

> **Every catastrophic defect in this program was silent.** A check that can only report success is not
> a check. Each gate **fails loud and halts**; none may be "warned past".

**FR-GATE-001 · M** — Every verification **shall** include a **control that would fail if the instrument
were broken**, executed in the **same run**.
**WHY:** proven repeatedly. "0 products with defect X" is indistinguishable from "my query is broken".
Note the corollary the loader itself established: **a retirement check asserting 0 rows cannot carry a
same-query control** — once the rows are gone there is nothing present to prove the call worked. Such
checks need a **separate positive probe**.
**VERIFY:** every acceptance report names its control and shows the observed positive.

**FR-GATE-002 · M** — Any assertion of the form "N defects remain" **shall** report **before and after** counts.
**WHY:** *a zero that was never non-zero proves nothing.*
**VERIFY:** the report shows both numbers.

**FR-GATE-003 · M** — Pre-flight gates **shall** run before any write and halt on failure:

| Gate | Assertion | Provenance |
|---|---|---|
| **G-VOCAB** | every packed facet value ∈ controlled vocabulary | `RUNBOOK G2` |
| **G-EXISTING** | all target SKUs queried in BC first; pre-existing matches reported with ids | `RUNBOOK G4` — an unmatched pre-existing SKU is created as a **duplicate** |
| **G-CATEGORY** | every category name resolves to a BC id; **HALT** if any does not | `RUNBOOK G5` — never auto-create; that is how the misspelled `Stripperss` twin was born |
| **G-IMAGES** | HEAD-check every image URL; report dead ones | `RUNBOOK G6` — **BC fails image fetches quietly** |
| **G-LIMITS** | name ≤250 · custom-field value ≤250 · image_url ≤255 · ≤1000 images/product · required-on-create present | `BC-API-REFERENCE §8` |
| **G-ROLLBACK** | rollback procedure written **before** the full run | `RUNBOOK G7` |

**VERIFY:** each gate demonstrated failing on a synthetic violation.

**FR-GATE-004 · M** — Runs **shall** proceed **dry run → small batch → full**, never straight to full.
**WHY:** `RUNBOOK G7`.
**VERIFY:** the runner refuses a full run with no preceding successful dry run for the same input hash.

**FR-GATE-005 · M** — Acceptance **shall** be measured on the **rendered storefront**, not only on the
API payload.
**WHY:** `DATA-MODEL §3.3` — Handlebars `{{#each}}` over an undefined `custom_fields` is a **no-op**, and
BigCommerce has an **open unresolved report** of `custom_fields` going undefined even in the documented
PDP context (stencil-cli#1229). **A passing filter over zero attributes looks fine.**
**VERIFY:** assert `data-*` presence on a rendered card **and** a non-zero decoded image count.

**FR-GATE-006 · M** — Any HTTP probe used for verification **shall** send a browser-equivalent
`Accept-Language` header.
**WHY:** measured 2026-07-30 — `stencil-cli` dereferences that header without a guard
(`renderer.module.js:347`) and returns an opaque **500** to any client omitting it. `curl` omits it by
default; browsers never do. **A perfectly healthy server looked dead to two sessions for hours.**
**VERIFY:** the same URL returns 200 with the header and 500 without; both recorded.

---

## 8. BigCommerce write semantics

**FR-BC-001 · M** — The loader **shall** upsert by SKU (GET → update if present, create if absent) and
**shall never** blind-create.
**WHY:** `RUNBOOK §8` — a create-over-existing **regenerates the product and clobbers re-hosted images**.
**VERIFY:** a re-run produces 0 creates and 0 duplicates.

**FR-BC-002 · M** — On **update**, the loader **shall** strip `custom_fields` from the product body,
then GET live fields, match **by name**, PUT existing, POST missing, and DELETE duplicates.
**WHY:** ⛔ `BC-API-REFERENCE §3` — *"A custom field sent in a product PUT without an `id` is treated as a
NEW ADDITION, not a replacement."* Every re-run appends a second `filter_metadata`; the storefront reads
whichever it hits first. **This silently destroys idempotency.**
**VERIFY:** run twice; custom-field count per product unchanged, zero duplicate names.

**FR-BC-003 · M** — On update the loader **shall not** modify `is_visible` or inventory, and **shall**
modify price only per the line's declared policy.
**WHY:** `RUNBOOK §8 HARD RULE` — *"A load run must never silently override a decision a human made in BC
admin."* Without the split a re-run **un-hides a product Tony deliberately hid**.
**VERIFY:** hide a product in admin, re-run, assert still hidden.

**FR-BC-004 · M** — PDP template routing **shall** use a **dedicated custom field** (`ct_page_type`),
never `layout_file`, and absence **shall** mean the default archetype.
**WHY:** `DATA-MODEL §4.7`; `RULING-LEDGER CT-1..CT-5`; `BC-API-REFERENCE §7` — **`layout_file` is
Blueprint-only and a no-op on Stencil.** Fails closed: absent ⇒ equipment.
**VERIFY:** 100% of line products carry the value; **control** — a known non-line SKU returns absent.

**FR-BC-005 · M** — Document and asset paths **shall** be stored **relative**, never with a hostname.
**WHY:** ⛔ `LOADER-SPEC ENVIRONMENT RULE` — the same data is served from **three hostnames** (live,
sandbox, store-hash). A stored hostname is correct on exactly one. This already left **all 292 products
pointing at a 404** when the warranty file moved.
**VERIFY:** the identical stored path returns 200 + correct content-type on at least two hostnames.

**FR-BC-006 · S** — Third-party assets **shall** be stored as an **identifier**, not a URL.
**WHY:** same section — store `ds=58222`, so a vendor site reorganisation is a one-line theme change,
not a 292-product reload.
**VERIFY:** no absolute third-party URL in any packed field.

**FR-BC-007 · M** — The loader **shall** respect BC rate limits and **shall** treat HTTP **207** as success.
**WHY:** `BC-API-REFERENCE §1`; v3 ≈450 requests/30s, catalog endpoints cap concurrency.
**VERIFY:** a full run completes with zero 429s.

**FR-BC-008 · M** — Where a price must be hidden, the loader **shall** set the documented companion
field and **shall** surface that this makes the product non-purchasable.
**WHY:** `BC-API-REFERENCE §2` — `is_price_hidden` requires `availability: "disabled"`. Tony's 20
unpriced SKUs load at `$0` + hidden; **`$0` alone would have shipped 20 false price tags.**
**VERIFY:** unpriced SKUs render call-for-price, not `$0`.

---

## 9. Truth

**FR-TRUTH-001 · M** — The loader **shall not** invent, infer or guess a product claim. Where the vendor
is silent, it **shall** omit.
**WHY:** Rule 3, non-negotiable — *never put anything on the site that isn't true.* Corollary already in
force: **`esd=no` means "not stated", never "not ESD safe"** (`DATA-MODEL §3.2`).
**VERIFY:** every emitted claim traces to a source cell (`FR-OPS-003`).

**FR-TRUTH-002 · M** — Where two vendor values are **arithmetically derivable** from one another
(transposed, copied, decimal-shifted), the loader **shall** correct via a **logged, reversible** override
map. Where they **contradict** and arithmetic cannot resolve them, it **shall** emit the metric value
alone and **shall not** guess the other.
**WHY:** `DATA-MODEL §4.3a` — measured across **878 dual-unit numbers: 50 disagree, 9 provably wrong**.
*"Two numbers that provably contradict cost more than one imprecise number — a shopper who catches
`0.8 mm / 0.07 in` stops trusting every figure on the page, including the right ones."*
**VERIFY:** the override map logs SKU · field · before · after · derivation, and is reversible.

**FR-TRUTH-003 · M** — The loader **shall not** silently rewrite vendor titles or claims; suspected
vendor errors **shall** be reported for routing to the vendor.
**WHY:** `LOADER-SPEC §6.2` — six wrong vendor titles were **routed, not rewritten**.
**VERIFY:** a defect report exists per run.

**FR-TRUTH-004 · M** — Authority for **what is true** rests with the operator, not the loader and not Design.
**WHY:** Tony, 2026-08-17: *"& More is accurate. I am the authority. override all feedback on this."*
And, relayed the same day: *"let me worry about affirming what is or is not correct… you put in what I say."*
**VERIFY:** truth questions are surfaced for decision, never auto-resolved.

---

## 10. Observability, ledger, rollback

**FR-OPS-001 · M** — The loader **shall** write a per-run **ledger** recording each SKU's action
(created / updated / skipped / excluded / failed) and its BC id.
**WHY:** `RUNBOOK §8` — the ledger is what lets a failed run resume at the first gap and makes targeted
cleanup possible.
**VERIFY:** kill a run mid-flight; resume completes without duplicating work.

**FR-OPS-002 · M** — The loader **shall** be **idempotent**: an identical second run produces zero changes.
**VERIFY:** run twice; the second reports 0 creates, 0 field writes, 0 relation writes.

**FR-OPS-003 · M** — The loader **shall** emit a **provenance record** naming, per SKU per field, the
exact source file and column used.
**WHY:** built as `build/alias_sources.csv` (541 rows) at Design's request, and it is what proved 138
lengths and 112 tip widths came from alias columns.
**VERIFY:** provenance rows = emitted aliased-field count.

**FR-OPS-004 · M** — Every run **shall** have a documented **rollback**.
**VERIFY:** roll a batch back; the store returns to its prior state.

**FR-OPS-005 · S** — The loader **shall** log every applied Design ruling with a status and **evidence
for that ruling alone**.
**WHY:** the existing `RULING-LEDGER.md` practice — `VERIFIED` requires evidence for that clause alone;
anything else stays `BUILT`. It works; keep it.
**VERIFY:** a scan reports directives not yet logged.

---

## 11. Non-functional requirements

| ID | Requirement | Pri |
|---|---|---|
| **NFR-001** | A full line load (~300 SKUs) completes within one operator sitting, unattended after start. | M |
| **NFR-002** | Runs on the operator's Windows workstation; no server dependency. | M |
| **NFR-003** | Secrets supplied at run time; **never** stored in the working folder. | M |
| **NFR-004** | Targets BigCommerce **Catalog v3**; any v2 dependency documented explicitly. | M |
| **NFR-005** | Derivation is unit-testable with no network and no vendor files. | M |
| **NFR-006** | Every failure message names SKU, field, observed value, expected condition. | M |
| **NFR-007** | Sandbox or live selectable by configuration, **defaulting to sandbox**. | S |

---

## 12. Explicitly out of scope — recorded so they are not re-proposed

| | Why excluded |
|---|---|
| **W-001** a separate facet manifest file | `DATA-MODEL §3` DECISION 2026-07-11 (Tony): per-SKU facet data lives **on the product**. One source of truth, no client-side JSON join. |
| **W-002** discrete custom fields per spec row | Ruled 2026-07-22, proven on product 4272: **16 fields → 4**. The 13 discrete fields were built around a theme limit **that does not exist**. |
| **W-003** a theme-side workaround for bad relation data | Ruled 2026-08-17: the template **cannot** distinguish an invented relation from a real one — BC resolves `[-1]` into real product objects before Stencil sees them. **Data contract only.** |
| **W-004** `tip_material` / `length` as facet keys | Not emitted; specifying against them yields an empty render, not an error (`DATA-MODEL §3.2`). |
| **W-005** `price` as a rail facet | Tony killed it 2026-07-21. Data retained, facet config-hidden. |
| **W-006** auto-creating BC categories | `RUNBOOK G5` — how the misspelled `Stripperss` twin was born. |
| **W-007** truncating any packed value | `LOADER-SPEC §5` — split by pack order, **never** truncate. |

---

## 13. Open questions the design must resolve with the operator

1. **Relation list cap** — unmeasured since the ADR (`FR-REL-006`). A silent truncation on a large
   family is a live risk today.
2. **The 152 pre-existing `[-1]` products** — released by Tony 2026-08-17 (*"direct a fix"*). Confirm the
   next-gen loader **inherits** the fixed state rather than re-deriving it.
3. **`esd_safe` → `filter_metadata.esd` fold** — planned (5 fields → 4), gated on Impl repointing the
   badge. Confirm which shape to build against.
4. **118 products missing specs that exist in the vendor sheet** (unmapped columns) — `LOAD-TO-DESIGN
   [OPEN] 2026-07-22`, still open. The next-gen column map should close it.
5. **Which line is next**, and does it need a new `ct_page_type` value — i.e. a new PDP archetype — or
   does it reuse `tool`?

---

## 14. Traceability

| Group | Primary source |
|---|---|
| §3 Generalization | new — the reason for the rewrite |
| §4 Ingestion | `DESIGN-TOOL-LOADER-SPEC §1`, `RULING-LEDGER AL-*` |
| §5 Derivation / packing | `DESIGN-TOOL-DATA-MODEL §3–4`, `DESIGN-TOOL-PIM-FIELD-SPEC §2A` |
| §6 Families | `ADR-TOOL-FAMILY-LINKING`, `RUNBOOK §8 PASS 2`, `LOAD-TO-DESIGN [OPEN] 2026-08-17` |
| §7 Gates | `RUNBOOK §2b` and the whole defect history |
| §8 BC semantics | `BIGCOMMERCE-API-REFERENCE` (verified against BC docs 2026-07-20) |
| §9 Truth | Rule 3; `DATA-MODEL §4.3a`; Tony 2026-08-17 |
| §10 Ops | `RUNBOOK §8 Operational`, `RULING-LEDGER` |

> **Ground truth that outranks this document:** the **shipped theme** (Tony 2026-07-23 — the theme as it
> exists overrides any spec that disagrees), and `pipeline/build_library.py :: FACET_KEYS + facets_for()`
> for facet **key names**. Re-read both before building against any key.

---

## Appendix A — Lindström reference data (the worked example)

Line #1, as it ships today. **Treat as a fixture for the generalized model, not as the model.**

### A.1 Facet keys — `filter_metadata` (11 live)
`type` · `cut` · `head` · `size` · `cap` · `cap_disp` · `handle` · `esd` · `block` · `series` · `tipw`

| key | applies to | vocabulary | derived from |
|---|---|---|---|
| `type` | all 292 | slug of the L3 section | `section_l3` |
| `cut` | cutters | `ultra-flush` · `flush` · `micro-bevel` | trademark term in `TITLE` |
| `head` | all | per-chapter (head/tip shape, jaw surface, drive type) | **`head_type` ELSE `group`** — fallback, never both |
| `size` | cutters | `xs` · `s` · `m` · `l` | vendor `Head Size` |
| `cap` | cutters, strippers (113) | `fine` · `medium` · `heavy` · `xheavy` | `capacity_mm` → buckets 0.8 / 1.25 / 1.6 / ∞ |
| `cap_disp` | same 113 | vendor's own string, verbatim | `capacity_raw` |
| `handle` | cutters, pliers | `standard` · `ergo` · `long` | SKU prefix: `RX`→ergo, `HS`(not shear)→long, else standard |
| `esd` | every tool | `yes` · `no` | vendor `ICONS` field — **never** inferred from `Resistivity` |
| `block` | all with a block | slug of vendor product block | `product_block` |
| `series` | cutters + pliers | `s80` · `rx` · `hs` · `sup` | `handle` first, then MPN first digit (read **through** any letter prefix) |
| `tipw` | tweezers | `ultra-fine` · `fine` · `medium` · `broad` | `Tip Width, mm` banded <0.20 / 0.20–0.49 / 0.50–0.99 / ≥1.00 |

**Chapter rails as shipped** (ground truth = `templates/components/category/ct-filter-rail-*.html`):
Tweezers `type` · `head` · `tipw` · `esd` — four facets, ESD **include-only**, never a Yes/No pair.

### A.2 Spec keys — `spec_display` (16)
`cr cc tw ht hs rs hn ln hh hw hk wt co` **+ `tt bh bw`**
⚠ The three appended keys reached two documents and **not** the loader spec, runbook or PIM spec — a
loader following the old line re-emits 13 and **107/103 products keep the empty rows the ruling existed
to fill, with every check passing.** Found by an independent reviewer. This is why `FR-GEN-002` demands
one declarative source per line.

### A.3 Chapter sizes (2026-07-10)
Cutters 116 · Tweezers 123 · Pliers 24 · Screwdrivers 19 → these get rails.
Small chapters (≤~10) are list-only, no rail: Torque Tools 9 · Shear Cutters 8 · Cable Cutters 5 ·
Spatulas 4 · Kits 2 · Special 1.

### A.4 Known live state at time of writing
292 products · 5 custom fields each · `ct_page_type=tool` on 292/292 · **163 products carrying
`related_products = [-1]`** (fix directed 2026-08-17, 11 in-scope + 152 released by Tony) · 20 unpriced
SKUs at `$0` + price hidden · 1 zero-weight SKU (`59-TL 242ACF`) · 23 colliding product names (reported,
not gated).
