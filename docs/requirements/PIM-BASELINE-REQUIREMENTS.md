# Castletronics PIM Pipeline III — Baselined Requirements Specification

| | |
|---|---|
| **Document ID** | `CT-PIM-SRS-001` |
| **Version** | 1.0 — **BASELINED** |
| **Date** | 2026-08-19 |
| **Status** | Binding. This document supersedes and replaces both source specifications below. |
| **Supersedes** | `MULTI-BRAND-LOADER-REQUIREMENTS.md` v1.1 (2026-08-17) and `LOADER-NG-REQUIREMENTS.md` / `CT-LOADER-NG-SRS-001` (2026-08-17) |
| **Author** | Merged and baselined by Claude (Cowork) under operator direction, from the Cornerstone Design AI and Loader AI source specs |
| **Operator / authority** | Tony (Castletronics). Per `FR-TRUTH-004`: authority for what is true rests with the operator. |

---

## 0. How to read this document

This is the **single binding requirements specification** for PIM Pipeline III.
The two source documents remain in the repository for provenance — their WHY
citations trace to production history — but **where anything disagrees, this
document wins.** Every reconciliation between the sources is recorded in
**§12 (Conflict-resolution log)**; every source requirement is accounted for in
**§13 (Traceability)**.

Requirement identifiers:

- `FR-1 … FR-110` retain the numbering of the Multi-Brand spec v1.1, so its
  internal cross-references remain valid.
- `FR-111+` are requirements carried in from the NG spec that had no
  Multi-Brand equivalent.
- `NFR-n`, `INV-n`, `AC-n`, `D-n` (baseline decisions), `OQ-n` (open questions).

**Every requirement is testable.** Requirements amended during baselining are
marked **[AMENDED]** with the change described in place and logged in §12.

### 0.1 Baseline decisions (operator, 2026-08-19)

| ID | Decision | Effect |
|---|---|---|
| **D-1** | The two source specs are merged into this single baseline; neither is independently binding any longer. | This document. |
| **D-2** | Built data is persisted in **SQLite as the authoritative store**, with a **deterministic canonical text export** emitted on every build for diffing and version control. | FR-39, FR-41, FR-42, AC-3 amended (§4.5). |
| **D-3** | On post-write verification failure the system **halts further writes and waits for the operator**, presenting the rollback diff for explicit approval. It never rolls back automatically. | FR-95 resolved (§4.10). |
| **D-4** | Implementation stack is delegated to the design document (`CT-PIM-ARCH-001`), to be chosen with an ADR-style justification. | NFR-13. |
| **D-5** | System is decomposed into two subsystems: the **PIM core** (intake, normalise, organise, update — the system of record for all product data) and the **Distribution chain** (publication to channels: new load, update, deletion). | §1.1, §3. |
| **D-6** | **Operator direction (verbatim intent): code must not drive the supported brands.** The code handles data and data relationships for any brand and normalises it; **the type of data, the amount of data, and the format of data shall not be driven by software.** The engine defines *operations* (read, join, normalise, derive, pack, publish); the brand pack defines *everything about the data* — which fields exist, their types, formats, units, counts, relationships and rules. Code enumerates no field name, no brand, no count, no format (FR-1). | P1, P3, FR-1..5, FR-8, §6.1 note. |
| **D-7** | **Primary/alias conflicts halt for operator ruling** (2026-08-19, resolves OQ-19). The build halts naming SKU, field, both values and both source columns; the operator rules via an override; neither value ships un-ruled. Supersedes both the source specs' load-neither rule and v1's shipped keep-primary behavior. | FR-20 amended; §7.3. |

### 0.2 ⛔ One coupling that must not be broken

**§4.6 (nothing is unwritable) is only safe when shipped with §4.9 (validate
every change) and §4.10 (roll back every run).** They are one mechanism
described in three places, not three independent features.

The first-generation loader refused, in code, to write price fields. That
refusal was removing a real risk: at the time, the built library held
**pre-increase** prices, and an unrestricted full apply would have reverted the
August increase on **288 products** and reported `updated=288 failed=0` as a
clean success. It was caught by a field-level diff against a saved snapshot
**before** any write. So the refusal was solving a real problem — with the
wrong instrument. It also made MSRP unreachable for two weeks (§9.3).

**An implementer who takes §4.6 without §4.9 and §4.10 has rebuilt the
288-product revert and removed the thing that caught it.**

### 0.3 ⛔ Every catastrophic defect in this program's history was silent

A check that can only report success is not a check. §9 records failures that
actually happened in production; §4.9 and the gate requirements exist because
of them. **If you implement the data model beautifully and skip the gates and
controls, you will rebuild the same class of failure with better structure.**

---

## 1. Purpose and scope

### 1.1 Purpose

> **Operator statement of purpose (Tony, 2026-08-19):** *"The entire point is
> to assemble brand information that aligns to a key, like product code, and
> build up information from a number of files. This will be a database of
> complete information that can then be processed to export data, load to a
> site, etc."* Every requirement in this document serves that sentence:
> key-aligned assembly (§4.2–4.3), from any number of declared files (FR-6),
> into one complete record per SKU (FR-14, §6.1), held as a database with full
> provenance (§4.5), processed downstream — export (FR-137), publish (§4.7),
> and every other operation (§4.8) — from the assembled records, never from
> the raw files.

Build and operate the product-information system of record for Castletronics:

1. **PIM core** — ingest vendor spreadsheets for **any brand**, normalise them
   into one canonical row per SKU, derive presentation and filtering data
   (facets, specs, families, SEO), and hold **all data on every product** —
   editable, versioned, auditable.
2. **Distribution chain** — publish that data to commerce channels
   (BigCommerce first, others by adapter), covering **new loads, updates and
   deletions** — flexibly, repeatably, and reversibly.

### 1.2 What exists today, and why it is being replaced

The first-generation pipeline successfully loaded the Lindström catalogue to
the live BigCommerce store (see OQ-1 on the live count). It is, however:

| Limitation | Evidence |
|---|---|
| **Single-brand** | `config.py` hardcodes source filenames, 11 chapter names, SKU prefix `59-`, brand `Lindström`, and expected row counts (322/312/10/302/20) |
| **Fixed source set** | Exactly six sources `S1..S6`, each with a bespoke reader |
| **Brand rules in code** | Series derivation, ESD policy, tip-width bands, category dual-list/move rules all live in Python |
| **Endpoint-coupled** | BigCommerce payload shapes, custom-field semantics and rate limits are spread through `build_products.py` and `bc_loader.py` |
| **No backup, no rollback** | The loader has neither. Both were added late, by hand, as separate tools |
| **Fields unwritable in code** | `build_body()` pops `price`, `retail_price` and `custom_fields` on update — an operator cannot change them at all |
| **Split write authority** | Product fields via one tool, prices via another — the seam caused a two-week live data defect (§9.3) |

Adding a second vendor line today means **editing the pipeline, not describing
the line**.

### 1.3 Scope

**In scope:** ingestion, normalisation, derivation, persistence of built data,
change management, validation, publication, verification, backup, rollback and
restore — for products, custom fields, facet/filter data, spec display data,
images, categories, relationships (families), SEO strings and template routing.

**Out of scope:** authoring vendor source data; storefront theme rendering
(the theme is a consumer of the data contract, §3.2); pricing strategy;
category tree design; order and inventory management; and any judgement about
what is *true* of a product (§4.12).

### 1.4 Design principles

> **P1 — The system is a data pipeline with an endpoint plugin, not a
> BigCommerce loader that happens to read spreadsheets.**

Everything brand-specific is **data**. Everything endpoint-specific sits
behind **one interface**. What remains in the core is generic.

> **P2 — Safety comes from visibility and reversibility, never from
> prohibition.**

The system does not protect data by refusing to change it. It protects data by
showing every intended change before it happens, validating it, verifying it
afterwards, and being able to put it back. **A field the operator cannot
change is a defect, not a safeguard.**

> **P3 — Declared, never inferred.**

The system never infers a brand's structure (chapters, facets, families,
identity) from its data. Inference drifts silently when a vendor reorganises a
sheet. Structure is declared in the brand pack; a vendor change produces a
loud validation failure, not a silent re-derivation.

> **P4 — Truth is the operator's.**

The system never invents, infers or guesses a product claim. Where the vendor
is silent, it omits. Where sources disagree irreconcilably, it surfaces the
question. §4.12.

---

## 2. Definitions

| Term | Meaning |
|---|---|
| **Brand pack** | A directory of configuration and rules defining one brand. Contains no code. |
| **Source** | One vendor file (xlsx/xlsm/csv/json) declared in the brand pack |
| **Canonical row** | One normalised record per SKU — the merge output; the single intermediate |
| **Canonical field** | A vendor-neutral field name (e.g. `length_mm`) as distinct from a vendor column (e.g. `Total length`). All derivation operates on canonical fields only. |
| **Derived field** | A value computed from canonical fields (facets, SEO, packed display strings, families) |
| **Built data** | Canonical rows plus derived fields, persisted and versioned (§4.5) |
| **Canonical export** | The deterministic text serialisation of built data emitted on every build — the diffing and version-control surface (D-2) |
| **Chapter** | A brand-declared grouping within a line that gets its own filter rail (maps to a category level at the endpoint) |
| **Facet** | A filterable/displayable per-SKU attribute, packed into a filter field |
| **Spec** | A display-only per-SKU attribute, packed into a display field |
| **Family** | The relationship set a product's "In this series" table lists |
| **Packed field** | A single endpoint field carrying `key=value;key=value` |
| **Payload** | Endpoint-shaped representation of a built row |
| **Endpoint** | A publication target (BigCommerce, CSV export, another platform) |
| **Managed field** | A field the system writes at the endpoint for a given run. Declared data, operator-editable. |
| **Unmanaged field** | A mapped field the system reads and reports drift on, but does not write this run |
| **Owner** | The single component responsible for writing a managed field |
| **Ledger** | Durable record of what was published, per SKU, with remote ids and before-images |
| **Before-image** | The endpoint's value of every field about to be written, captured per row at write time |
| **Snapshot** | Complete capture of remote state before a change |
| **Change set** | The field-level set of differences a run intends to write |
| **Blast radius** | The measured size, direction and concentration of a change set |
| **Gate** | A pre-condition check that halts the run when it fails |
| **Control** | A check that proves a measuring instrument is able to report failure |
| **Override** | An operator-authored correction applied at build time, never to source |

---

## 3. System context

### 3.1 Structure

