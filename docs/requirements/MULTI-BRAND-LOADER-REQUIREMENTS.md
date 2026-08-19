# Multi-Brand Product Data Loader — Requirements Specification

**Version:** 1.1 · **Date:** 2026-08-17
**Status:** For implementation
**Supersedes:** the single-brand Lindström pipeline (`pipeline/`, `tools/`)

**Changes in 1.1 (operator direction, 2026-08-17):** every field — pricing
included — is changeable; no field may be permanently unwritable; all changes are
validated before and after the write; every run is individually reversible.
Sections §0.1, §4.6, §4.9, §4.10, §7, §9.3 and §9.13 carry the change.

---

## 0. How to read this document

This is a **requirements specification**, not a design. It states *what* the
system must do and *why*, with the reasoning preserved, so an implementer can
make design decisions without re-discovering the constraints.

Requirements are identified `FR-n` (functional), `NFR-n` (non-functional),
`INV-n` (invariant), `AC-n` (acceptance). **Every requirement is testable.**

**§9 is the most important section.** It records failures that actually happened
in production on the first-generation loader. Each one cost a correction cycle
and most were invisible to a green build. A v2 that does not address §9 will
reproduce them.

### 0.1 ⛔ One coupling that must not be broken

**§4.6 (nothing is unwritable) is only safe when shipped with §4.9 (validate
every change) and §4.10 (roll back every run).** They are one mechanism described
in three places, not three independent features.

The first-generation loader refused, in code, to write price fields. That refusal
was removing a real risk: at the time, the built library held **pre-increase**
prices, and an unrestricted full apply would have reverted the August increase on
**288 products** and reported `updated=288 failed=0` as a clean success. It was
caught by a field-level diff against a saved snapshot **before** any write.

So the refusal was solving a real problem — with the wrong instrument. It also
made MSRP unreachable for two weeks (§9.3). The replacement is:

| v1 | v2 |
|---|---|
| the loader *may not* write price | the loader *may* write any field |
| — | every intended change is shown field-by-field before the write |
| — | a change set of unusual size or direction requires explicit confirmation |
| — | every field written is read back and verified |
| — | every run is reversible from per-row before-images |

**An implementer who takes §4.6 without §4.9 and §4.10 has rebuilt the
288-product revert and removed the thing that caught it.**

---

## 1. Purpose and scope

### 1.1 Purpose

Build product data for **any brand** from an arbitrary set of vendor
spreadsheets, normalise it into one canonical row per SKU, derive presentation
and filtering data, and publish it to a commerce endpoint — flexibly, repeatably,
and reversibly.

### 1.2 What exists today, and why it is being replaced

The first-generation pipeline successfully loaded 346 Lindström products to a
live BigCommerce store. It is, however:

| Limitation | Evidence |
|---|---|
| **Single-brand** | `config.py` hardcodes source filenames, 11 chapter names, SKU prefix `59-`, brand `Lindström`, and expected row counts (322/312/10/302/20) |
| **Fixed source set** | Exactly six sources `S1..S6`, each with a bespoke reader |
| **Brand rules in code** | Series derivation, ESD policy, tip-width bands, category dual-list/move rules all live in Python |
| **Endpoint-coupled** | BigCommerce payload shapes, custom-field semantics and rate limits are spread through `build_products.py` and `bc_loader.py` |
| **No backup, no rollback** | The loader has neither. Both were added late, by hand, as separate tools |
| **Fields unwritable in code** | `build_body()` pops `price`, `retail_price` and `custom_fields` on update — an operator cannot change them at all |
| **Split write authority** | Product fields via one tool, prices via another — the seam caused a two-week live data defect (§9.3) |

### 1.3 Scope

**In scope:** ingestion, normalisation, derivation, persistence of built data,
change management, validation, publication, verification, backup, rollback and
restore.

**Out of scope:** authoring vendor source data; storefront theme; pricing
strategy; order and inventory management.

### 1.4 Design principles

> **P1 — The system is a data pipeline with an endpoint plugin, not a
> BigCommerce loader that happens to read spreadsheets.**

Everything brand-specific is **data**. Everything endpoint-specific sits behind
**one interface**. What remains in the core is generic.

> **P2 — Safety comes from visibility and reversibility, never from
> prohibition.**

The system does not protect data by refusing to change it. It protects data by
showing every intended change before it happens, validating it, verifying it
afterwards, and being able to put it back. **A field the operator cannot change
is a defect, not a safeguard.**

---

## 2. Definitions

| Term | Meaning |
|---|---|
| **Brand pack** | A directory of configuration and rules defining one brand. Contains no code. |
| **Source** | One vendor file (xlsx/csv/json) declared in the brand pack |
| **Canonical row** | One normalised record per SKU — the merge output; the single intermediate |
| **Derived field** | A value computed from canonical fields (facets, SEO, packed display strings) |
| **Built data** | Canonical rows plus derived fields, persisted and versioned |
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
| **Override** | An operator-authored correction applied at build time, never to source |