```
   Vendor spreadsheets (N per brand, READ-ONLY)
                │
                ▼
   ╔═══════════════════════════════════════════╗
   ║ PIM CORE (system of record)               ║
   ║  1. INGEST        declared sources → raw  ║
   ║  2. NORMALISE+MERGE → canonical rows      ║
   ║  3. DERIVE        facets·SEO·pack·family  ║
   ║  4. BUILT DATA STORE (SQLite, D-2)        ║
   ║       └─ canonical text export per build  ║
   ╚═══════════════════════════════════════════╝
                │
                ▼
   ╔═══════════════════════════════════════════╗
   ║ DISTRIBUTION CHAIN                        ║
   ║  5. VALIDATE + PUBLISH                    ║
   ║     change set → confirm → write → verify ║
   ╚═══════════════════════════════════════════╝
                │            ▲
        ┌───────┴────────┐   └── rollback (per-run, from before-images)
        ▼                ▼
   BigCommerce      other endpoints (adapter interface)
```

**Stages 1–4 have no knowledge of any endpoint.** Stage 5 is the only place an
endpoint's field names, limits or semantics appear.

### 3.2 The BigCommerce endpoint contract (the shipped theme's reads)

These are **contracts, not preferences**. The Castletronics Cornerstone theme
fails closed against all of them. They bind the **BigCommerce adapter and the
Lindström brand pack**, not the core.

| The theme reads | From | Contract |
|---|---|---|
| Filter rail + card `data-*` attributes | `filter_metadata` | `key=value;…`, **ASCII slugs** |
| PDP spec table · card chips · series compare columns · BC compare page | `spec_display` | `key=value;…`, **finished display strings** |
| Document links (datasheet, warranty) | `spec_docs` | packed; uses `= ; \|` internally |
| ESD badge | `esd_safe` | folding into `filter_metadata.esd` in Phase 2 (OQ-4) |
| **Which PDP template renders** | `ct_page_type` | value `tool`; **absent ⇒ equipment** (fails closed) |
| "In this series" table | BC native `related_products` | array of product ids; `[]` written explicitly (FR-65) |

**Field-count budget: 5 custom fields today, 4 after the `esd_safe` fold.**

> **Ground truth that outranks any spec:** the **shipped theme** (operator
> ruling 2026-07-23 — the theme as it exists overrides any spec that
> disagrees), and the v1 `pipeline/build_library.py :: FACET_KEYS +
> facets_for()` for facet **key names**. Re-read both before building against
> any key.

---

## 4. Functional requirements

### 4.1 Brand configuration

- **FR-1** The system shall load all brand-specific configuration from a
  **brand pack** — a directory of declarative files — with no brand identifier,
  filename, field name, count or rule appearing in code.
- **FR-2** The brand pack shall declare: brand identity; SKU construction rule;
  source declarations; join strategy; **normalization rules (the brand's
  normalization function — see §4.3 note)**; field mappings; derivation rules;
  vocabularies; validation expectations; managed-field sets; blast-radius
  thresholds; endpoint bindings. *(For endpoint-consumed routing values such as
  `ct_page_type`, see FR-131.)*
- **FR-3** The system shall support **multiple brand packs concurrently**, with
  no shared mutable state between them, and shall require an explicit brand
  selection on every invocation. Facet vocabularies, families and exclusions
  are **brand-scoped**: no brand-A product may appear in any brand-B family or
  facet count.
- **FR-4** The system shall **validate a brand pack** against a schema before
  any processing — before any source file is read — reporting every error at
  once rather than failing on the first.
- **FR-5** The system shall run any operation against a **named environment**
  (e.g. `sandbox`, `live`) resolved from the brand pack, and shall never
  default to a production environment.

### 4.2 Ingestion (Stage 1)

- **FR-6** The system shall ingest **N sources per brand**, where N is not
  fixed, each declared with identifier, path, format, sheet/range, header row,
  and key column.
- **FR-7** The system shall support at minimum `.xlsx`, `.xlsm`, `.csv`,
  `.json`. The reader shall be selected by declaration, not by extension
  sniffing.
- **FR-8** The system shall read all source values as **text by default**, and
  coerce types only where a declaration says so.
  > *Rationale: numeric inference turned the vendor's `108` into `108.0`, which
  > shipped as "108.0 mm" on a customer-facing spec row; and an EAN read as a
  > float produced a malformed GTIN.*
- **FR-9** The system shall read sources **without acquiring a write lock**,
  and shall succeed when a file is open in Excel or held by a sync client —
  copying to a temporary location if required.
- **FR-10** The system shall treat every source as **strictly read-only** and
  shall never write to a source path.
  > *Rationale: the vendor directory is a copy taken from masters. A correction
  > written there is silently overwritten by the next copy — the fix appears to
  > apply, then vanishes. Corrections belong in overrides (FR-25).*
- **FR-11** The system shall record, for each source, a **content hash, size
  and modification time** in the build manifest, and shall report when a source
  has changed since the previous build.
- **FR-12** The system shall support a source that is **two or more blocks in
  one sheet** (e.g. product data and price data side by side, row-aligned but
  keyed by different columns), each block declared and keyed independently.
  > *Rationale: joining on the obvious column collided two genuinely distinct
  > products that share one product code; the correct key covered 322/322.*
- **FR-13** The system shall support declaring a source as **optional**, and
  shall proceed with a recorded warning when it is absent.
- **FR-111** The system shall **not normalise vendor column headers**. Headers
  are matched exactly as declared.
  > *Provenance: NG FR-ING-005. Three legitimate Lindström column names contain
  > commas; header normalisation silently split them.*
  > **VERIFY:** a header containing `,` resolves to the correct canonical field.

### 4.3 Normalisation and merge (Stage 2)

> **Per-brand normalization function (operator direction, 2026-08-19).** Every
> brand has its own normalization function, **declared in its pack and
> composed from the engine's normalization operations** — key handling, unit
> parsing, decimal conventions, encoding checks, alias chains, value maps.
> The engine owns the operations (FR-15..24 below); the pack decides which
> apply to which columns, with which parameters, for that brand. Two brands
> therefore normalise completely differently while running identical code
> (D-6). A brand needing a normalization *operation* the engine lacks is a
> core feature request, never a per-brand script.

- **FR-14** The system shall produce exactly **one canonical row per SKU**.
- **FR-15** The system shall normalise join keys using a **declared** key
  function, and shall never assume two systems spell a product the same way.
- **FR-16** The system shall support **explicit code-association tables**
  mapping a key in one source to a key in another; these shall take precedence
  over any computed match.
  > *Rationale: the vendor's site code `TL 15A-GW` is the price book's
  > `15AGWM`. A raw key join found 203 of 346 products; the association table
  > found 334.*
- **FR-17** The system shall **never infer product identity from names or
  descriptions**. Identity comes from codes and declared associations only.
  > *Rationale: operator direction — "use the book and live sku associations.
  > dont factor the name, differences may be subtle." Name matching would bind
  > `8211` to `RX8211`, a different tool with different specs.*
- **FR-18** The system shall support **alias columns**: an ordered fallback
  chain of source columns for one canonical field, where an alias fires **only
  when the primary is empty**.
  > *Provenance: 138 lengths and 112 tip widths in the Lindström line come from
  > alias columns — those products ship blank without the chain.*
- **FR-19** For every aliased value the system shall record **which source
  column supplied it**, per SKU, in an auditable artefact.
  > *Rationale: without provenance a wrong storefront value cannot be diagnosed
  > — a bad vendor cell and the loader reading the wrong column need opposite
  > fixes. v1's `build/alias_sources.csv` (541 rows) is the model.*
- **FR-20 [AMENDED — OQ-19 RESOLVED, operator 2026-08-19 (D-7)]** When a
  primary and an alias are **both populated and disagree beyond a declared
  tolerance**, the build shall **HALT**, naming the SKU, the field, both
  values and both source columns. The operator resolves the conflict via an
  **override** (FR-25/26); the build then proceeds with the ruled value.
  A silent tiebreak is prohibited, and neither value ships un-ruled.
  > *Ruling history: both source specs said load-neither-and-report; the
  > shipped v1 loader was corrected 2026-07-22 to keep-primary-and-report
  > (`CT-PIM-V1-ASM-001` §5.2). Operator ruled 2026-08-19: **halt and rule
  > via override** — neither falsehood ships (a contradicted number, or an
  > absence that reads as not-applicable), consistent with FR-134. Impact of
  > the change is nil on current data: 0 of 322 products populate both
  > columns, so all three behaviors are byte-identical today and migration
  > (FR-107) is unaffected. The affected surface if it ever fires is
  > display-only (`spec_length`, `spec_tip_width` — not rail facets). The
  > condition has never occurred on real data, so the regression fixture is
  > the only proof the halt works — keep it (INV-1).*
- **FR-21** The system shall parse units **from inside the value**, never from
  the column header, where a declaration marks a column unit-bearing.
  > *Rationale: one `Length` column carries `130 mm` on one row and `4,72 in`
  > on 115 others. Assuming the header unit manufactures a wrong number.*
- **FR-22** The system shall support **decimal-comma** values and normalise
  them to a declared output form.
- **FR-23** The system shall support **dual-unit output** (e.g.
  `133.5 mm / 5.25 in`) composed from two source columns, and single-unit
  output where only one exists.
- **FR-24 [AMENDED]** The system shall detect and report **mojibake and
  encoding defects** in any text field destined for display or for a filter
  value, and shall inspect encoding-sensitive values **by codepoint, never by
  rendered appearance**.
  > *Provenance: NG FR-ING-006 folded in. A terminal that could not print
  > non-ASCII substituted `U+FFFD`, and a repair was nearly specced for clean
  > data. The same codepoint check found a real defect: `45º` using `U+00BA`
  > (masculine ordinal) where `U+00B0` (degree) is meant. Console appearance is
  > not acceptable evidence.*
- **FR-25** The system shall apply **operator overrides** — on any field,
  without exception — after merge and before derivation. An override shall
  apply **only when its recorded pre-value still matches** what the build
  produced; otherwise the build halts.
  > *Rationale: an override written against data that has since changed is
  > being applied to a value it was never derived from.*
- **FR-26** Overrides shall be **reversible** — deleting an entry restores the
  source-derived value — and shall carry a recorded basis (who, when, why).

### 4.4 Derivation (Stage 3)

- **FR-27** The system shall derive **facet values** from canonical fields
  using declared rules, supporting at minimum: direct mapping, slug, numeric
  banding, conditional scoping by category/chapter, and derivation from
  multiple inputs in declared precedence (e.g. Lindström `head`:
  `head_type` ELSE `group` — fallback, never both).