---

## 3. System context

```
   Vendor spreadsheets (N per brand, READ-ONLY)
                │
                ▼
   ┌───────────────────────────┐
   │ 1. INGEST                 │  declared sources → raw frames
   ├───────────────────────────┤
   │ 2. NORMALISE + MERGE      │  → canonical rows (one per SKU)
   ├───────────────────────────┤
   │ 3. DERIVE                 │  facets · SEO · packed strings · families
   ├───────────────────────────┤
   │ 4. BUILT DATA STORE       │  versioned, diffable, every field editable
   ├───────────────────────────┤
   │ 5. VALIDATE + PUBLISH     │  change set → confirm → write → verify
   └───────────────────────────┘
                │            ▲
        ┌───────┴────────┐   └── rollback (per-run, from before-images)
        ▼                ▼
   BigCommerce      other endpoints
```

**Stages 1–4 have no knowledge of any endpoint.** Stage 5 is the only place an
endpoint's field names, limits or semantics appear.

---

## 4. Functional requirements

### 4.1 Brand configuration

- **FR-1** The system shall load all brand-specific configuration from a **brand
  pack** — a directory of declarative files — with no brand identifier, filename,
  field name, count or rule appearing in code.
- **FR-2** The brand pack shall declare: brand identity; SKU construction rule;
  source declarations; join strategy; field mappings; derivation rules;
  vocabularies; validation expectations; managed-field sets; blast-radius
  thresholds; endpoint bindings.
- **FR-3** The system shall support **multiple brand packs concurrently**, with
  no shared mutable state between them, and shall require an explicit brand
  selection on every invocation.
- **FR-4** The system shall **validate a brand pack** against a schema before any
  processing, reporting every error at once rather than failing on the first.
- **FR-5** The system shall run any operation against a **named environment**
  (e.g. `sandbox`, `live`) resolved from the brand pack, and shall never default
  to a production environment.

### 4.2 Ingestion (Stage 1)

- **FR-6** The system shall ingest **N sources per brand**, where N is not fixed,
  each declared with identifier, path, format, sheet/range, header row, and key
  column.
- **FR-7** The system shall support at minimum `.xlsx`, `.xlsm`, `.csv`, `.json`.
  The reader shall be selected by declaration, not by extension sniffing.
- **FR-8** The system shall read all source values as **text by default**, and
  coerce types only where a declaration says so.
  > *Rationale: numeric inference turned the vendor's `108` into `108.0`, which
  > shipped as "108.0 mm" on a customer-facing spec row; and an EAN read as a
  > float produced a malformed GTIN.*
- **FR-9** The system shall read sources **without acquiring a write lock**, and
  shall succeed when a file is open in Excel or held by a sync client — copying
  to a temporary location if required.
- **FR-10** The system shall treat every source as **strictly read-only** and
  shall never write to a source path.
  > *Rationale: the vendor directory is a copy taken from masters. A correction
  > written there is silently overwritten by the next copy — the fix appears to
  > apply, then vanishes. Corrections belong in overrides (FR-25), which are
  > loader-side and reversible.*
- **FR-11** The system shall record, for each source, a **content hash, size and
  modification time** in the build manifest, and shall report when a source has
  changed since the previous build.
- **FR-12** The system shall support a source that is **two or more blocks in one
  sheet** (e.g. product data and price data side by side, row-aligned but keyed
  by different columns), each block declared and keyed independently.
  > *Rationale: joining on the obvious column collided two genuinely distinct
  > products that share one product code; the correct key covered 322/322.*
- **FR-13** The system shall support declaring a source as **optional**, and shall
  proceed with a recorded warning when it is absent.

### 4.3 Normalisation and merge (Stage 2)

- **FR-14** The system shall produce exactly **one canonical row per SKU**.
- **FR-15** The system shall normalise join keys using a **declared** key
  function, and shall never assume two systems spell a product the same way.
- **FR-16** The system shall support **explicit code-association tables** mapping
  a key in one source to a key in another; these shall take precedence over any
  computed match.
  > *Rationale: the vendor's site code `TL 15A-GW` is the price book's `15AGWM`.
  > A raw key join found 203 of 346 products; the association table found 334.*
- **FR-17** The system shall **never infer product identity from names or
  descriptions**. Identity comes from codes and declared associations only.
  > *Rationale: operator direction — "use the book and live sku associations.
  > dont factor the name, differences may be subtle." Name matching would bind
  > `8211` to `RX8211`, a different tool with different specs.*
- **FR-18** The system shall support **alias columns**: an ordered fallback chain
  of source columns for one canonical field, where an alias fires **only when the
  primary is empty**.
- **FR-19** For every aliased value the system shall record **which source column
  supplied it**, per SKU, in an auditable artefact.
  > *Rationale: without provenance a wrong storefront value cannot be diagnosed —
  > a bad vendor cell and the loader reading the wrong column need opposite fixes.*
- **FR-20** When a primary and an alias are **both populated and disagree beyond a
  declared tolerance**, the system shall load **neither** and shall report the
  conflict. A silent tiebreak is prohibited.
- **FR-21** The system shall parse units **from inside the value**, never from the
  column header, where a declaration marks a column unit-bearing.
  > *Rationale: one `Length` column carries `130 mm` on one row and `4,72 in` on
  > 115 others.*
- **FR-22** The system shall support **decimal-comma** values and normalise them
  to a declared output form.
- **FR-23** The system shall support **dual-unit output** (e.g. `133.5 mm / 5.25 in`)
  composed from two source columns, and single-unit output where only one exists.
- **FR-24** The system shall detect and report **mojibake** in any text field
  destined for display or for a filter value.
- **FR-25** The system shall apply **operator overrides** — on any field, without
  exception — after merge and before derivation. An override shall apply **only
  when its recorded pre-value still matches** what the build produced; otherwise
  the build halts.
  > *Rationale: an override written against data that has since changed is being
  > applied to a value it was never derived from.*
- **FR-26** Overrides shall be **reversible** — deleting an entry restores the
  source-derived value — and shall carry a recorded basis (who, when, why).

### 4.4 Derivation (Stage 3)

- **FR-27** The system shall derive **facet values** from canonical fields using
  declared rules, supporting at minimum: direct mapping, slug, numeric banding,
  conditional scoping by category, and derivation from multiple inputs in
  declared precedence.
- **FR-28** Numeric band boundaries shall be **declared explicitly**, including
  which side a boundary value joins.
  > *Rationale: 52 of 94 products sat exactly on a boundary — this rule silently
  > decided half a category.*
- **FR-29** The system shall support facets **scoped to a subset of categories**,
  and shall assert both the presence set and the **absence set**.
  > *Rationale: over-application of a facet is invisible to a presence check.*
- **FR-30** The system shall validate every derived facet value against a
  **frozen, versioned vocabulary** and shall **halt** on any value outside it,
  naming the SKU and the key.
  > *Rationale: filter values are compared as literal strings by the storefront.
  > A mismatched value matches nothing and renders "no products" — it does not
  > error.*
- **FR-31** Adding a vocabulary value shall be an **explicit, recorded action**,
  never automatic. The operator shall be able to add one without a code change.
- **FR-32** The system shall support **packed multi-value fields**
  (`key=value;key=value`) with declared key order, declared delimiters, and
  omission of absent keys.
- **FR-33** A packed value shall **never contain a delimiter**. On encountering
  one the system shall **halt** — escaping or sanitising is prohibited.
  > *Rationale: one theme parser handles several packed fields; corruption in one
  > spreads to the others.*
- **FR-34** The system shall enforce declared **length limits** on any field with
  a remote limit, and shall **halt rather than truncate**, naming the field, SKU
  and measured length.
  > *Rationale: a truncated packed string loses whole values silently and still
  > looks like a success.*
- **FR-35** A derived field with no value shall be **omitted entirely**, never
  written as an empty string.
  > *Rationale: an empty spec row reads as missing data rather than not-applicable.*
- **FR-36** The system shall derive **relationship sets** (families) from declared
  rules; every member of a family shall carry the same membership, so
  relationships are **symmetric by construction**.
- **FR-37** The system shall emit relationship lists in a **declared order**,
  because endpoints and storefronts generally preserve stored order and do not
  sort.
- **FR-38** Derivation shall be **pure and per-row** wherever possible; any
  cross-row derivation shall be declared explicitly.

### 4.5 Built data store (Stage 4)

- **FR-39** The system shall persist built data in a **diffable, text-based,
  version-controllable** format.
- **FR-40** Each build shall record a **manifest**: brand, timestamp, tool
  version, source hashes, overrides applied, vocabulary version, row count, and
  every assertion with its measured value.
- **FR-41** The system shall **rebuild deterministically**: identical sources,
  overrides and configuration produce byte-identical built data.
- **FR-42** The system shall **diff two builds**, reporting added, removed and
  changed rows field by field.
- **FR-43** The system shall support **operator edits to any field of built
  data** through declared override files, and shall never require editing built
  data directly. **No field shall be excluded from override.**
- **FR-44** The system shall support **explicitly adding rows** not present in any
  source (products known only from an operator list), with provenance recorded as
  operator-supplied.
- **FR-45** The system shall support **explicitly removing rows** via an exclusion
  list, honoured on **every** subsequent run.
  > *Rationale: without a persistent exclusion list, deleting a product remotely
  > does not stick — the next run finds no match and recreates it.*