- **FR-28** Numeric band boundaries shall be **declared explicitly** as
  configuration constants in one place per brand, including which side a
  boundary value joins.
  > *Rationale: 52 of 94 products sat exactly on a boundary — this rule
  > silently decided half a category. "Bucket thresholds are config constants —
  > one place to retune."*
- **FR-29** The system shall support facets **scoped to a subset of
  categories/chapters**, and shall assert both the presence set and the
  **absence set**.
  > *Rationale: over-application of a facet is invisible to a presence check.*
- **FR-30** The system shall validate every derived facet value against a
  **frozen, versioned vocabulary** and shall **halt** on any value outside it,
  naming the SKU, the key and the value.
  > *Rationale: filter values are compared as literal strings by the
  > storefront. A mismatched value matches nothing and renders "no products" —
  > it does not error.*
- **FR-31** Adding a vocabulary value shall be an **explicit, recorded
  action**, never automatic. The operator shall be able to add one without a
  code change.
- **FR-32** The system shall support **packed multi-value fields**
  (`key=value;key=value`) with declared key order, declared delimiters, and
  omission of absent keys. Facet values in packed filter fields shall be
  **ASCII slugs** matching `^[a-z0-9][a-z0-9-]*$`, never display labels
  (display wording lives in the theme's rail config so it can change without a
  reload).
- **FR-33** A packed value shall **never contain a delimiter**. On encountering
  one the system shall **halt** — escaping or sanitising is prohibited.
  > *Rationale: the theme splits on those characters; an escaped value corrupts
  > every key after it. One theme parser handles several packed fields;
  > corruption in one spreads to the others.*
- **FR-34 [AMENDED]** The system shall enforce declared **length limits** on
  any field with a remote limit. The general rule is **halt rather than
  truncate**, naming the field, SKU and measured length. **Exception, by
  declaration only:** where the brand pack declares an **overflow field** for a
  packed field, an over-length packed value shall be **split into the overflow
  field by pack order**. Truncation is prohibited in all cases. Every run shall
  report the maximum packed length observed and the SKU producing it.
  > *Reconciles NG FR-PACK-003 (split) with MB FR-34 (halt) — see §12 C-3. For
  > BigCommerce custom fields the declared limit is **250 characters**, the
  > safe intersection of BC's own conflicting documentation (250 vs 255);
  > exceeding it is a hard 422, not a truncation.*
- **FR-35** A derived field with no value shall be **omitted entirely**, never
  written as an empty string, placeholder or default — a key with no value is
  **not packed at all**, never `key=`.
  > *Rationale: an empty spec row reads as missing data rather than
  > not-applicable.*
- **FR-36** The system shall derive **relationship sets** (families) from
  declared rules; every member of a family shall carry the same membership, so
  relationships are **symmetric by construction**.
  > *Provenance: the Lindström rule is `PRODUCT BLOCK` ladder ∪ handle twins —
  > block alone excludes the twins; further filtering to same cut-type yields 2
  > rows and risks pulling tapered-head SKUs (ADR-TOOL-FAMILY-LINKING).*
- **FR-37** The system shall emit relationship lists in a **declared order**,
  because endpoints and storefronts generally preserve stored order and do not
  sort.
  > *Provenance: the shipped theme prints BC's returned order unsorted
  > (`product-view-tool.html:533`); `105 · 106 · 117 · 109 · 110` read as wrong
  > because it was unordered.*
- **FR-38** Derivation shall be **pure and per-row** wherever possible; any
  cross-row derivation (families, chapter completeness) shall be declared
  explicitly.
- **FR-112** The system shall emit, for every SKU in a chapter, **every facet
  key that chapter declares** — including display-only keys the rail does not
  filter on.
  > *Provenance: NG FR-DRV-003. Under the old "only the keys its category
  > defines" rule a plier carried no `esd` key, forcing the card to read a
  > second custom field. Under this rule the card reads exactly one, so a
  > Stencil cap of 1 is survivable.*
  > **VERIFY:** per chapter, SKUs missing each declared key = 0.
- **FR-113** Where a SKU lacks a value for a key its rail **filters on**, the
  system shall report it as a **blocking** completeness failure.
  > *Provenance: NG FR-DRV-004. ⛔ Filtering fails closed: a card without the
  > key is hidden the moment that facet is used — unfindable, silently.
  > Measured: 15 unpriced cutters vanish under any price filter.*
- **FR-114** Where the vendor publishes a real measurement behind a banded
  facet, the system shall emit both a **band** key and a **display** key (e.g.
  `cap` + `cap_disp`) and shall not substitute the band on a display surface.
  > *Provenance: NG FR-DRV-006. Rendering an invented band where the vendor
  > publishes a figure is weaker truth, and a band is meaningless to a shopper
  > without its scale.*
- **FR-115** Spec values shall be **finished display strings**; no consumer
  (theme or channel) shall be required to parse, convert, round or format.
  Dual-unit form `0.2–1.0 mm / 0.008–0.04 in`; range separator is **en-dash
  U+2013**. The rendered value shall be byte-identical to the packed value.
  > *Provenance: NG FR-PACK-005.*
- **FR-116** The system shall **not nest one packed field inside another**; a
  static check shall assert no packed value contains another packed field's
  delimiters.
  > *Provenance: NG FR-PACK-004. `spec_docs` uses `= ; |` internally; nesting
  > corrupts both.*
- **FR-117** When new keys are added to a packed field, pack order shall be
  **append-only** for existing keys. Pack order is not render order — render
  order belongs to the consumer.
  > *Provenance: NG FR-PACK-006. Appending leaves every already-correct
  > product's prefix undisturbed.*
- **FR-118** Document and asset references shall be stored **relative or as
  identifiers, never with a hostname**; third-party assets shall be stored as
  an **identifier** (e.g. `ds=58222`), not a URL.
  > *Provenance: NG FR-BC-005/006. ⛔ The same data is served from three
  > hostnames (live, sandbox, store-hash); a stored hostname is correct on
  > exactly one. This already left all live products pointing at a 404 when the
  > warranty file moved. A vendor site reorganisation must be a one-line theme
  > change, not a full reload.*
  > **VERIFY:** the identical stored path returns 200 + correct content-type on
  > at least two hostnames; no absolute third-party URL in any packed field.

### 4.5 Built data store (Stage 4)

- **FR-39 [AMENDED, D-2]** The system shall persist built data in an
  **authoritative SQLite store**, and shall emit on every build a
  **deterministic canonical text export** (stable ordering, stable formatting)
  that is diffable and version-controllable. The export is a **projection**:
  it shall be regenerable from the store at any time, and all diffing
  (FR-42), version control and determinism assertions operate on the export.
  A store whose export cannot be regenerated byte-identically is corrupt and
  shall be reported as such.
- **FR-40** Each build shall record a **manifest**: brand, timestamp, tool
  version, source hashes, overrides applied, vocabulary version, row count, and
  every assertion with its measured value.
- **FR-41 [AMENDED, D-2]** The system shall **rebuild deterministically**:
  identical sources, overrides and configuration produce a **byte-identical
  canonical export**. No wall-clock, random, or iteration-order dependence in
  derived values.
- **FR-42 [AMENDED, D-2]** The system shall **diff two builds** via their
  canonical exports, reporting added, removed and changed rows field by field.
- **FR-43** The system shall support **operator edits to any field of built
  data** through declared override files, and shall never require editing built
  data (or the SQLite store) directly. **No field shall be excluded from
  override.**
- **FR-44** The system shall support **explicitly adding rows** not present in
  any source (products known only from an operator list), with provenance
  recorded as operator-supplied.
- **FR-45** The system shall support **explicitly removing rows** via an
  exclusion list, honoured on **every** subsequent run.
  > *Rationale: without a persistent exclusion list, deleting a product
  > remotely does not stick — the next run finds no match and recreates it.*
- **FR-46** The system shall support **holding rows** from publication with a
  recorded reason, distinct from exclusion, and shall report held rows on every
  build.
- **FR-47** Every row shall carry, per field, the **source that supplied it**
  (source cell, override, or named derivation rule), so any published value is
  traceable without re-running the build.
- **FR-137 [ADDED 2026-08-19, operator]** The system shall **export the
  combined built data set to CSV** for any brand — one row per SKU, one column
  per field, covering canonical, derived and commercial fields together —
  with row, field and subset selection (consistent with FR-75/76). The export
  shall be **spreadsheet-safe**: values written as text (no numeric or date
  coercion on open — leading zeros, EANs and codes survive Excel), UTF-8 with
  BOM, quoted delimiters, and a header row of exact field names.
  > *Purpose: bulk data edits in a spreadsheet — the operator's stated
  > workflow. Distinct from the CSV endpoint adapter (FR-60), which emits
  > payload-shaped files for publication; this is the PIM core's own data in
  > editable form.*
- **FR-138 [ADDED 2026-08-19, operator]** The system shall **import an edited
  CSV** and apply it through change management, not as a blind overwrite: it
  shall compute a **field-level diff** against current built data, report the
  complete change set before applying (FR-74 semantics — producible without
  applying), and record every accepted change as an **operator override**
  (FR-25/26) with basis = the import file, timestamp and row, so every bulk
  edit is **individually reversible** and survives rebuilds from vendor
  sources. Unknown SKUs shall be treated as explicit row additions only when
  flagged (FR-44), otherwise reported and skipped; unknown columns shall
  require explicit confirmation before becoming newly declared fields, never
  silently created. Blast-radius and directional-anomaly checks (FR-80..82)
  apply to imports exactly as to publications.
- **FR-139 [ADDED 2026-08-19, operator]** CSV round-trip shall be **provably
  lossless and self-checking**: an export re-imported unmodified shall
  produce an **empty change set**; and the importer shall detect
  spreadsheet-mangled values — float-ified integers (`7314150103003.0`),
  stripped leading zeros, date-coerced codes, encoding damage — and **report
  them as suspected tool damage rather than accept them as edits**.
  > *Rationale: the profile measured exactly these mutations in the existing
  > dataset (CT-PIM-DATA-001 §4.3); a bulk-edit path that lets Excel corrupt
  > 300 EANs in one import would be the largest single blast radius in the
  > system.*

### 4.6 Field mutability and write authority

> This section replaces v1's hardcoded field exclusions. **Read §0.2 first: it
> is only safe together with §4.9 and §4.10.**