- **FR-46** The system shall support **holding rows** from publication with a
  recorded reason, distinct from exclusion, and shall report held rows on every
  build.
- **FR-47** Every row shall carry, per field, the **source that supplied it**, so
  any published value is traceable without re-running the build.

### 4.6 Field mutability and write authority

> This section replaces v1's hardcoded field exclusions. **Read §0.1 first: it is
> only safe together with §4.9 and §4.10.**

- **FR-48** **Every field the system can represent shall be changeable by the
  operator.** No field shall be permanently unwritable, and no field shall require
  a code change to become writable.
- **FR-49** The set of **managed fields** — those the system writes at an endpoint
  for a given run — shall be **declared data**, editable by the operator without
  a code change, defaulting to **every mapped field**.
- **FR-50** No component shall contain a **code-level exclusion** preventing a
  mapped field from being written. Such an exclusion is prohibited outright.
  > *Rationale: `build_body()` popped `price`, `retail_price` and `custom_fields`
  > on update. The MSRP defect was therefore unfixable by the loader, and no
  > configuration change could reach it. §9.3.*
- **FR-51** **Commercial fields — price, MSRP/retail price, sale price, cost,
  currency, availability, price visibility — shall be ordinary managed fields**,
  creatable and updatable by the same mechanism as any other field, with no
  special-case handling anywhere in the system.
- **FR-52** A field **absent from built data shall not be written**. Omission is
  not a write, and shall never be published as an empty or zero value.
  > *Rationale: this — not a code-level ban — is what protects operator-set values
  > such as the 23 active sale prices. It is a property of the payload builder,
  > and the operator turns it off simply by putting the field in built data.*
- **FR-53** The operator shall be able to move a field between **managed and
  unmanaged per run**, by declaration or by command-line selection, without
  editing code.
- **FR-54** **Exactly one component shall own each managed field** for a given
  run. Two components writing one field is prohibited.
- **FR-55** **Every managed field shall have an owner.** A managed field with no
  owner shall be a **build failure**, reported by name — never a silent omission.
  > *Rationale: this closes §9.3. MSRP was managed in intent and owned by nobody
  > in fact, and nothing in the system detected that.*
- **FR-56** Field ownership shall be declared in the brand pack, **reported at the
  start of every run** as a field→owner table, and enforced at runtime.
- **FR-57** Where a field is deliberately **unmanaged**, the system shall report
  it as unmanaged on every run **together with the count of rows whose built value
  differs from the endpoint's**. Unmanaged shall never mean invisible.

### 4.7 Publication (Stage 5)

- **FR-58** The system shall publish through an **endpoint adapter interface**.
  The core shall contain no endpoint-specific field names, limits or semantics.
- **FR-59** The adapter interface shall define at minimum `capabilities()`,
  `snapshot()`, `fetch_existing()`, `create()`, `update()`, `delete()`,
  `verify()`, `restore()`, and declared limits.
- **FR-60** The system shall ship a **BigCommerce adapter** first, and at least
  one **non-API adapter** (e.g. CSV/JSON export) to prove the abstraction holds.
- **FR-61** The system shall determine create-vs-update by **querying the endpoint
  for existing identity first**, never by assuming.
- **FR-62** All publication operations shall be **idempotent**: re-running with
  unchanged data produces no change and no duplication.
- **FR-63** Sub-resources (custom fields, images, relationships) shall be
  reconciled **by identity, not appended**: match existing, update, create only
  the missing, delete only those the system manages.
  > *Rationale: a custom field sent without an id is added, not replaced —
  > re-running duplicated every field. Images posted blindly went 7 → 14.*
- **FR-64** Where a remote resource is re-hosted on write (e.g. images), the
  system shall write a **provenance fingerprint** enabling idempotent
  reconciliation, and shall **never delete a resource it cannot prove it owns**.
- **FR-65** The system shall write **explicit empty values** rather than skipping
  a field, where the endpoint declares a legacy sentinel default.
  > *Rationale: skipping a relationship list for a family-less product left
  > BigCommerce's V2 `[-1]` "auto-determine" default in place, and the storefront
  > rendered invented relationships on 163 products. This does not conflict with
  > FR-52: an endpoint sentinel is a declared adapter property, and the adapter
  > states which fields need an explicit empty.*
- **FR-66** The system shall maintain a **ledger**: local identity, remote
  identity, action, **fields written**, per-sub-resource counts, status, detail,
  and the **before-image** of every field written (§4.10).
- **FR-67** The ledger shall be written **incrementally — before and after each
  row's write** — so an interrupted run is both resumable and reversible.
- **FR-68** The system shall support **staged publication** — dry run → limited
  batch → full — and shall **refuse an unstaged full run**.
- **FR-69** The system shall respect declared **rate limits** and back off on
  throttling responses rather than failing.
- **FR-70** All writes shall require an **explicit arming flag**; writing to a
  production environment shall require a **second, distinct** flag.
- **FR-71** The system shall treat **partial-success responses** per the adapter's
  declaration (e.g. HTTP 207 is a success for BigCommerce).

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

- **FR-73** A **delta publication shall recompute every affected relationship set
  and rewrite all members**, not only the changed rows.
  > *Rationale: relationship lists are per-row and not mirrored by the endpoint.
  > Writing only the new row leaves every existing sibling's list without it —
  > the new product's own page is right while it is missing from all the others.*
- **FR-74** The system shall report, before any write, a **complete field-level
  change set**: creates, updates by field with before and after values, removals,
  and unchanged counts. This report shall be producible **without arming**.
- **FR-75** The system shall support **selecting a subset of rows** for any
  operation by explicit list, reporting subset size against total.
- **FR-76** The system shall support **selecting a subset of fields** for any
  operation, so a single field (e.g. MSRP) can be corrected across the whole
  catalogue without touching anything else.
- **FR-77** The system shall provide a **repair mode** that re-writes named fields
  on rows the ledger already marks complete.
  > *Rationale: a ledger-idempotent tool skips rows it believes are done. Without
  > a repair path, a field it failed to write once is unreachable forever. §9.3.*

### 4.9 Validation of changes

- **FR-78** The system shall **validate every payload before any write**: type,
  required-ness, numeric range, string length, vocabulary membership, delimiter
  safety, and referential integrity of every id it references.
- **FR-79** A validation failure shall name the **row, field, rule, and offending
  value**, and shall halt the run **before the first write**, never part-way
  through.
- **FR-80** The system shall compute and report the **blast radius** of every
  change set before writing: rows affected, fields affected, count per field, and
  for numeric fields the magnitude and **direction** of change.
- **FR-81** A change set exceeding a **declared threshold** — proportion of rows,
  proportion of a field's population, or absolute count — shall require an
  **explicit confirmation that names the measured figure**. Arming alone shall not
  satisfy it.
- **FR-82** The system shall flag a **directional anomaly**: a numeric field where
  a large majority of the changes move the same way.
  > *Rationale: the exact signature of the near-miss in §9.13 — 288 prices, all
  > moving down, because built data was one price book behind. Size alone would
  > not have flagged it in a full catalogue load; size plus direction does.*
- **FR-83** A run whose change set is **empty** shall say so explicitly and exit
  without writing, rather than reporting a successful write of nothing.
- **FR-84** The system shall **verify every field it wrote** by reading it back
  from the endpoint and comparing against intent.
- **FR-85** Verification shall report **expected versus observed per field**, name
  every mismatched row, state **how many of how many fields were verified**, and
  exit non-zero on any mismatch.
- **FR-86** Verification shall **not rely on the write operation's own success
  report**.
  > *Rationale: a full catalogue load reported `updated=346 failed=0` while
  > writing none of the intended price fields, because the adapter's update
  > policy excluded them.*
- **FR-87** Every check shall be **provably falsifiable**: the system shall
  provide a mechanism to corrupt an input and demonstrate the check reports it,
  and that demonstration shall be part of the test suite.

### 4.10 Backup, rollback and restore

- **FR-88** The system shall take a **complete snapshot of remote state before any
  write**, automatically — not as a separate operator step.
- **FR-89** A snapshot shall capture **every field and sub-resource the system can
  write**, plus remote identities, and shall be self-describing (brand,
  environment, timestamp, counts, tool version).
- **FR-90** A snapshot shall include a **control assertion** — a known-present
  record — and shall **fail rather than write a partial snapshot** if absent.
  > *Rationale: an empty or filtered pull must read as a failure, never as
  > "zero records".*
- **FR-91** The system shall **refuse to write** when a pre-write snapshot cannot
  be taken.
- **FR-92** The system shall capture a **per-row before-image at write time** —
  the endpoint's current value of every field about to be written — and record it
  in the ledger **before** issuing the write.
  > *Rationale: a bulk snapshot taken at run start can be minutes stale and does
  > not cover rows created mid-run. The before-image makes each individual write
  > reversible on its own terms, which is what makes FR-93 exact rather than
  > approximate.*
- **FR-93** The system shall **roll back a named run** from its before-images,
  restoring every field that run wrote and **no other field**.
- **FR-94** Rollback shall be available for an **interrupted or partially
  completed** run, covering exactly the rows the ledger records as written.
- **FR-95** On **verification failure**, the system shall halt further writes
  immediately and shall roll back, or offer rollback, according to a declared
  policy — reporting which rows are affected either way.
- **FR-96** Rollback shall report a **field-level diff before executing**, and
  shall be refusable by the operator at that point.
- **FR-97** Rollback shall be **verified by the same mechanism as publication**
  (FR-84..86). An unverified rollback is not a completed rollback.