- **FR-48** **Every field the system can represent shall be changeable by the
  operator.** No field shall be permanently unwritable, and no field shall
  require a code change to become writable.
- **FR-49** The set of **managed fields** — those the system writes at an
  endpoint for a given run — shall be **declared data**, editable by the
  operator without a code change, defaulting to **every mapped field**.
  *(Default managed set for a new brand: OQ-7.)*
- **FR-50** No component shall contain a **code-level exclusion** preventing a
  mapped field from being written. Such an exclusion is prohibited outright.
  > *Rationale: `build_body()` popped `price`, `retail_price` and
  > `custom_fields` on update. The MSRP defect was therefore unfixable by the
  > loader, and no configuration change could reach it. §9.3.*
- **FR-51** **Commercial fields — price, MSRP/retail price, sale price, cost,
  currency, availability, price visibility — shall be ordinary managed
  fields**, creatable and updatable by the same mechanism as any other field,
  with no special-case handling anywhere in the system.
- **FR-52** A field **absent from built data shall not be written**. Omission
  is not a write, and shall never be published as an empty or zero value —
  except where an endpoint declares a legacy sentinel default (FR-65).
  > *Rationale: this — not a code-level ban — is what protects operator-set
  > values such as active sale prices, admin-set visibility and inventory. The
  > v1 rule "a load run must never silently override a decision a human made in
  > the admin" is realised here as declared data: fields the operator manages
  > by hand at the endpoint are simply left unmanaged (FR-53, §12 C-2), and
  > drift on them is reported (FR-57), never silently overwritten.*
- **FR-53** The operator shall be able to move a field between **managed and
  unmanaged per run**, by declaration or by command-line selection, without
  editing code.
- **FR-54** **Exactly one component shall own each managed field** for a given
  run. Two components writing one field is prohibited.
- **FR-55** **Every managed field shall have an owner.** A managed field with
  no owner shall be a **build failure**, reported by name — never a silent
  omission.
  > *Rationale: this closes §9.3. MSRP was managed in intent and owned by
  > nobody in fact, and nothing in the system detected that.*
- **FR-56** Field ownership shall be declared in the brand pack, **reported at
  the start of every run** as a field→owner table, and enforced at runtime.
- **FR-57** Where a field is deliberately **unmanaged**, the system shall
  report it as unmanaged on every run **together with the count of rows whose
  built value differs from the endpoint's**. Unmanaged shall never mean
  invisible.

### 4.7 Publication (Stage 5 — the Distribution chain)

- **FR-58** The system shall publish through an **endpoint adapter
  interface**. The core shall contain no endpoint-specific field names, limits
  or semantics.
- **FR-59** The adapter interface shall define at minimum `capabilities()`,
  `snapshot()`, `fetch_existing()`, `create()`, `update()`, `delete()`,
  `verify()`, `restore()`, and declared limits.
- **FR-60** The system shall ship a **BigCommerce adapter** first, and at least
  one **non-API adapter** (e.g. CSV/JSON export) to prove the abstraction
  holds.
- **FR-61** The system shall determine create-vs-update by **querying the
  endpoint for existing identity first**, never by assuming — upsert by SKU:
  GET → update if present, create if absent. Blind creation is prohibited.
  > *Rationale: a create-over-existing regenerates the product and clobbers
  > re-hosted images; an unmatched pre-existing SKU is created as a duplicate.*
- **FR-62** All publication operations shall be **idempotent**: re-running with
  unchanged data produces no change and no duplication (zero creates, zero
  field writes, zero relation writes on an identical second run).
- **FR-63** Sub-resources (custom fields, images, relationships) shall be
  reconciled **by identity, not appended**: match existing, update, create only
  the missing, delete only those the system manages.
  > *Rationale: a BigCommerce custom field sent in a product PUT without an
  > `id` is treated as a NEW ADDITION, not a replacement — every re-run
  > appended a second `filter_metadata` and the storefront read whichever it
  > hit first, silently destroying idempotency. Images posted blindly went
  > 7 → 14. The BC adapter shall therefore strip `custom_fields` from the
  > product body on update, GET live fields, match by name, PUT existing, POST
  > missing, DELETE duplicates.*
- **FR-64** Where a remote resource is re-hosted on write (e.g. images), the
  system shall write a **provenance fingerprint** enabling idempotent
  reconciliation, and shall **never delete a resource it cannot prove it
  owns**.
- **FR-65** The system shall write **explicit empty values** rather than
  skipping a field, where the endpoint declares a legacy sentinel default.
  > *Rationale: ⛔ the live `[-1]` defect. Skipping `related_products` for a
  > family-less product left BigCommerce's V2 "auto-determine" sentinel in
  > place; BC invented the series table on 163 products, and `[-1]` has length
  > 1 so the theme's `{{#if related_products.length}}` gate opens. The theme
  > cannot distinguish an invented relation from a real one — BC resolves
  > `[-1]` into real product objects before Stencil sees them (§12 W-3). This
  > does not conflict with FR-52: an endpoint sentinel is a declared adapter
  > property, and the adapter states which fields need an explicit empty.*
  > **VERIFY:** store-wide count of products returning `[-1]` = 0, quoted
  > against the before-count (FR-101/INV-15).
- **FR-66** The system shall maintain a **ledger**: local identity, remote
  identity, action (created/updated/skipped/excluded/failed), **fields
  written**, per-sub-resource counts, status, detail, and the **before-image**
  of every field written (§4.10).
- **FR-67** The ledger shall be written **incrementally — before and after each
  row's write** — so an interrupted run is both resumable and reversible.
- **FR-68** The system shall support **staged publication** — dry run → limited
  batch → full — and shall **refuse an unstaged full run** (no full run without
  a preceding successful dry run for the same input hash).
- **FR-69** The system shall respect declared **rate limits** and back off on
  throttling responses rather than failing. *(BigCommerce v3 ≈ 450 requests/
  30 s; catalog endpoints cap concurrency; a full run shall complete with zero
  429s.)*
- **FR-70** All writes shall require an **explicit arming flag**; writing to a
  production environment shall require a **second, distinct** flag.
- **FR-71** The system shall treat **partial-success responses** per the
  adapter's declaration (e.g. HTTP 207 is a success for BigCommerce).
- **FR-119** Relationships shall be published in a **second pass**, after all
  products in the batch exist, against a complete id map; no relation write
  shall attempt an unknown SKU, and relationship members shall be restricted to
  SKUs **actually present at the endpoint**.
  > *Provenance: NG FR-REL-004/007. Relations are by product id, which does not
  > exist until pass 1 creates the product. Restricting members to present SKUs
  > is what makes a partial load render correctly and a re-run self-heal stale
  > pointers after a delete.*
- **FR-120** The system shall **measure and report** whether the endpoint
  truncates long relationship lists (write the largest family, read it back,
  report written vs returned counts), and shall not design around an unmeasured
  cap.
  > *Provenance: NG FR-REL-006; open since ADR-TOOL-FAMILY-LINKING — "blocks
  > run to 12+; truncation would be silent." OQ-3.*
- **FR-121** The BigCommerce adapter shall route PDP templates via the
  **dedicated custom field `ct_page_type`**, never `layout_file`, with absence
  meaning the default archetype (fails closed: absent ⇒ equipment).
  > *Provenance: NG FR-BC-004. `layout_file` is Blueprint-only and a no-op on
  > Stencil.*
  > **VERIFY:** 100% of brand products carry the declared value; **control** —
  > a known non-brand SKU returns absent.
- **FR-122** Where a price must be hidden, the BigCommerce adapter shall set
  the documented companion field (`is_price_hidden` requires
  `availability: "disabled"`) and shall surface that this makes the product
  non-purchasable.
  > *Provenance: NG FR-BC-008. The 20 unpriced SKUs load at `$0` + hidden;
  > `$0` alone would have shipped 20 false price tags. Unpriced SKUs shall
  > render call-for-price, never `$0`.*
- **FR-123** The BigCommerce adapter shall **never auto-create categories**:
  every category name shall resolve to an existing category id before any
  write, and a failure to resolve shall halt the run.
  > *Provenance: NG G-CATEGORY. Auto-creation is how the misspelled
  > `Stripperss` twin category was born.*
- **FR-124** Before any write, the system shall **HEAD-check every image URL**
  it intends to publish and report dead ones.
  > *Provenance: NG G-IMAGES — BigCommerce fails image fetches quietly.*

### 4.8 Change management

- **FR-72** The system shall support these modes, each independently invocable:

  | Mode | Effect |
  |---|---|
  | `build` | Stages 1–4. No network. |
  | `diff` | Compare built data against the endpoint or a snapshot; report intended changes. No writes. |
  | `publish --new` | Create rows absent from the endpoint |
  | `publish --update` | Update rows present at the endpoint |
  | `publish --delta` | Publish only rows whose built data changed since a named build |
  | `publish --fields <list>` | Publish only the named fields, across the selected rows |
  | `repair --fields <list>` | Re-write named fields on rows the ledger already marks complete |
  | `remove` | Remove rows via the exclusion list |
  | `verify` | Compare endpoint state against built data |
  | `snapshot` | Capture endpoint state |
  | `rollback <run>` | Reverse a named run from its before-images |
  | `restore <snapshot>` | Restore endpoint state from a snapshot |
  | `export-csv` | Export the combined built data set to CSV for bulk editing (FR-137) |
  | `import-csv` | Diff an edited CSV, report the change set, apply as overrides (FR-138) |

- **FR-73** A **delta publication shall recompute every affected relationship
  set and rewrite all members**, not only the changed rows.
  > *Rationale: relationship lists are per-row and not mirrored by the
  > endpoint. Writing only the new row leaves every existing sibling's list
  > without it — the new product's own page is right while it is missing from
  > all the others. This is the defect the operator reported 2026-08-17.*
  > **VERIFY:** pairwise symmetry — for every pair (A,B), A lists B **and** B
  > lists A; report the pair count; prove the check can fail by breaking one
  > side in a dry run.
- **FR-74** The system shall report, before any write, a **complete
  field-level change set**: creates, updates by field with before and after
  values, removals, and unchanged counts. This report shall be producible
  **without arming**.
- **FR-75** The system shall support **selecting a subset of rows** for any
  operation by explicit list, reporting subset size against total.
- **FR-76** The system shall support **selecting a subset of fields** for any
  operation, so a single field (e.g. MSRP) can be corrected across the whole
  catalogue without touching anything else.