- **FR-98** The system shall support **restoring from any retained snapshot**,
  wholly or for a named subset of rows or fields.
- **FR-99** Snapshots and ledgers shall be retained per a declared policy, indexed
  by run, and **never overwritten implicitly**.

### 4.11 Reporting and observability

- **FR-100** Every run shall produce a **durable, timestamped report** containing
  the field→owner table, the change set, every assertion with its measured value,
  the verification result, and the **rollback handle** for that run.
- **FR-101** Every assertion shall report a **measured number**, never only a
  verdict.
  > *Rationale: "a check that can only ever say 'all clear' is not a check."*
- **FR-102** Long operations shall report **progress with counts and ETA**, and
  report failures as they occur, not only in a summary.
- **FR-103** The system shall never print credentials, tokens, or environment
  identifiers to logs, reports or documents.

---

## 5. Non-functional requirements

- **NFR-1 Determinism.** Identical inputs produce identical built data. No
  wall-clock, random, or iteration-order dependence in derived values.
- **NFR-2 Auditability.** Every published value traceable to a source cell, an
  override, or a named derivation rule.
- **NFR-3 Fail-closed on ambiguity.** Ambiguity halts. Absence of a signal selects
  the safe default. No silent coercion, truncation, or tiebreak. **This governs
  uncertainty, not permission** — it shall never be implemented as a restriction
  on which fields may be changed (P2, FR-48).
- **NFR-4 Idempotence.** Every operation safe to re-run.
- **NFR-5 Resumability.** Any interrupted operation resumable without duplication.
- **NFR-6 Reversibility.** Every run individually reversible from its own
  before-images, without depending on a bulk snapshot and without disturbing any
  other run.
- **NFR-7 Mutability.** No field permanently unwritable; no field requiring a code
  change to become writable.
- **NFR-8 Isolation.** Brand packs cannot affect one another.
- **NFR-9 Portability.** Core has no endpoint dependency; adding an endpoint
  requires no core change.
- **NFR-10 Performance.** 1,000 rows built in under 60 s on a developer machine;
  publication bounded by endpoint rate limits, not local processing.
- **NFR-11 Operability.** One CLI, consistent verbs, dry-run default.
- **NFR-12 Testability.** Every gate and derivation rule unit-testable without
  network access, with fixtures for each failure in §9.

---

## 6. Data model

### 6.1 Canonical row — required structure

| Group | Fields |
|---|---|
| Identity | local key, vendor code, endpoint SKU, remote id (from ledger) |
| Classification | category path (L1..Ln), grouping/block, family membership |
| Commercial | list price, MSRP, sale price, cost, currency, availability, price visibility, hold state |
| Physical | weight, dimensions, with declared unit and source |
| Descriptive | name, description, meta description |
| Media | ordered image references with provenance |
| Derived | facets, packed display strings, SEO strings |
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
  fields.yaml           source → canonical mapping
  derive.yaml           facets, bands, packing, SEO, families
  vocabulary.json       frozen facet vocabulary (versioned)
  expectations.yaml     asserted counts and shapes
  managed.yaml          managed-field set + field→owner map (§4.6)
  thresholds.yaml       blast-radius thresholds per field (§4.9)
  endpoints.yaml        adapter bindings
  overrides/            operator corrections, each with basis
  exclusions.csv        rows never to publish
```

**No code in a brand pack.** If a brand needs behaviour the declarations cannot
express, that is a **core feature request**, not a per-brand script.

### 6.3 Field mapping is data

- **FR-104** The mapping from canonical fields to endpoint fields shall live in a
  **declaration the operator can read and change** without code changes.
- **FR-105** A field shall be published **only when explicitly confirmed** in the
  mapping; the operator confirms a field by editing the mapping — never by editing
  code.
  > *Rationale: the operator's standing rule — "CONFIRMED = Y → load the field;
  > blank → leave it blank." This is a per-field switch under operator control,
  > which is the opposite of a code-level exclusion (FR-50): the operator can
  > always flip it.*

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
7. verify                    # the batch — halt + rollback on mismatch
8. publish                   # remainder
9. verify                    # everything
   rollback <run>            # available at any point from step 6 onward
```

- **FR-106** The system shall enforce this ordering: it shall refuse a full
  publication without a prior staged batch and its verification, and shall refuse
  any publication whose change set has not been validated (FR-78..82).

### 7.2 Write authority

Specified in **§4.6**; summarised here because it is the rule most often broken
in practice:

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
| Over-length field (FR-34) | The endpoint rejects it anyway; halting names the field instead of 422 |
| Primary/alias disagreement (FR-20) | The operator rules on it via an override (FR-25) |
| Blast radius over threshold (FR-81) | Confirming proceeds; it asks, it does not refuse |
| Managed field with no owner (FR-55) | Declaring the owner proceeds |

Every one of these is resolvable by the operator through **data**, with no code
change. That is the test for whether a halt is legitimate: *can the operator clear
it by editing the brand pack or an override?* If not, it violates FR-48.

---

## 8. Acceptance criteria

- **AC-1** Two brand packs with different source counts, join strategies and
  facet rules both build and publish with no code difference.
- **AC-2** A brand with 3 sources and a brand with 9 sources both build.
- **AC-3** Rebuilding unchanged inputs produces byte-identical built data.
- **AC-4** Publishing twice produces zero changes on the second run, with no
  duplicated sub-resources.
- **AC-5** **Any field can be changed end to end.** For each of price, MSRP, sale
  price, weight, description, a facet and a relationship list: change the value in
  built data, publish, and verify the endpoint reflects it — **with no code change
  between cases**.
- **AC-6** A managed field declared with **no owner fails the build**, naming the
  field.
- **AC-7** Repair mode re-writes a named field on rows the ledger already marks
  complete.
- **AC-8** A single field can be published across the whole catalogue via
  `--fields`, leaving every other field byte-identical, verified against a
  snapshot.
- **AC-9** Adding one product and re-publishing updates **every** member of that
  product's family, verified symmetric in both directions.
- **AC-10** Removing a product via the exclusion list keeps it removed across
  three subsequent runs.
- **AC-11** A completed run can be **rolled back from its before-images**,
  restoring exactly the fields it wrote and leaving every other field untouched,
  verified field by field.
- **AC-12** An **interrupted** run can be rolled back, covering exactly the rows
  the ledger records as written.
- **AC-13** A verification failure **halts further writes** and triggers rollback
  per policy.
- **AC-14** A change set exceeding a declared threshold **cannot be written**
  without an explicit confirmation naming the measured figure — arming alone is
  refused.
- **AC-15** A **directional anomaly** is flagged: a fixture in which N numeric
  values all move the same way is reported before any write. *(This fixture is the
  §9.13 near-miss: rebuild it and prove the system stops.)*
- **AC-16** A snapshot taken before a write restores the endpoint to its prior
  state, verified field by field.
- **AC-17** Every gate is demonstrated **red** by a fixture that violates it, and
  green when it does not.
- **AC-18** Verification detects a value written to built data but not published —
  i.e. it does not trust the publication report.
- **AC-19** A second endpoint adapter publishes the same built data with no core
  modification.
- **AC-20** Corrupting one source cell causes a specific, named assertion to fail
  rather than a silent wrong value.
- **AC-21** The system refuses to publish when a pre-write snapshot fails.
- **AC-22** Every failure in §9 has a regression test.

---

## 9. Invariants — failures that actually occurred

**Each of these was live, and most were invisible to a passing build.**

### 9.1 A green check that cannot fail

A verification routine passed for weeks while checking 7 hardcoded SKUs,
asserting nothing, and returning exit 0 unconditionally.

- **INV-1** Every check shall be demonstrated to fail on corrupted input before
  its passing result is trusted.

### 9.2 A check that does not look at the field it protects

A price run wrote `price` and never `retail_price`. Its verification checked
`price` only. It reported **286/286 clean, twice**, while 309 MSRPs were stale
for two weeks.

- **INV-2** Verification shall assert **every field the operation writes**.
- **INV-3** Coverage shall be stated in the output: *"verified N of M fields."*

### 9.3 A field owned by nobody, and unreachable by design

The product loader **refused in code** to write price fields — a deliberate
"never clobber a manual price" safeguard. The price tool owned prices but wrote
only two of the three price fields. **MSRP was managed in intent and owned by
nobody in fact.** Neither tool could fix it; a full catalogue load reported
`updated=346 failed=0` having written none of it; and the price tool's ledger
idempotence then made the field unreachable on re-run.

- **INV-4** One owner per managed field, **and every managed field has an owner**.
  A managed field with no owner is a build failure.
- **INV-5** **A safeguard that makes a field permanently unwritable is a defect,
  not a safety feature.** Protection comes from diff-before-write, blast-radius
  confirmation, post-write verification and rollback — never from prohibition.
- **INV-6** A ledger-idempotent tool must have a **repair path**, or a field it
  failed to write once is unreachable forever.

### 9.4 Sentinel defaults

Skipping a relationship list for family-less products left BigCommerce's V2 `[-1]`
"auto-determine" default. The storefront rendered invented relationships on
**163 products** — a jewellery kit listing diagonal cutters as "in this series".

- **INV-7** Write explicit empties. "Nothing to write" is not "write nothing".

### 9.5 Asymmetric relationships

Relationship lists are per-row and not mirrored. A delta wrote the new product's
list; its existing siblings never gained it.

- **INV-8** Recompute and rewrite **every member** of an affected set.

### 9.6 Identity by name