- **FR-77** The system shall provide a **repair mode** that re-writes named
  fields on rows the ledger already marks complete.
  > *Rationale: a ledger-idempotent tool skips rows it believes are done.
  > Without a repair path, a field it failed to write once is unreachable
  > forever. §9.3.*

### 4.9 Validation of changes

- **FR-78** The system shall **validate every payload before any write**:
  type, required-ness, numeric range, string length, vocabulary membership,
  delimiter safety, and referential integrity of every id it references.
- **FR-79** A validation failure shall name the **row, field, rule, and
  offending value**, and shall halt the run **before the first write**, never
  part-way through.
- **FR-80** The system shall compute and report the **blast radius** of every
  change set before writing: rows affected, fields affected, count per field,
  and for numeric fields the magnitude and **direction** of change.
- **FR-81** A change set exceeding a **declared threshold** — proportion of
  rows, proportion of a field's population, or absolute count — shall require
  an **explicit confirmation that names the measured figure**. Arming alone
  shall not satisfy it. *(Starting thresholds: OQ-6.)*
- **FR-82** The system shall flag a **directional anomaly**: a numeric field
  where a large majority of the changes move the same way.
  > *Rationale: the exact signature of the near-miss in §9.13 — 288 prices,
  > all moving down, because built data was one price book behind. Size alone
  > would not have flagged it in a full catalogue load; size plus direction
  > does.*
- **FR-83** A run whose change set is **empty** shall say so explicitly and
  exit without writing, rather than reporting a successful write of nothing.
- **FR-84** The system shall **verify every field it wrote** by reading it
  back from the endpoint and comparing against intent.
- **FR-85** Verification shall report **expected versus observed per field**,
  name every mismatched row, state **how many of how many fields were
  verified**, and exit non-zero on any mismatch.
- **FR-86** Verification shall **not rely on the write operation's own success
  report**.
  > *Rationale: a full catalogue load reported `updated=346 failed=0` while
  > writing none of the intended price fields, because the adapter's update
  > policy excluded them.*
- **FR-87** Every check shall be **provably falsifiable**: the system shall
  provide a mechanism to corrupt an input and demonstrate the check reports
  it, and that demonstration shall be part of the test suite.
- **FR-125** Every verification shall include a **control that would fail if
  the instrument were broken**, executed in the same run, and every acceptance
  report shall name its control and show the observed positive.
  **Corollary:** a retirement check asserting 0 rows cannot carry a same-query
  control — once the rows are gone there is nothing present to prove the call
  worked. Such checks require a **separate positive probe**.
  > *Provenance: NG FR-GATE-001; INV-16.*
- **FR-126** Any assertion of the form "N defects remain" shall report
  **before and after counts** — a zero that was never non-zero proves nothing.
  > *Provenance: NG FR-GATE-002; INV-15.*
- **FR-127** For the BigCommerce endpoint, acceptance shall be measured on the
  **rendered storefront**, not only on the API payload: assert `data-*`
  attribute presence on a rendered card and a non-zero decoded image count.
  > *Provenance: NG FR-GATE-005. Handlebars `{{#each}}` over an undefined
  > `custom_fields` is a no-op, and BC has an open unresolved report of
  > `custom_fields` going undefined even in the documented PDP context
  > (stencil-cli#1229). A passing filter over zero attributes looks fine.*
- **FR-128** Any HTTP probe used for verification shall send a
  browser-equivalent **`Accept-Language` header**, and the probe harness shall
  record that the same URL returns 200 with the header where applicable.
  > *Provenance: NG FR-GATE-006, measured 2026-07-30 — `stencil-cli`
  > dereferences that header without a guard (`renderer.module.js:347`) and
  > returns an opaque 500 to any client omitting it. `curl` omits it by
  > default; browsers never do. A perfectly healthy server looked dead to two
  > sessions for hours.*

### 4.10 Backup, rollback and restore

- **FR-88** The system shall take a **complete snapshot of remote state before
  any write**, automatically — not as a separate operator step.
- **FR-89** A snapshot shall capture **every field and sub-resource the system
  can write**, plus remote identities, and shall be self-describing (brand,
  environment, timestamp, counts, tool version).
- **FR-90** A snapshot shall include a **control assertion** — a known-present
  record — and shall **fail rather than write a partial snapshot** if absent.
  > *Rationale: an empty or filtered pull must read as a failure, never as
  > "zero records".*
- **FR-91** The system shall **refuse to write** when a pre-write snapshot
  cannot be taken.
- **FR-92** The system shall capture a **per-row before-image at write time** —
  the endpoint's current value of every field about to be written — and record
  it in the ledger **before** issuing the write.
  > *Rationale: a bulk snapshot taken at run start can be minutes stale and
  > does not cover rows created mid-run. The before-image makes each
  > individual write reversible on its own terms, which is what makes FR-93
  > exact rather than approximate.*
- **FR-93** The system shall **roll back a named run** from its before-images,
  restoring every field that run wrote and **no other field**.
- **FR-94** Rollback shall be available for an **interrupted or partially
  completed** run, covering exactly the rows the ledger records as written.
- **FR-95 [RESOLVED, D-3]** On **verification failure**, the system shall
  **halt further writes immediately**, report which rows are affected, and
  **present the rollback field-level diff for explicit operator approval**. It
  shall not roll back automatically. *(The per-invocation policy flag of the
  source spec is dropped; halt-and-wait is the single behaviour.)*
- **FR-96** Rollback shall report a **field-level diff before executing**, and
  shall be refusable by the operator at that point.
- **FR-97** Rollback shall be **verified by the same mechanism as publication**
  (FR-84..86). An unverified rollback is not a completed rollback.
- **FR-98** The system shall support **restoring from any retained snapshot**,
  wholly or for a named subset of rows or fields.
- **FR-99** Snapshots and ledgers shall be retained per a declared policy,
  indexed by run, and **never overwritten implicitly**. *(Retention policy:
  OQ-9.)*
- **FR-129** Every run shall have a documented rollback **written before the
  full run is armed** (the rollback handle and procedure are part of the
  pre-flight gate set).
  > *Provenance: NG G-ROLLBACK.*

### 4.11 Reporting and observability

- **FR-100** Every run shall produce a **durable, timestamped report**
  containing the field→owner table, the change set, every assertion with its
  measured value, the verification result, and the **rollback handle** for
  that run.
- **FR-101** Every assertion shall report a **measured number**, never only a
  verdict.
  > *Rationale: "a check that can only ever say 'all clear' is not a check."*
- **FR-102** Long operations shall report **progress with counts and ETA**,
  and report failures as they occur, not only in a summary. Every failure
  message shall name the SKU, field, observed value and expected condition.
- **FR-103** The system shall never print credentials, tokens, or environment
  identifiers to logs, reports or documents.
- **FR-130** The system shall log every applied design/operator ruling with a
  status and **evidence for that ruling alone** (`VERIFIED` requires evidence
  for that clause alone; anything else stays `BUILT`), and a scan shall report
  directives not yet logged.
  > *Provenance: NG FR-OPS-005 — the existing `RULING-LEDGER.md` practice. It
  > works; keep it.*

### 4.12 Truth

- **FR-131** The system shall not invent, infer or guess a product claim.
  Where the vendor is silent, it shall omit. Corollary already in force:
  **`esd=no` means "not stated", never "not ESD safe"** — ESD status comes
  from the vendor's declared field, never inferred from measurements such as
  resistivity. Every emitted claim shall trace to a source cell, an override,
  or a named derivation rule (FR-47).
- **FR-132** Where two vendor values are **arithmetically derivable** from one
  another (transposed, copied, decimal-shifted), the system shall correct via
  a **logged, reversible** override (FR-25/26) recording SKU · field · before
  · after · derivation. Where they **contradict** and arithmetic cannot
  resolve them, it shall emit the metric value alone and shall not guess the
  other.
  > *Rationale: measured across 878 dual-unit numbers: 50 disagree, 9 provably
  > wrong. "Two numbers that provably contradict cost more than one imprecise
  > number — a shopper who catches `0.8 mm / 0.07 in` stops trusting every
  > figure on the page, including the right ones."*
- **FR-133** The system shall not silently rewrite vendor titles or claims;
  suspected vendor errors shall be reported per run for routing to the vendor.
  > *Rationale: six wrong vendor titles were routed, not rewritten.*
- **FR-134** Authority for **what is true** rests with the operator, not the
  system and not any design agent. Truth questions are surfaced for decision,
  never auto-resolved.
  > *Operator, 2026-08-17: "let me worry about affirming what is or is not
  > correct… you put in what I say."*

---

## 5. Non-functional requirements

- **NFR-1 Determinism.** Identical inputs produce a byte-identical canonical
  export (D-2). No wall-clock, random, or iteration-order dependence in
  derived values.
- **NFR-2 Auditability.** Every published value traceable to a source cell, an
  override, or a named derivation rule.
- **NFR-3 Fail-closed on ambiguity.** Ambiguity halts. Absence of a signal
  selects the safe default. No silent coercion, truncation, or tiebreak.
  **This governs uncertainty, not permission** — it shall never be implemented
  as a restriction on which fields may be changed (P2, FR-48).
- **NFR-4 Idempotence.** Every operation safe to re-run.
- **NFR-5 Resumability.** Any interrupted operation resumable without
  duplication (kill a run mid-flight; resume completes without duplicating
  work).
- **NFR-6 Reversibility.** Every run individually reversible from its own
  before-images, without depending on a bulk snapshot and without disturbing
  any other run.
- **NFR-7 Mutability.** No field permanently unwritable; no field requiring a
  code change to become writable.
- **NFR-8 Isolation.** Brand packs cannot affect one another.
- **NFR-9 Portability.** Core has no endpoint dependency; adding an endpoint
  requires no core change.
- **NFR-10 Performance.** 1,000 rows built in under 60 s on a developer
  machine; a full brand load (~300 SKUs) completes within one operator
  sitting, unattended after start; publication bounded by endpoint rate
  limits, not local processing.
- **NFR-11 Operability.** One CLI, consistent verbs, dry-run default. Runs on
  the operator's Windows workstation; no server dependency.
- **NFR-12 Testability.** Every gate and derivation rule unit-testable without
  network access and with no vendor files present (canonical fixtures), with
  fixtures for each failure in §9.
- **NFR-13 Stack.** Implementation stack chosen and justified in
  `CT-PIM-ARCH-001` (D-4).
- **NFR-14 Secrets.** Secrets supplied at run time; never stored in the
  working folder; never printed (FR-103).
- **NFR-15 Endpoint API version.** The BigCommerce adapter targets **Catalog
  v3**; any v2 dependency (e.g. the `related_products` sentinel semantics) is
  documented explicitly in the adapter.

---

## 6. Data model

### 6.1 Canonical row — required structure

> **The canonical field set is OPEN (D-6).** The groups below are **roles**,
> not a schema: they say what kinds of fields a row can carry, never which
> fields exist. The actual field list — its names, types, formats, units and
> count — is defined entirely by each brand pack's `fields.yaml` and
> `derive.yaml`. Code declares **no** field name (FR-1); a brand with 30
> fields and a brand with 300 use the same code. The store persists fields as
> open key–value rows per SKU, so adding a field to a brand is a pack edit,
> never a schema migration.

| Group | Fields |
|---|---|
| Identity | local key, vendor code, endpoint SKU, remote id (from ledger) |
| Classification | category path (L1..Ln), chapter, grouping/block, family membership |
| Commercial | list price, MSRP, sale price, cost, currency, availability, price visibility, hold state |
| Physical | weight, dimensions, with declared unit and source |
| Descriptive | name, description, meta description |
| Media | ordered image references with provenance |
| Derived | facets, packed display strings, SEO strings, template-routing value |
| Provenance | per-field source identifier |
| Lifecycle | first-built, last-changed, publish state |

**Every group is writable. No group is special-cased** — the Commercial row in
particular carries no privileged handling anywhere in the system (FR-51).

### 6.2 Brand pack — required contents

```
brands/<brand>/
  brand.yaml            identity, SKU rule, environments
  sources.yaml          N source declarations
  joins.yaml            key functions, association tables
  normalize.yaml        the brand's normalization function, declared: key
                        handling, encoding expectations, decimal and unit
                        conventions, per-column cleanup (small brands may
                        fold this into fields.yaml)
  fields.yaml           source → canonical mapping (incl. alias chains, units)
  derive.yaml           facets, bands, packing, SEO, families, page-type value
  vocabulary.json       frozen facet vocabulary (versioned)
  expectations.yaml     asserted counts and shapes
  managed.yaml          managed-field set + field→owner map (§4.6)
  thresholds.yaml       blast-radius thresholds per field (§4.9)
  endpoints.yaml        adapter bindings (incl. sentinel-empty fields, limits)
  overrides/            operator corrections, each with basis
  exclusions.csv        rows never to publish
```

**No code in a brand pack.** If a brand needs behaviour the declarations
cannot express, that is a **core feature request**, not a per-brand script.

### 6.3 Field mapping is data

- **FR-104** The mapping from canonical fields to endpoint fields shall live
  in a **declaration the operator can read and change** without code changes.
- **FR-105** A field shall be published **only when explicitly confirmed** in
  the mapping; the operator confirms a field by editing the mapping — never by
  editing code.
  > *Rationale: the operator's standing rule — "CONFIRMED = Y → load the
  > field; blank → leave it blank." This is a per-field switch under operator
  > control, which is the opposite of a code-level exclusion (FR-50): the
  > operator can always flip it.*

---

## 7. Operating model

### 7.1 Standard sequence

```
1. build                     # no network
2. snapshot                  # capture remote state
3. diff                      # what would change, field by field
4. validate                  # payload + blast radius; confirm if over threshold
5. publish --dry-run
6. publish --limit N         # staged batch; before-image recorded per row
7. verify                    # the batch — halt on mismatch, offer rollback (D-3)
8. publish                   # remainder
9. verify                    # everything
   rollback <run>            # available at any point from step 6 onward
```

- **FR-106** The system shall enforce this ordering: it shall refuse a full
  publication without a prior staged batch and its verification, and shall
  refuse any publication whose change set has not been validated (FR-78..82).

### 7.2 Write authority

Specified in **§4.6**; summarised here because it is the rule most often
broken in practice:

- One owner per managed field (**FR-54**) — so no two components fight.
- Every managed field has an owner (**FR-55**) — so nothing falls in the gap.
- No code-level exclusion (**FR-50**) — so the operator can always reach a field.

Together: **full coverage under single authority.** v1 had neither — two
components, one field owned by neither, and a code-level ban on reaching it.

### 7.3 What flexibility does *not* mean

Flexibility is about **permission**, not about **rigour**. The following still
halt a run, and are not restrictions on what may be changed:

| Still halts | Why it is not a restriction |
|---|---|
| Unknown facet value (FR-30) | The operator adds it to the vocabulary and re-runs (FR-31) |
| Delimiter inside a packed value (FR-33) | The operator changes the value; no value is banned, one *character* is |
| Over-length field without a declared overflow (FR-34) | The endpoint rejects it anyway; halting names the field instead of 422 |
| Primary/alias disagreement (FR-20) | The operator rules on it via an override (FR-25) |
| Blast radius over threshold (FR-81) | Confirming proceeds; it asks, it does not refuse |
| Managed field with no owner (FR-55) | Declaring the owner proceeds |
| Unresolvable category name (FR-123) | The operator creates/corrects the category at the endpoint |
| Missing filtering-key value (FR-113) | The operator supplies the value or descopes the facet |

Every one of these is resolvable by the operator through **data**, with no
code change. That is the test for whether a halt is legitimate: *can the
operator clear it by editing the brand pack or an override?* If not, it
violates FR-48.

### 7.4 Pre-flight gates (consolidated)

All gates run before any write and halt on failure. Each shall be demonstrated
failing on a synthetic violation (FR-87, AC-17).

| Gate | Assertion | Baseline requirement |
|---|---|---|
| **G-PACK** | brand pack schema-valid before any file read | FR-4 |
| **G-VOCAB** | every packed facet value ∈ frozen vocabulary | FR-30 |
| **G-COMPLETE** | every declared facet key present per chapter; filtering keys never blank | FR-112, FR-113 |
| **G-DELIM** | no delimiter inside any packed value; no nested packed fields | FR-33, FR-116 |
| **G-LIMITS** | declared length limits (BC: name ≤250 · custom-field value ≤250 · image_url ≤255 · ≤1000 images/product · required-on-create present) | FR-34, FR-78 |
| **G-EXISTING** | all target SKUs queried at the endpoint first; pre-existing matches reported with ids | FR-61 |
| **G-CATEGORY** | every category name resolves to an existing id; never auto-create | FR-123 |
| **G-IMAGES** | HEAD-check every image URL; report dead ones | FR-124 |
| **G-SNAPSHOT** | pre-write snapshot taken, with control assertion | FR-88..91 |
| **G-ROLLBACK** | rollback procedure/handle written before the full run | FR-129 |
| **G-STAGED** | no full run without a preceding successful dry run for the same input hash | FR-68, FR-106 |

---

## 8. Acceptance criteria

- **AC-1** Two brand packs with different source counts, join strategies and
  facet rules both build and publish with no code difference.
- **AC-2** A brand with 3 sources and a brand with 9 sources both build.
- **AC-3 [AMENDED, D-2]** Rebuilding unchanged inputs produces a
  byte-identical **canonical export**.
- **AC-4** Publishing twice produces zero changes on the second run, with no
  duplicated sub-resources (custom-field count per product unchanged, zero
  duplicate names).
- **AC-5** **Any field can be changed end to end.** For each of price, MSRP,
  sale price, weight, description, a facet and a relationship list: change the
  value in built data, publish, and verify the endpoint reflects it — **with
  no code change between cases**.
- **AC-6** A managed field declared with **no owner fails the build**, naming
  the field.
- **AC-7** Repair mode re-writes a named field on rows the ledger already
  marks complete.
- **AC-8** A single field can be published across the whole catalogue via
  `--fields`, leaving every other field byte-identical, verified against a
  snapshot.
- **AC-9** Adding one product and re-publishing updates **every** member of
  that product's family, verified symmetric in both directions (pairwise: A
  lists B and B lists A, with the pair count reported).
- **AC-10** Removing a product via the exclusion list keeps it removed across
  three subsequent runs.
- **AC-11** A completed run can be **rolled back from its before-images**,
  restoring exactly the fields it wrote and leaving every other field
  untouched, verified field by field.
- **AC-12** An **interrupted** run can be rolled back, covering exactly the
  rows the ledger records as written.
- **AC-13** A verification failure **halts further writes** and presents the
  rollback diff for operator approval (D-3).
- **AC-14** A change set exceeding a declared threshold **cannot be written**
  without an explicit confirmation naming the measured figure — arming alone
  is refused.
- **AC-15** A **directional anomaly** is flagged: a fixture in which N numeric
  values all move the same way is reported before any write. *(This fixture is
  the §9.13 near-miss: rebuild it and prove the system stops.)*
- **AC-16** A snapshot taken before a write restores the endpoint to its prior
  state, verified field by field.
- **AC-17** Every gate in §7.4 is demonstrated **red** by a fixture that
  violates it, and green when it does not.
- **AC-18** Verification detects a value written to built data but not
  published — i.e. it does not trust the publication report.
- **AC-19** A second endpoint adapter publishes the same built data with no
  core modification.
- **AC-20** Corrupting one source cell causes a specific, named assertion to
  fail rather than a silent wrong value.
- **AC-21** The system refuses to publish when a pre-write snapshot fails.
- **AC-22** Every failure in §9 has a regression test.
- **AC-23** A synthetic second brand added **by configuration alone** loads
  end-to-end with **zero diffs to core modules** (the FR-1 generalisation
  proof).
- **AC-24** Store-wide count of products whose `related_products` returns
  `[-1]` is **0**, quoted against the recorded before-count (FR-65, FR-126).
- **AC-25** For the BigCommerce endpoint: a rendered category card carries the
  expected `data-*` attributes and a non-zero decoded image count (FR-127),
  and all HTTP probes send `Accept-Language` (FR-128).
- **AC-26** Hiding a product in the endpoint admin, leaving `is_visible`
  unmanaged, and re-running publication leaves the product hidden — and the
  run reports the drift count (FR-52/FR-57, §12 C-2).
- **AC-27** A vendor column rename produces a loud config-validation failure,
  not a silent re-derivation (P3, FR-111/FR-4).
- **AC-28** The relation-list truncation measurement runs and reports written
  vs returned counts for the largest family (FR-120).
- **AC-29** **CSV round-trip is lossless:** export a brand's combined data set,
  re-import it unmodified, and the resulting change set is **empty** — proven
  on a fixture containing a leading-zero code, a 13-digit EAN, a value with an
  embedded comma, a value with an embedded quote, a dual-unit string with an
  en-dash, and a trademark symbol (FR-137/139).