A vendor site search substring-matched `8211` inside `RX8211` and returned a
different tool with full specs. Separately, `15AGWM` and `TL 15A-GW` are one
product under two codes, while `HS7291` and `7291` are two different products
(140.3 mm / 103 g versus 108 mm / 50 g) that a prefix join would merge.

- **INV-9** Identity by declared code association only. Never by name, substring,
  or prefix.
- **INV-10** A near-match is a **reportable gap**, never a substitution.

### 9.7 Silent truncation and sanitising

A packed field over the endpoint limit hard-errors; a truncated one loses whole
values and still looks successful. A delimiter inside a value corrupts every
subsequent key.

- **INV-11** Halt, never truncate. Halt, never escape.

### 9.8 Stale mirrors

Three of five specification documents differed from their originals by hash. The
inbound coordination channel was **18 days stale**, causing a resolved defect to
be re-reported as open.

- **INV-12** Any mirrored artefact shall be hash-verified before it is read as
  authoritative.

### 9.9 Source data that disagrees with itself

The vendor's mm and inch cells contradicted on 50 pairs. A weight column read 6 g
where the vendor's own site said 50 g. Two products carried 0.09 g against peers
at 50 g.

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

A manually uploaded image had no source URL, so it never appeared in the desired
set; an unrelated field update classified it stale and deleted it.

- **INV-18** Never delete a remote resource that cannot be proven system-owned
  and superseded.

### 9.13 Stale built data silently reverting a live change (near miss)

The August price increase was applied directly to the store; built data was never
updated. Built data therefore disagreed with live on **288 of 346 products — every
one of them low**. An unrestricted full apply would have reverted the increase and
reported `updated=288 failed=0` as a clean success. It was caught by a field-level
diff against a saved snapshot, before any write.

This is the failure v1's code-level price ban was really guarding against — and it
guarded against it by making the field permanently unreachable, which then caused
§9.3. **The correct guard is detection and reversal, not prohibition.**

- **INV-19** Every run shall show its **complete field-level change set before
  writing**, and that report shall be producible without arming.
- **INV-20** A change set of unusual **size or direction** shall require an
  explicit confirmation naming the measured figure. 288 values all moving down is
  a signature, not a coincidence — and in a full-catalogue load, size alone would
  not have caught it.
- **INV-21** Built data shall be treated as **capable of being behind the
  endpoint**. The system shall never assume built data is authoritative simply
  because it was built more recently than it was published.

---

## 10. Migration from v1

- **FR-107** The system shall produce a Lindström brand pack reproducing the
  current 346-product catalogue, and its built data shall be diffed against live
  with **zero unintended changes** before cutover.
- **FR-108** The existing ledger and exclusion list shall be importable, so remote
  identities and deletions are preserved.
- **FR-109** v1 and v2 shall be runnable side by side against the same endpoint
  until v2's output is verified equivalent.
- **FR-110** The v1 code-level field exclusions shall be migrated to **declared
  managed-field data**, and the migration shall be demonstrated by **changing MSRP
  through the normal publish path and rolling it back** — the operations v1 could
  perform in neither direction.

---

## 11. Open questions for the operator

1. **Brands and scale** — which brands follow Lindström, and roughly how many
   SKUs and sources each? This sizes the join and derivation declarations.
2. **Second endpoint** — is a real second endpoint in view, or is the abstraction
   insurance? A real one should be built now; insurance can be a CSV adapter.
3. **Rollback policy (FR-95)** — on verification failure, should the system roll
   back automatically, or halt and wait for your decision? Automatic is safer for
   unattended runs; halt-and-wait keeps you in control of a partial state.
4. **Blast-radius thresholds (FR-81)** — what proportion of rows changing on one
   field should demand explicit confirmation? Starting proposal: any field
   changing on more than 25% of rows, **or** more than 80% of that field's changes
   moving the same direction. Both would have caught §9.13.
5. **Default managed set (FR-49)** — should a new brand default to managing
   *every* mapped field, or to a conservative core with the rest opt-in? Managing
   everything matches your direction; the conservative default is gentler when
   introducing the system to an existing catalogue.
6. **Sale pricing** — sale price is now an ordinary managed field. Should the
   system *compute* the sale programme from a rule, or only preserve and publish
   values you set?
7. **Multi-brand concurrency** — must brands publish independently to the same
   store simultaneously, or is serial acceptable?
8. **Override authoring** — should operators edit override files directly, or is a
   review-workbook round trip (as used for price review) preferred?
9. **Retention (FR-99)** — how long are snapshots and per-run ledgers kept, and
   where?
10. **Quote-only products** — should absence of a price be inferred, or always an
    explicit operator declaration?
11. **Verification depth (FR-84)** — is field-level read-back on every published
    row acceptable at scale, or is sampling with full-coverage-on-demand required?