- **AC-30** **Bulk edit is reversible:** change 50 values across 3 fields in an
  exported CSV, import, confirm the reported change set matches exactly those
  50, publish, then remove the import's overrides — built data returns to its
  pre-import state field for field (FR-138, FR-26).
- **AC-31** **Spreadsheet damage is caught, not applied:** an import whose EAN
  column arrives float-ified and whose zero-padded codes lost their leading
  zeros is **reported as suspected tool damage and refused**, naming the rows
  and columns — it does not enter built data as edits (FR-139).
- **AC-32** An import introducing an **unknown column** is refused pending
  explicit confirmation, and one containing **unknown SKUs** reports them and
  skips them unless row-addition is flagged (FR-138, FR-44).

---

## 9. Invariants — failures that actually occurred

**Each of these was live, and most were invisible to a passing build.** Every
one has a regression test (AC-22).

### 9.1 A green check that cannot fail
A verification routine passed for weeks while checking 7 hardcoded SKUs,
asserting nothing, and returning exit 0 unconditionally.
- **INV-1** Every check shall be demonstrated to fail on corrupted input
  before its passing result is trusted.

### 9.2 A check that does not look at the field it protects
A price run wrote `price` and never `retail_price`. Its verification checked
`price` only. It reported **286/286 clean, twice**, while 309 MSRPs were stale
for two weeks.
- **INV-2** Verification shall assert **every field the operation writes**.
- **INV-3** Coverage shall be stated in the output: *"verified N of M fields."*

### 9.3 A field owned by nobody, and unreachable by design
The product loader **refused in code** to write price fields — a deliberate
"never clobber a manual price" safeguard. The price tool owned prices but
wrote only two of the three price fields. **MSRP was managed in intent and
owned by nobody in fact.** Neither tool could fix it; a full catalogue load
reported `updated=346 failed=0` having written none of it; and the price
tool's ledger idempotence then made the field unreachable on re-run.
- **INV-4** One owner per managed field, **and every managed field has an
  owner**. A managed field with no owner is a build failure.
- **INV-5** **A safeguard that makes a field permanently unwritable is a
  defect, not a safety feature.** Protection comes from diff-before-write,
  blast-radius confirmation, post-write verification and rollback — never
  from prohibition.
- **INV-6** A ledger-idempotent tool must have a **repair path**, or a field
  it failed to write once is unreachable forever.

### 9.4 Sentinel defaults
Skipping a relationship list for family-less products left BigCommerce's V2
`[-1]` "auto-determine" default. The storefront rendered invented
relationships on **163 products** — a jewellery kit listing diagonal cutters
as "in this series". The v1 code's own comment predicted exactly this; a
`if not linked and not had: continue` guard meant `[]` was never sent.
- **INV-7** Write explicit empties. "Nothing to write" is not "write nothing".

### 9.5 Asymmetric relationships
Relationship lists are per-row and not mirrored. A delta wrote the new
product's list; its existing siblings never gained it.
- **INV-8** Recompute and rewrite **every member** of an affected set.

### 9.6 Identity by name
A vendor site search substring-matched `8211` inside `RX8211` and returned a
different tool with full specs. Separately, `15AGWM` and `TL 15A-GW` are one
product under two codes, while `HS7291` and `7291` are two different products
(140.3 mm / 103 g versus 108 mm / 50 g) that a prefix join would merge.
- **INV-9** Identity by declared code association only. Never by name,
  substring, or prefix.
- **INV-10** A near-match is a **reportable gap**, never a substitution.

### 9.7 Silent truncation and sanitising
A packed field over the endpoint limit hard-errors; a truncated one loses
whole values and still looks successful. A delimiter inside a value corrupts
every subsequent key.
- **INV-11** Halt, never truncate. Halt, never escape. (Declared pack-order
  overflow split is the only over-length path, FR-34.)

### 9.8 Stale mirrors
Three of five specification documents differed from their originals by hash.
The inbound coordination channel was **18 days stale**, causing a resolved
defect to be re-reported as open.
- **INV-12** Any mirrored artefact shall be hash-verified before it is read
  as authoritative.

### 9.9 Source data that disagrees with itself
The vendor's mm and inch cells contradicted on 50 pairs. A weight column read
6 g where the vendor's own site said 50 g. Two products carried 0.09 g against
peers at 50 g.
- **INV-13** Cross-check independent sources where both exist; report
  disagreement, never resolve it silently.
- **INV-14** Plausibility bounds per field type, with violations reported.

### 9.10 Counts that prove nothing
"0 mismatches" was reported by a query that returned 0 rows.
- **INV-15** Report before and after together. A zero that was never non-zero
  proves nothing.
- **INV-16** Every store-wide query shall carry a control assertion that fails
  when the query itself is wrong.

### 9.11 Derived data with no source
24 products loaded with an empty grouping field; the storefront's series table
then grouped them arbitrarily.
- **INV-17** A field consumed by a downstream renderer shall be declared
  **required**, and its absence shall be a build failure — not an empty value.

### 9.12 Local resources deleted by unrelated updates
A manually uploaded image had no source URL, so it never appeared in the
desired set; an unrelated field update classified it stale and deleted it.
- **INV-18** Never delete a remote resource that cannot be proven
  system-owned and superseded.

### 9.13 Stale built data silently reverting a live change (near miss)
The August price increase was applied directly to the store; built data was
never updated. Built data therefore disagreed with live on **288 of 346
products — every one of them low**. An unrestricted full apply would have
reverted the increase and reported `updated=288 failed=0` as a clean success.
It was caught by a field-level diff against a saved snapshot, before any
write. This is the failure v1's code-level price ban was really guarding
against — and it guarded against it by making the field permanently
unreachable, which then caused §9.3. **The correct guard is detection and
reversal, not prohibition.**
- **INV-19** Every run shall show its **complete field-level change set before
  writing**, and that report shall be producible without arming.
- **INV-20** A change set of unusual **size or direction** shall require an
  explicit confirmation naming the measured figure.
- **INV-21** Built data shall be treated as **capable of being behind the
  endpoint**. The system shall never assume built data is authoritative simply
  because it was built more recently than it was published.

---

## 10. Migration from v1

- **FR-107** The system shall produce a Lindström brand pack reproducing the
  current live catalogue, and its built data shall be diffed against live with
  **zero unintended changes** before cutover.
- **FR-108** The existing ledger and exclusion list shall be importable, so
  remote identities and deletions are preserved.
- **FR-109** v1 and v2 shall be runnable side by side against the same
  endpoint until v2's output is verified equivalent.
- **FR-110** The v1 code-level field exclusions shall be migrated to
  **declared managed-field data**, and the migration shall be demonstrated by
  **changing MSRP through the normal publish path and rolling it back** — the
  operations v1 could perform in neither direction.
- **FR-135** Migration shall **inherit** operator-directed remote fixes rather
  than re-derive them — specifically the `[-1]` relationship fix directed
  2026-08-17 (11 in-scope + 152 released). The Lindström pack's built data
  shall reproduce the fixed state (OQ-2 confirms scope).
- **FR-136** The Lindström pack's spec-key set shall be taken from the
  **shipped state (16 keys, including `tt bh bw`)**, not from any earlier
  document.
  > *Provenance: NG §A.2 — the three appended keys reached two documents and
  > not the loader spec, runbook or PIM spec; a loader following the old line
  > re-emits 13 and 107/103 products keep the empty rows the ruling existed to
  > fill, with every check passing. Found by an independent reviewer. This is
  > why FR-2 demands one declarative source per brand.*

---

## 11. Decisions and open questions

### 11.1 Resolved at baseline (2026-08-19)

See §0.1 (D-1..D-5). Additionally resolved by merger:

- **Facet manifest file** — rejected; per-SKU facet data lives on the product
  (§12 W-1).
- **Discrete custom fields per spec row** — rejected; packed fields (§12 W-2).
- **Theme-side workaround for bad relation data** — rejected; data contract
  only (§12 W-3).
- **`price` as a rail facet** — killed by operator 2026-07-21; data retained,
  facet config-hidden (§12 W-5).

### 11.2 Open questions for the operator (OQ)

| ID | Question | Source |
|---|---|---|
| **OQ-1** | **Live catalogue count discrepancy:** NG records **292 Lindström SKUs live** (v1.21.0); Multi-Brand records **346 products loaded**. Which figure is current, and what accounts for the difference (excluded/held/deleted rows)? Migration (FR-107) needs the authoritative number. | Baseline merge finding |
| **OQ-2** | The pre-existing `[-1]` products (11 in-scope + 152 released): confirm the new system **inherits** the fixed state rather than re-deriving it (FR-135). | NG OQ-2 |
| **OQ-3** | Relation-list cap: unmeasured since the ADR. FR-120 measures it — schedule the measurement before the first large-family publish. | NG OQ-1 |
| **OQ-4** | `esd_safe` → `filter_metadata.esd` fold (5 fields → 4), gated on the theme repointing the badge. Which shape does the Lindström pack build against? | NG OQ-3 |
| **OQ-5** | 118 products missing specs that exist in the vendor sheet (unmapped columns) — the new column map should close it. Confirm the target list. | NG OQ-4 |
| **OQ-6** | Blast-radius thresholds (FR-81): starting proposal — any field changing on more than 25% of rows, **or** more than 80% of a field's changes moving the same direction. Both would have caught §9.13. Confirm or adjust. | MB OQ-4 |
| **OQ-7** | Default managed set for a new brand (FR-49): every mapped field (matches your direction) or a conservative core with the rest opt-in? | MB OQ-5 |
| **OQ-8** | Which brands follow Lindström, roughly how many SKUs and sources each, and does the next line need a new `ct_page_type` archetype or reuse `tool`? | MB OQ-1 + NG OQ-5 |
| **OQ-9** | Retention (FR-99): how long are snapshots and per-run ledgers kept, and where? | MB OQ-9 |
| **OQ-10** | Sale pricing: should the system *compute* the sale programme from a rule, or only preserve and publish values you set? | MB OQ-6 |
| **OQ-11** | Multi-brand concurrency: must brands publish independently to the same store simultaneously, or is serial acceptable? | MB OQ-7 |
| **OQ-12** | Override authoring: direct file edits, or a review-workbook round trip (as used for price review)? | MB OQ-8 |
| **OQ-13** | Quote-only products: absence of a price inferred, or always an explicit operator declaration? | MB OQ-10 |
| **OQ-14** | Verification depth (FR-84): field-level read-back on every published row, or sampling with full-coverage-on-demand at scale? | MB OQ-11 |
| **OQ-15** | Second endpoint: is a real second channel in view, or is the abstraction insurance? A real one should be built now; insurance is the CSV adapter (FR-60). | MB OQ-2 |

---

## 12. Conflict-resolution log (baselining record)

How the two source specs were reconciled. `MB` = Multi-Brand v1.1;
`NG` = CT-LOADER-NG-SRS-001.

| # | Topic | NG position | MB position | Baseline resolution |
|---|---|---|---|---|
| **C-1** | Built-data persistence | (silent) | FR-39: diffable text-based format | **D-2:** SQLite authoritative + deterministic canonical text export; diffs/determinism on the export. Operator decision 2026-08-19. |
| **C-2** | Protected admin fields | FR-BC-003: never modify `is_visible`/inventory; price per declared policy | FR-48/50/51: nothing unwritable, price ordinary | **MB wins on mechanism, NG's intent preserved as data:** no code-level exclusion anywhere; `is_visible` and inventory default to **unmanaged** in the Lindström pack (FR-52/53/57), so admin decisions are never silently overwritten but remain reachable by declaration. AC-26 proves it. |
| **C-3** | Over-length packed values | FR-PACK-003: split into overflow field by pack order | FR-34: halt, never truncate | **Merged (FR-34 amended):** halt is the general rule; split applies only where the brand pack declares an overflow field; truncation prohibited always. |
| **C-4** | Verification-failure behaviour | (halt implied) | FR-95: rollback or halt per declared policy | **D-3:** halt-and-wait, single behaviour; operator decision 2026-08-19. |
| **C-5** | Empty vs omitted values | FR-GEN-004: omit, never default | FR-65: explicit empties for sentinel fields | **Both, by layer:** omission at build/derive (FR-35, FR-52); explicit empties only where the adapter declares an endpoint sentinel (FR-65). Already reconciled inside MB. |
| **C-6** | Environment default | NFR-007: default sandbox (S) | FR-5: never default production; FR-70: arming flags | **MB form kept, NG intent absorbed:** explicit named environment required, never defaulting to production; live requires a second distinct flag. |
| **C-7** | Requirement numbering | FR-XXX-nnn mnemonic IDs | FR-n serial | MB serials kept (FR-1..110); NG uniques renumbered FR-111..136; full map in §13. |
| **C-8** | Priorities (M/S/C/W) | Carried per requirement | Not used | Dropped as a field; W-items carried as explicit exclusions below; everything else in this baseline is binding. |
| **C-9** | Live product count | 292 live | 346 loaded | **Unresolved — escalated as OQ-1.** Not silently picked (INV-13). |
| **C-10** | Rendered-storefront acceptance, Accept-Language probe, category/image gates, `ct_page_type`, price-hidden companion, relation second pass/cap, truth section, ruling ledger | Present | Absent | Carried into baseline as FR-119..134 — endpoint-adapter and process requirements, no conflict. |

**Exclusions carried forward (recorded so they are not re-proposed):**

| | Why excluded |
|---|---|
| **W-1** a separate facet manifest file | Operator decision 2026-07-11: per-SKU facet data lives **on the product**. One source of truth, no client-side JSON join. |
| **W-2** discrete custom fields per spec row | Ruled 2026-07-22, proven on product 4272: 16 fields → 4. The 13 discrete fields were built around a theme limit **that does not exist**. |
| **W-3** a theme-side workaround for bad relation data | Ruled 2026-08-17: the template cannot distinguish an invented relation from a real one — BC resolves `[-1]` into real product objects before Stencil sees them. **Data contract only.** |
| **W-4** `tip_material` / `length` as facet keys | Not emitted; specifying against them yields an empty render, not an error. |
| **W-5** `price` as a rail facet | Operator killed it 2026-07-21. Data retained, facet config-hidden. |
| **W-6** auto-creating BC categories | How the misspelled `Stripperss` twin was born (FR-123). |
| **W-7** truncating any packed value | Split by pack order where declared, **never** truncate (FR-34). |

---

## 13. Traceability

### 13.1 NG requirement → baseline requirement

| NG ID | Baseline | NG ID | Baseline |
|---|---|---|---|
| FR-GEN-001 | FR-1, AC-23 | FR-PACK-001 | FR-32 |
| FR-GEN-002 | FR-2 | FR-PACK-002 | FR-33 |
| FR-GEN-003 | Definitions (canonical field), FR-27, NFR-12 | FR-PACK-003 | FR-34 [amended] |
| FR-GEN-004 | FR-35 | FR-PACK-004 | FR-116 |
| FR-GEN-005 | P3, FR-4, AC-27 | FR-PACK-005 | FR-115 |
| FR-GEN-006 | FR-3 | FR-PACK-006 | FR-117 |
| FR-ING-001 | FR-6, FR-14 | FR-REL-001 | FR-36 |
| FR-ING-002 | FR-18 | FR-REL-002 | FR-65, AC-24 |
| FR-ING-003 | FR-20 | FR-REL-003 | FR-73, AC-9 |
| FR-ING-004 | FR-21 | FR-REL-004 | FR-119 |
| FR-ING-005 | FR-111 | FR-REL-005 | FR-37 |
| FR-ING-006 | FR-24 [amended] | FR-REL-006 | FR-120, AC-28 |
| FR-ING-007 | FR-45, AC-10 | FR-REL-007 | FR-119 |
| FR-DRV-001 | FR-27, FR-32 | FR-GATE-001 | FR-125 |
| FR-DRV-002 | FR-30 | FR-GATE-002 | FR-126 |
| FR-DRV-003 | FR-112 | FR-GATE-003 | §7.4 gate table |
| FR-DRV-004 | FR-113 | FR-GATE-004 | FR-68, FR-106 |
| FR-DRV-005 | FR-28 | FR-GATE-005 | FR-127, AC-25 |
| FR-DRV-006 | FR-114 | FR-GATE-006 | FR-128 |
| FR-BC-001 | FR-61 | FR-TRUTH-001 | FR-131 |
| FR-BC-002 | FR-63 | FR-TRUTH-002 | FR-132 |
| FR-BC-003 | §12 C-2 (FR-52/53/57, AC-26) | FR-TRUTH-003 | FR-133 |
| FR-BC-004 | FR-121 | FR-TRUTH-004 | FR-134 |
| FR-BC-005 | FR-118 | FR-OPS-001 | FR-66/67 |
| FR-BC-006 | FR-118 | FR-OPS-002 | FR-62, AC-4 |
| FR-BC-007 | FR-69, FR-71 | FR-OPS-003 | FR-19, FR-47 |
| FR-BC-008 | FR-122 | FR-OPS-004 | FR-93..97, FR-129 |
| NFR-001..007 | NFR-10/11/14/15, NFR-12, FR-102, C-6 | FR-OPS-005 | FR-130 |
| §12 W-001..007 | §12 W-1..7 | §13 open questions | §11.2 OQ-1..5, OQ-8 |
| Appendix A | Appendix A (below) | | |

### 13.2 MB requirements

FR-1..FR-110, NFR-1..12, INV-1..21, AC-1..22 are carried with original
numbering; amendments marked in place (FR-24, FR-34, FR-39, FR-41, FR-42,
FR-95, AC-3, AC-13, NFR-1, NFR-10, NFR-11, NFR-12). MB §11 open questions map
to §11.2 (OQ-6..15); MB OQ-3 resolved by D-3.

### 13.3 Ground truth outranking this document

The **shipped theme** and the v1 `pipeline/build_library.py :: FACET_KEYS +
facets_for()` for facet key names (§3.2).

---

## Appendix A — Lindström reference data (the worked example)

Brand #1, as it ships today. **Treat as a fixture for the generalized model,
not as the model.**

### A.1 Facet keys — `filter_metadata` (11 live)

`type` · `cut` · `head` · `size` · `cap` · `cap_disp` · `handle` · `esd` ·
`block` · `series` · `tipw`

| key | applies to | vocabulary | derived from |
|---|---|---|---|
| `type` | all | slug of the L3 section | `section_l3` |
| `cut` | cutters | `ultra-flush` · `flush` · `micro-bevel` | trademark term in `TITLE` |
| `head` | all | per-chapter (head/tip shape, jaw surface, drive type) | **`head_type` ELSE `group`** — fallback, never both (agree on only 5 of 155 rows) |
| `size` | cutters | `xs` · `s` · `m` · `l` | vendor `Head Size` |
| `cap` | cutters, strippers (113) | `fine` · `medium` · `heavy` · `xheavy` | `capacity_mm` → buckets 0.8 / 1.25 / 1.6 / ∞ |
| `cap_disp` | same 113 | vendor's own string, verbatim | `capacity_raw` |
| `handle` | cutters, pliers | `standard` · `ergo` · `long` | SKU prefix: `RX`→ergo, `HS`(not shear)→long, else standard |
| `esd` | every tool | `yes` · `no` | vendor `ICONS` field — **never** inferred from `Resistivity` |
| `block` | all with a block | slug of vendor product block | `product_block` |
| `series` | cutters + pliers | `s80` · `rx` · `hs` · `sup` | `handle` first, then MPN first digit (read **through** any letter prefix) |
| `tipw` | tweezers | `ultra-fine` · `fine` · `medium` · `broad` | `Tip Width, mm` banded <0.20 / 0.20–0.49 / 0.50–0.99 / ≥1.00 |

**Chapter rails as shipped** (ground truth =
`templates/components/category/ct-filter-rail-*.html`): Tweezers
`type` · `head` · `tipw` · `esd` — four facets, ESD **include-only**, never a
Yes/No pair.

### A.2 Spec keys — `spec_display` (16)

`cr cc tw ht hs rs hn ln hh hw hk wt co` **+ `tt bh bw`** — the shipped set is
16, including the three appended keys (FR-136).

### A.3 Chapter sizes (2026-07-10)

Cutters 116 · Tweezers 123 · Pliers 24 · Screwdrivers 19 → these get rails.
Small chapters (≤~10) are list-only, no rail: Torque Tools 9 · Shear Cutters 8
· Cable Cutters 5 · Spatulas 4 · Kits 2 · Special 1.

### A.4 Known live state at time of baselining

292 products live per NG (see OQ-1 vs MB's 346) · 5 custom fields each ·
`ct_page_type=tool` on 292/292 · `related_products = [-1]` fix directed
2026-08-17 (11 in-scope + 152 released, FR-135) · 20 unpriced SKUs at `$0` +
price hidden · 1 zero-weight SKU (`59-TL 242ACF`) · 23 colliding product
names (reported, not gated).
