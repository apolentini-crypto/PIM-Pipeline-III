# PIM Pipeline III — Top-Down Architecture and Design

| | |
|---|---|
| **Document ID** | `CT-PIM-ARCH-001` |
| **Version** | 1.0 |
| **Date** | 2026-08-19 |
| **Status** | For review by operator; implements `CT-PIM-SRS-001` v1.0 (Baselined) |
| **Requirements** | `docs/requirements/PIM-BASELINE-REQUIREMENTS.md` — the single binding spec |
| **Audience** | The engineer/AI implementing the system |

---

## 1. Overview

PIM Pipeline III is two subsystems joined by one data contract (SRS D-5):

1. **PIM core** — the system of record. Ingests vendor spreadsheets for any
   brand, normalises to one canonical row per SKU, derives facets, specs,
   families and SEO, and holds all product data: editable, versioned,
   auditable.
2. **Distribution chain** — publishes built data to channels through endpoint
   adapters (BigCommerce first): new loads, updates, deletions — validated
   before, verified after, reversible always.

The contract between them is **built data**: an authoritative SQLite store
plus a deterministic canonical text export (SRS D-2). Stages 1–4 never see an
endpoint; stage 5 never sees a vendor file.

```
 vendor xlsx/csv/json          brand pack (declarative, no code)
        │                              │
        ▼                              ▼
 ┌─────────────────────────────────────────────┐
 │ PIM CORE                                    │
 │  ingest → normalise/merge → derive → store  │
 │                                  │          │
 │             SQLite (authoritative)          │
 │                └─ canonical export (JSONL)  │
 └─────────────────────┬───────────────────────┘
                       │  built data contract
 ┌─────────────────────▼───────────────────────┐
 │ DISTRIBUTION CHAIN                          │
 │  changeset → gates → confirm → publish      │
 │      → verify → (halt+offer rollback)       │
 └───────┬─────────────────────────┬───────────┘
         ▼                         ▼
   BigCommerce adapter       CSV/JSON adapter (abstraction proof)
```

### 1.1 Design stance

Everything brand-specific is **data** (brand packs). Everything
endpoint-specific is behind **one adapter interface**. What remains in core is
generic (SRS P1). Safety comes from **visibility and reversibility, never
prohibition** (P2). Structure is **declared, never inferred** (P3). Truth is
the **operator's** (P4).

---

## 2. Architecture decisions (ADRs)

### ADR-1 — Implementation stack: Python 3.12+, single CLI application

**Decision.** Python ≥3.12, one installable package (`pim`), one console entry
point, standard library + a small pinned dependency set: `openpyxl` (xlsx/xlsm),
`pydantic` v2 (brand-pack and payload validation), `httpx` (endpoint HTTP),
`typer` or `argparse` (CLI), `pyyaml`, `rich` (progress/reports). **No pandas
in core paths** — plain dicts/dataclasses keep values as text (FR-8), avoid
dtype coercion (the `108` → `108.0` failure class), and keep determinism
trivial.

**Why Python.**
- v1 is Python; every derivation rule, defect fixture and operator habit
  transfers. The team (operator + AI sessions) reads it fluently.
- NFR-11: runs on the operator's Windows workstation, no server. Python +
  SQLite is a zero-infrastructure fit.
- Best-in-class spreadsheet ingestion (`openpyxl` reads values-as-displayed
  and raw, handles xlsm, does not require Excel).
- Pydantic gives schema validation with every-error-at-once reporting (FR-4)
  and typed payload validation (FR-78) without hand-rolled checking.

**Alternatives rejected.** *Node/TS:* weaker xlsx story, no continuity, no
advantage for a CLI data tool. *Go:* fast and single-binary, but slower to
iterate on derivation rules and no v1 lineage; performance is not the
constraint (NFR-10 is trivially met by any stack).

**Consequences.** Pin exact dependency versions; `openpyxl` numeric handling
must be wrapped by the text-first reader (§5.2); Windows paths and LF-only
export writing handled explicitly (§6.4).

### ADR-2 — Storage: authoritative SQLite + deterministic JSONL export

**Decision (operator, SRS D-2).** One SQLite database per brand
(`var/<brand>/pim.db`, WAL mode). Every build writes the store, then emits a
**canonical export**: JSON Lines, one SKU per line, SKUs sorted, object keys
sorted, LF endings, UTF-8 (no BOM), fixed number formatting — plus
`manifest.json`. All diffing (FR-42), git versioning and the determinism
assertion (FR-41/AC-3) operate on export bytes. The export is a projection:
`pim export` regenerates it at any time, and a store whose regenerated export
differs from the recorded build export is reported corrupt (FR-39).

**Why.** SQLite gives real queries (completeness gates, drift reports, ledger
joins), transactional builds, and a single-file artifact that fits the
workstation model. The export preserves everything FR-39 originally wanted
from text files. Two representations, one authority, one projection rule —
never hand-edit either (edits go through overrides, FR-43).

### ADR-3 — One repository, layered packages, adapters as plugins

**Decision.** Monorepo. Core packages may not import `endpoints.*` except
through the adapter protocol; `endpoints.*` may not import `ingest/normalize/
derive`. Adapters register via entry points so a new endpoint is a new package,
zero core edits (NFR-9, AC-19). Brand packs live in `brands/` as pure data
(SRS §6.2). Enforced by an import-linter contract in CI.

### ADR-4 — Brand packs: YAML/JSON validated by published schemas

**Decision.** Each brand-pack file has a pydantic model; JSON Schemas are
generated into `docs/schemas/` so packs are editable with IDE validation.
Validation runs before any file read, reports every error at once (FR-4), and
rejects unknown keys (a typo'd key must fail loud, P3/AC-27).

### ADR-5 — Derivation is a closed rule vocabulary, not embedded code

**Decision.** `derive.yaml` composes a fixed set of rule types implemented in
core: `copy`, `map` (value→value), `slug`, `band` (explicit boundaries + side,
FR-28), `precedence` (A ELSE B, never both), `sku-pattern` (anchored regex on
identity fields), `unit-parse` (from inside the value, FR-21), `compose`
(format string over canonical fields → display strings, FR-115), `pack`
(ordered key packing, FR-32/117), `family` (block/attribute set rules ∪
explicit twin lists, FR-36). No expressions, no eval, no per-brand Python: if
a brand needs a rule the vocabulary can't express, that is a **core feature
request** (SRS §6.2). This is what keeps "no code in a brand pack" true rather
than aspirational, and keeps every rule unit-testable against canonical
fixtures with no vendor file present (NFR-12).

**The engine/data boundary (SRS D-6).** The relationship is the same one a
spreadsheet application has to its workbooks: the engine defines *operations*
— the fixed set of things that can be done to data (read a block, join on a
key, parse a unit, band a number, pack a string, compute a family) — and the
brand pack defines *everything about the data*: which fields exist, their
names, types, formats, units, counts, vocabularies and relationships. Nothing
about a brand's data shape lives in code; conversely, no executable logic
lives in a pack. When a brand needs an *operation* that does not exist yet,
that is the one case that touches code — a new rule type added to the engine,
available to every brand thereafter, never a per-brand script.

### ADR-6 — Verification failure: halt and wait, single behaviour

**Decision (operator, SRS D-3/FR-95).** On any post-write verification
mismatch the publisher stops issuing writes, prints affected rows, and renders
the rollback field-level diff with an explicit prompt. Nothing automatic. The
run stays `halted` in the run index until the operator rolls back or accepts.

### ADR-7 — Every check is an object with a control

**Decision.** All gates, assertions and verifications implement one `Check`
interface returning a **measurement** (numbers, not verdicts — FR-101), a
**control result** (proof the instrument can fail — FR-125/INV-16), and
before/after counts where the claim is "N defects remain" (FR-126/INV-15).
The test suite carries a **falsifiability harness**: for every check, a
fixture corruptor that must turn it red (FR-87, AC-17/20/22). A check without
a registered corruptor fails CI.

---

## 3. Codebase layout (top-down)

```
PIM-Pipeline-III/
├── pim/                        # the installable package
│   ├── cli/                    # command tree (§10); thin — no logic
│   ├── config/                 # brand-pack models, schema gen, validation (FR-1..5)
│   ├── ingest/                 # Stage 1 (FR-6..13, FR-111)
│   │   ├── readers/            # xlsx.py, csv.py, json_.py — declared, not sniffed
│   │   └── blocks.py           # multi-block sheets (FR-12)
│   ├── normalize/              # Stage 2 (FR-14..26, FR-24 codepoint checks)
│   │   ├── join.py             # key functions, association tables (FR-15..17)
│   │   ├── aliases.py          # fallback chains + provenance (FR-18..20)
│   │   ├── units.py            # in-value unit parse, decimal comma (FR-21..23)
│   │   ├── encoding.py         # codepoint sweep, mojibake (FR-24)
│   │   └── overrides.py        # pre-value-matched overrides (FR-25..26)
│   ├── derive/                 # Stage 3 (FR-27..38, FR-112..118)
│   │   ├── rules.py            # the ADR-5 rule vocabulary
│   │   ├── facets.py           # scoping, completeness, vocabulary (FR-29..31, 112..113)
│   │   ├── packing.py          # pack, delimiters, limits/overflow (FR-32..35, 116..117)
│   │   └── families.py         # symmetric-by-construction sets (FR-36..37)
│   ├── store/                  # Stage 4 (FR-39..47)
│   │   ├── db.py               # SQLite repository, migrations
│   │   ├── export.py           # canonical JSONL projection (D-2)
│   │   ├── csv_io.py           # CSV export/import for bulk edits (FR-137..139)
│   │   └── diffs.py            # build-vs-build diff on exports (FR-42)
│   ├── changeset/              # field-level diff vs endpoint/snapshot,
│   │   │                       # blast radius, directional anomaly (FR-74, 80..83)
│   ├── publish/                # Stage 5 orchestration (FR-58..77, 119..124)
│   │   ├── runner.py           # run lifecycle, staging, arming (FR-68, 70, 106)
│   │   ├── ledger.py           # incremental ledger + before-images (FR-66..67, 92)
│   │   ├── rollback.py         # per-run reversal (FR-93..97)
│   │   └── snapshot.py         # pre-write snapshots (FR-88..91, 98..99)
│   ├── verify/                 # Check framework, read-back, probes (FR-84..87, 125..128)
│   ├── endpoints/
│   │   ├── base.py             # EndpointAdapter protocol (§8.1)
│   │   ├── bigcommerce/        # §8.2
│   │   └── csvexport/          # abstraction proof (FR-60, AC-19)
│   ├── report/                 # run reports, ruling ledger (FR-100..103, 130)
│   └── util/
├── brands/
│   └── lindstrom/              # brand pack per SRS §6.2 (data only)
├── docs/
│   ├── requirements/           # SRS (binding) + superseded sources
│   ├── architecture/           # this document + ADR details as needed
│   └── schemas/                # generated JSON Schemas (ADR-4)
├── tests/
│   ├── fixtures/               # canonical fixtures, §9 failure fixtures
│   ├── corruptors/             # falsifiability harness (ADR-7)
│   └── fake_endpoint/          # in-memory adapter for full-loop tests
└── var/                        # NOT committed: db, exports, runs, snapshots
    └── <brand>/
        ├── pim.db
        ├── exports/<build_id>/rows.jsonl + manifest.json
        └── runs/<run_id>/ledger.jsonl · report.md · snapshot/
```

**Dependency rule (ADR-3):** `cli → publish/changeset/verify → store →
derive → normalize → ingest → config`. `endpoints.*` is reached only through
`endpoints.base`. No upward or cross imports.

---

## 4. Domain model

### 4.1 Core entities

| Entity | Identity | Notes |
|---|---|---|
| `Brand` | slug | loaded from a brand pack; no shared state between brands (FR-3) |
| `Build` | `build_id` = hash(sources, pack, overrides, tool version) | deterministic (FR-41) |
| `CanonicalRow` | (brand, sku) | one per SKU (FR-14); groups per SRS §6.1 |
| `FieldValue` | (row, canonical field) | value **as text** + typed view + `Provenance` |
| `Provenance` | — | `source_cell(file,sheet,row,col)` \| `override(id)` \| `derived(rule)` \| `operator_supplied` (FR-19, FR-47) |
| `Family` | (brand, family key) | member list + declared order (FR-36..37) |
| `Vocabulary` | (brand, facet key, version) | frozen; additions are recorded actions (FR-30..31) |
| `Override` | id | field, pre-value, new value, basis(who/when/why) (FR-25..26) |
| `ChangeSet` | (build, endpoint snapshot) | per-row per-field before/after + blast radius (FR-74, 80) |
| `Run` | `run_id` | mode, environment, arming, status ∈ {dry, staged, full, halted, rolled_back, verified} |
| `LedgerEntry` | (run, sku) | action, remote id, fields written, before-images (FR-66) |
| `Snapshot` | id | complete remote capture + control assertion (FR-88..90) |

### 4.2 SQLite schema (sketch)

```sql
-- store metadata: schema_version, brand, created
CREATE TABLE builds(
  build_id TEXT PRIMARY KEY, created TEXT, tool_version TEXT,
  pack_hash TEXT, vocab_version TEXT, row_count INTEGER,
  manifest_json TEXT);                          -- FR-40
CREATE TABLE rows(
  build_id TEXT, sku TEXT, held INTEGER DEFAULT 0, hold_reason TEXT,
  PRIMARY KEY(build_id, sku));                  -- FR-14, FR-46
CREATE TABLE field_values(
  build_id TEXT, sku TEXT, field TEXT, value TEXT,
  prov_kind TEXT, prov_ref TEXT,                -- FR-47
  PRIMARY KEY(build_id, sku, field));
CREATE TABLE families(
  build_id TEXT, family_key TEXT, position INTEGER, sku TEXT,
  PRIMARY KEY(build_id, family_key, position)); -- FR-36..37
CREATE TABLE vocab(
  facet_key TEXT, value TEXT, version TEXT, added_when TEXT, added_why TEXT,
  PRIMARY KEY(facet_key, value, version));      -- FR-30..31
CREATE TABLE remote_ids(
  sku TEXT, endpoint TEXT, environment TEXT, remote_id TEXT,
  PRIMARY KEY(sku, endpoint, environment));     -- FR-66, FR-108
CREATE TABLE runs(
  run_id TEXT PRIMARY KEY, build_id TEXT, mode TEXT, environment TEXT,
  status TEXT, started TEXT, finished TEXT, report_path TEXT);
CREATE TABLE ledger(
  run_id TEXT, seq INTEGER, sku TEXT, action TEXT, remote_id TEXT,
  fields_json TEXT, before_json TEXT,           -- FR-66..67, FR-92
  status TEXT, detail TEXT,
  PRIMARY KEY(run_id, seq));
CREATE TABLE rulings(
  ruling_id TEXT PRIMARY KEY, status TEXT, evidence TEXT); -- FR-130
```

Ledger rows are additionally streamed to `runs/<run_id>/ledger.jsonl` as they
happen (append-only, fsync'd per row) so an interrupted process loses nothing
(FR-67, NFR-5): the DB is authoritative, the JSONL is the crash-safe journal
replayed into the DB on resume.

### 4.3 Canonical export (the diff surface)

`exports/<build_id>/rows.jsonl` — one line per SKU, ascending SKU order:

```json
{"sku":"59-7191","fields":{"capacity_mm":{"v":"1.25","p":"S1:Cutters!D14"},
 "length_disp":{"v":"135.5 mm / 5.33 in","p":"derived:compose.length"}},
 "facets":{"cap":"medium","cap_disp":"0.2-1.25 mm"},
 "packed":{"filter_metadata":"type=cutter;cut=ultra-flush;..."},
 "family":{"key":"7190-block","pos":2},"held":false}
```

Determinism rules: sorted keys at every level, no floats (all values text),
no timestamps in `rows.jsonl` (timestamps live in `manifest.json` only), LF,
UTF-8. `manifest.json` carries build metadata, source hashes and every
assertion with its measured value (FR-40). AC-3 is tested as
`sha256(rows.jsonl)` equality across two builds of identical inputs.

---

## 5. PIM core design (Stages 1–4)

### 5.1 Stage order and halt points

```
validate pack (G-PACK, FR-4)          ← before any file read
→ ingest sources (hash, FR-11)
→ merge to canonical rows (FR-14..17)
→ alias resolution + provenance (FR-18..20)
→ units/decimal/encoding normalisation (FR-21..24)
→ apply overrides, pre-value-matched (FR-25..26)   ← halt on stale override
→ derive: facets → completeness → packing → families
→ vocabulary + completeness + delimiter + limit gates (G-VOCAB, G-COMPLETE, G-DELIM, G-LIMITS)
→ expectations check (counts/shapes from expectations.yaml)
→ write build to store, emit canonical export, print manifest
```

Every halt names SKU, field, observed value, expected condition (FR-102).

### 5.2 Ingest

Readers are selected by declaration (FR-7) and produce `RawFrame`s of
**strings**: the xlsx reader takes cell *display text* unless the declaration
says `type: number|date` (FR-8). Sources are copied to a temp location before
opening so a file held by Excel/sync still reads (FR-9) and no write lock ever
touches the vendor path (FR-10). Headers are matched byte-exact — never
trimmed, case-folded or comma-split (FR-111). A `blocks:` declaration slices
one sheet into independently keyed frames (FR-12). Each source records
(hash, size, mtime) into the manifest and a changed-since-last-build note
(FR-11).

### 5.3 Merge and identity

Join keys pass through the brand pack's declared key function (FR-15);
`joins.yaml` association tables always win over computed matches (FR-16).
Identity never comes from names, substrings or prefixes (FR-17/INV-9); a
near-match is emitted to the build report as a gap (INV-10). Output: exactly
one canonical row per SKU or a halt naming the collision.

### 5.4 Aliases, units, encoding, overrides

Alias chains fire only on empty primary (FR-18); every aliased value records
its supplying column (FR-19, projected as the `alias_sources` report); a
populated-and-disagreeing primary/alias pair loads **neither** and reports
(FR-20 — fixture-proven, since real data has never fired it). Unit parsing
reads the value's own unit token (FR-21), handles decimal commas (FR-22), and
composes dual-unit display strings with U+2013 ranges (FR-23, FR-115).
`encoding.py` sweeps by codepoint — U+FFFD, C1 controls, confusables like
U+00BA-for-degree — and never trusts rendered appearance (FR-24). Overrides
apply after merge, before derivation, only when the recorded pre-value still
matches, else halt (FR-25); deleting one restores the source value (FR-26).

### 5.5 Derivation and packing

The rules engine (ADR-5) evaluates per-row, pure, in declared order; cross-row
work (families, completeness) is explicit (FR-38). Facet slugs are validated
`^[a-z0-9][a-z0-9-]*$` and against the frozen vocabulary (FR-30/32). Chapter
scoping asserts presence **and absence** sets (FR-29). Completeness: every
declared key present for every SKU in the chapter (FR-112); a blank
rail-filtering key is a blocking failure (FR-113). Band facets emit
`X` + `X_disp` pairs where the vendor publishes the measurement (FR-114).
Packing enforces delimiter safety (halt, FR-33), no nesting (FR-116),
append-only pack order (FR-117), omission of empty keys (FR-35), and the
declared length limit with pack-order overflow split only where the pack
declares an overflow field (FR-34). Asset references are stored relative or as
identifiers, never hostnames (FR-118).

### 5.6 CSV bulk-edit round trip (`store/csv_io.py`)

Two representations already exist (SQLite authoritative, JSONL canonical
export). CSV is a **third, human-facing projection** (FR-137) — an editing
surface, not a storage format — and it never writes the store directly.
Imports go through change management (FR-138) and are self-checking against
spreadsheet damage (FR-139). The round trip:

```
pim <brand> export-csv [--fields ...] [--rows @list] [-o edits.csv]
      ↓  operator edits in Excel / Sheets
pim <brand> import-csv edits.csv            # diff only — no arming, no writes
      ↓  reports: N rows × M fields changed, before→after per cell,
         blast radius + directional anomaly, damage suspicions
pim <brand> import-csv edits.csv --apply    # writes overrides/, not built data
      ↓
pim <brand> build                            # overrides re-apply on every build
```

**Why imports land in `overrides/` rather than in the store.** Built data is
regenerated from vendor sources on every build (FR-41). A bulk edit written
into the store would be silently erased by the next build; written as an
override it is re-applied every time, carries its basis (file, row, timestamp),
is individually removable to restore the source-derived value (FR-26), and is
visible in the build manifest. This is what makes AC-30 (change 50 values,
then un-change them) mechanical rather than heroic. Overrides also inherit the
pre-value guard (FR-25): if the underlying vendor data has moved since the CSV
was exported, the build halts instead of applying an edit to a value it was
never derived from — the stale-edit case that a naive CSV overwrite cannot see.

**Format decisions (FR-137/139).** Every cell is written as text, UTF-8 with
BOM (so Excel opens it in Unicode without a wizard), `\r\n` line endings, all
fields quoted, and a leading `sku` column. Numeric-looking identifiers are the
hazard the profile measured firsthand — 13-digit EANs, zero-padded codes,
values like `15A-GW` that Excel reads as text but `8-1` that it reads as a
date — so the export writes a **companion `.types.json`** recording each
column's declared type and a per-cell fingerprint (length + hash) for identity
columns. On import, `csv_io` compares fingerprints: a cell whose value changed
in a way that matches a known spreadsheet mutation (trailing `.0` on an
integer, lost leading zeros, an ISO date where a code was, mojibake where a
`®` was) is classified **suspected tool damage** and refuses the import naming
rows and columns, rather than accepting 300 corrupted EANs as intentional
edits. A genuine edit to the same cell that doesn't match a damage signature
passes normally; the operator can force any specific cell with an explicit
allow-list flag, because a refusal the operator cannot clear through data
would violate FR-48.

**Scale.** One wide CSV per brand (322 rows × ~430 columns for Lindström is a
comfortable spreadsheet). `--fields` narrows it to a working set — the common
case is editing two or three columns across the catalogue, which is exactly
the S8 `Listing Updates` review-workbook pattern the operator already uses.

### 5.7 Families

`families.py` computes sets from declared rules (block ladder ∪ declared
twins for Lindström), stores one membership list per family with declared
order (FR-36..37), and projects per-row membership from it — so symmetry holds
**by construction** and the pairwise check (FR-73/AC-9) verifies the endpoint,
not the build.

---

## 6. Distribution chain design (Stage 5)

### 6.1 Run lifecycle

```
plan:    load build → adapter.fetch_existing() → ChangeSet (FR-61, 74)
gate:    G-EXISTING · G-CATEGORY · G-IMAGES · G-LIMITS · payload validation
         (FR-78..79, 123..124) → all reported at once, halt before write 0
snapshot: adapter.snapshot() + control assertion; refuse to write without it
         (G-SNAPSHOT, FR-88..91)
confirm: blast radius + directional anomaly; over-threshold ⇒ typed
         confirmation naming the measured figure (FR-80..82, AC-14)
arm:     --arm required for any write; --arm-live additionally for live
         (FR-70); staged order enforced: dry → batch N → full, same input
         hash (FR-68, FR-106, G-STAGED)
write:   per row: capture before-image → ledger row (pending) → write →
         ledger row (done) (FR-92, 66..67)
         pass 2: relationships, complete id map, members ∩ present SKUs,
         explicit [] for sentinel fields (FR-119, FR-65)
verify:  read back every written field, compare to intent, report
         expected-vs-observed and N-of-M coverage (FR-84..85, INV-2..3);
         never trusts the write's own success report (FR-86)
on mismatch: HALT, list affected rows, render rollback diff, wait (ADR-6)
report:  field→owner table, change set, assertions with measurements,
         verification result, rollback handle (FR-100)
```

An empty change set says so and exits without writing (FR-83). Deletion runs
(`remove`) follow the same lifecycle: exclusion-list driven (FR-45), before-
imaged, verified, reversible.

### 6.2 Change set and blast radius

`ChangeSet` = per-SKU, per-field `{before, after}` computed against live fetch
or a named snapshot — producible without arming (FR-74/INV-19). Blast radius:
rows touched, fields touched, per-field counts; numeric fields add magnitude
and direction (FR-80). Directional anomaly: >declared% of a field's changes
moving one way flags the §9.13 signature (FR-82/INV-20, AC-15). Thresholds
come from `thresholds.yaml` (starting proposal in SRS OQ-6). Built data is
treated as *capable of being behind the endpoint* (INV-21) — the diff, not
recency, is the authority.

### 6.3 Managed fields and ownership

`managed.yaml` declares the managed set (default: every mapped field, FR-49)
and the field→owner map. At run start the resolved field→owner table prints
and is enforced: an ownerless managed field fails the build naming the field
(FR-55/AC-6); two owners for one field is a config error (FR-54). CLI
`--fields`/`--rows` narrows any run (FR-75..76); `repair --fields` re-writes
ledger-complete rows (FR-77/AC-7). Unmanaged fields are drift-reported every
run with counts (FR-57, AC-26). Nothing anywhere refuses a field by code
(FR-48/50/51); omission-from-built-data is the only "don't write" (FR-52).

### 6.4 Rollback and restore

Rollback replays a run's before-images newest-first, shows the field-level
diff first and is refusable (FR-96), covers interrupted runs exactly to the
ledger's written rows (FR-94), restores only fields that run wrote (FR-93),
and is verified by the same read-back machinery (FR-97, AC-11..13). Snapshots
restore wholly or by row/field subset (FR-98). Retention is a declared policy,
nothing implicitly overwritten (FR-99, OQ-9).

---

## 7. Verification and control framework

```python
class Check(Protocol):
    id: str
    def measure(self, ctx) -> Measurement      # numbers, not verdicts (FR-101)
    def control(self, ctx) -> ControlResult    # proof it can fail   (FR-125)
```

- A `Measurement` carries observed counts and, for "N defects remain" claims,
  the before-count (FR-126/INV-15). A zero-rows retirement check must supply a
  **separate positive probe** as its control (FR-125 corollary).
- The **falsifiability harness** (ADR-7): every registered check has a fixture
  corruptor in `tests/corruptors/`; CI runs each corruptor and asserts the
  check goes red (FR-87, AC-17/20). A check without a corruptor fails CI.
- **Storefront probes** (BigCommerce acceptance): fetch a rendered category
  page and PDP, assert card `data-*` attributes and non-zero decoded image
  count (FR-127/AC-25); every probe sends browser-equivalent
  `Accept-Language` (FR-128) and the harness records the with/without-header
  status pair once per environment.
- Every applied operator/design ruling is logged with per-clause evidence,
  `VERIFIED` only with evidence for that clause alone (FR-130).

---

## 8. Endpoint adapters

### 8.1 Adapter protocol (`endpoints/base.py`)

```python
class EndpointAdapter(Protocol):
    name: str
    def capabilities(self) -> Capabilities
        # limits (field lengths, image counts, rate), sentinel_empty_fields
        # (e.g. related_products: []), partial_success_codes (e.g. 207),
        # sub_resource kinds, id semantics
    def snapshot(self, scope) -> Snapshot                    # FR-88..90
    def fetch_existing(self, skus) -> dict[sku, RemoteRow]   # FR-61
    def create(self, payload) -> RemoteId
    def update(self, remote_id, payload) -> None
    def delete(self, remote_id) -> None
    def verify(self, remote_id, expected_fields) -> FieldReport  # FR-84
    def restore(self, before_image) -> None                  # FR-93
```

Core knows only this protocol (FR-58). The **CSV/JSON export adapter**
implements it against the filesystem, proving the abstraction with no core
change (FR-60, AC-19) and doubling as the offline test double's shape.

### 8.2 BigCommerce adapter

Targets **Catalog v3** (NFR-15); every v2-era semantic is declared, not
buried:

| Concern | Design |
|---|---|
| Upsert | `fetch_existing` by SKU page-batched; create only on confirmed absence (FR-61); pre-existing matches reported with ids (G-EXISTING) |
| Custom fields | On update: strip `custom_fields` from the product body; GET live fields; match **by name**; PUT existing, POST missing, DELETE duplicates and system-owned strays (FR-63) — the id-less-PUT-appends trap is documented at the call site |
| Images | Provenance fingerprint (source URL/hash) written into image metadata; reconcile by fingerprint; never delete an image without a fingerprint match (FR-64/INV-18); HEAD-check URLs pre-write (FR-124) — BC fails fetches quietly |
| Relationships | Second pass over complete id map; members ∩ present SKUs; **explicit `[]`** for family-less products — `related_products` is a declared `sentinel_empty_field` because BC's V2 `[-1]` auto-determine invents relations (FR-65, FR-119); truncation measured, written-vs-returned, on the largest family (FR-120, AC-28) |
| Categories | Resolve names → ids up front; unresolvable ⇒ halt; never auto-create (FR-123) |
| Template routing | `ct_page_type` custom field only; never `layout_file` (Blueprint-only no-op on Stencil); absent ⇒ default archetype, fails closed (FR-121) |
| Hidden prices | `is_price_hidden` always paired with `availability:"disabled"`; non-purchasability surfaced in the report (FR-122) |
| Rate/partial | Token bucket ≈450 req/30s, bounded concurrency on catalog endpoints, backoff on 429 (FR-69); 207 declared success (FR-71) |
| Environments | live / sandbox / store-hash hostnames resolved from `endpoints.yaml`; asset paths remain relative (FR-118) so one payload is correct on all three |

### 8.3 Adding a channel

New adapter = new package implementing §8.1 + a `capabilities()` declaration +
an entry-point registration. No core edits (AC-19). Candidate second real
channel per SRS OQ-15.

---

## 9. Brand pack design (worked shape)

Schemas in `docs/schemas/`; illustrative Lindström fragments:

```yaml
# normalize.yaml — the brand's normalization function (SRS §4.3 note):
# engine operations, selected and parameterized per brand
keys:
  rule: trim-only              # never alter a key's interior (TL 15A-GW ≠ TL 15AGW)
conventions:
  decimal_comma: [technical_details_matrix]   # sources using European decimals
  unit_in_value: [Length, "Tip Width, mm"]    # parse unit from the cell, not header
encoding:
  expect: [latin-text, "®", "™", "°", "·"]    # codepoint sweep tolerates these
  reject_mojibake: true

# fields.yaml — alias chain + unit-bearing column (FR-18, FR-21)
length_mm:
  primary: {source: S1, column: "Length"}          # exact header, commas legal
  aliases: [{source: S2, column: "Total length"}]
  unit: {parse: in-value, expect: [mm, in]}
  confirmed: Y                                     # FR-105 per-field switch

# derive.yaml — precedence + band + pair (FR-27/28/114)
facets:
  head: {rule: precedence, of: [head_type, group]} # ELSE, never both
  cap:
    rule: band
    input: capacity_mm
    bands: [{lt: "0.8", value: fine}, {lt: "1.25", value: medium},
            {lt: "1.6", value: heavy}, {else: xheavy}]
    boundary: lower-inclusive                      # which side joins (FR-28)
    display_pair: cap_disp                         # from capacity_raw verbatim
families:
  rule: block-ladder
  union: twins.csv                                 # handle twins, declared
  order: mpn-numeric

# managed.yaml — §4.6
managed: all-mapped
unmanaged: [is_visible, inventory_level]           # admin-owned; drift-reported
owners: {product-fields: catalog, prices: catalog, custom-fields: catalog,
         images: media, related_products: relations}

# endpoints.yaml
bigcommerce:
  environments: {sandbox: {...}, live: {...}}      # never defaults to live
  page_type_value: tool
```

The Lindström pack is built from the shipped state: 11 facet keys, **16 spec
keys including `tt bh bw`** (FR-136), chapter rails per the shipped theme
(SRS Appendix A), and inherits the `[-1]` fix rather than re-deriving it
(FR-135, OQ-2).

---

## 10. CLI design

```
pim <brand> build                      # stages 1–4, no network
pim <brand> export [--build ID]        # regenerate canonical export
pim <brand> export-csv [--fields ...] [--rows @list] [-o FILE]   # bulk-edit sheet
pim <brand> import-csv FILE [--apply] [--allow-damage col:sku,…] # diff → overrides
pim <brand> diff --against live|snap   # change set, no arming needed (FR-74)
pim <brand> snapshot  --env sandbox
pim <brand> publish   --env sandbox --dry-run
pim <brand> publish   --env sandbox --limit 10 --arm
pim <brand> publish   --env live --arm --arm-live [--new|--update|--delta B|
                                                  --fields f1,f2 --rows @list]
pim <brand> repair    --fields msrp --arm ...
pim <brand> remove    --arm ...
pim <brand> verify    --env live [--fields ...]
pim <brand> rollback  <run_id>         # shows diff, asks, verifies
pim <brand> restore   <snapshot_id> [--rows ...|--fields ...]
pim <brand> runs / builds / report <run_id>
```

Brand always explicit (FR-3); environment always explicit (FR-5); dry-run is
the default posture (NFR-11); `--arm`/`--arm-live` per FR-70; staged-order
enforcement refuses `publish` (full) without a verified batch for the same
input hash (FR-106). Exit codes: 0 clean · 1 halt (gate/validation) ·
2 verification mismatch (halted, rollback offered) · 3 refused (unarmed,
unstaged, snapshot unavailable).

---

## 11. Testing strategy

| Layer | What | Proves |
|---|---|---|
| Unit | rule vocabulary, packing, units, encoding, banding boundaries — against canonical fixtures, no vendor files, no network | NFR-12, FR-28 boundary sides |
| Golden | build a fixture brand twice → byte-identical export; export hash pinned | FR-41/AC-3 |
| Gates | every §7.4 gate red on its corruptor fixture, green clean | AC-17, FR-87 |
| Regression | one fixture per SRS §9 failure (9.1–9.13), including the 288-down directional fixture and the `[-1]` sentinel fixture | AC-22, AC-15 |
| Full-loop | fake in-memory endpoint: publish → verify → rollback → verify; interrupted-run resume; repair; exclusion persistence | AC-4..13, NFR-4..6 |
| Generalisation | synthetic second brand, config only, zero core diffs; 3-source and 9-source packs | AC-1/2/23 |
| Live acceptance | sandbox: staged publish, rendered-storefront probes with Accept-Language, `[-1]` store-wide count vs before-count, truncation measurement | AC-24/25/28, FR-127..128 |

---

## 12. Implementation roadmap

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **M0 — Skeleton** | repo layout, config models + schema gen, CLI shell, CI with import-linter + falsifiability scaffold | G-PACK red/green; AC-27 |
| **M1 — Core build** | ingest, merge, aliases, units, encoding, overrides; SQLite store + canonical export + build diff; **CSV export/import round trip** | golden determinism (AC-3); FR-20 fixture; provenance report; **AC-29..32** |
| **M2 — Derivation** | rule vocabulary, facets, completeness, packing, families | G-VOCAB/G-COMPLETE/G-DELIM/G-LIMITS red/green; Lindström pack builds and matches shipped facet/spec keys |
| **M3 — Change management** | changeset vs snapshot/live, blast radius, directional anomaly, managed/owner enforcement | AC-6, AC-14, AC-15 (fixture) |
| **M4 — Publish + safety** | fake-endpoint full loop: ledger, before-images, staged runs, verify, halt-and-wait, rollback, repair, remove | AC-4..13, AC-18, NFR-4..6 |
| **M5 — BigCommerce adapter** | §8.2 complete; CSV adapter; sandbox acceptance | AC-19..21, AC-24/25/28 on sandbox |
| **M6 — Lindström migration** | pack reproduces live; ledger/exclusion import; v1 side-by-side; MSRP change+rollback demo | FR-107..110, FR-135..136, zero unintended diffs vs live; OQ-1 resolved with operator |

Each phase lands with its tests; no phase starts against unresolved blocking
OQs (M6 needs OQ-1/OQ-2; M2 wants OQ-4's field shape).

---

## 13. Traceability (requirement group → design element)

| SRS | Design |
|---|---|
| FR-1..5 (brand config) | `config/`, ADR-4, §9 |
| FR-6..13, 111 (ingest) | `ingest/`, §5.2 |
| FR-14..26 (merge/normalise) | `normalize/`, §5.3–5.4 |
| FR-27..38, 112..118 (derive/pack) | `derive/`, ADR-5, §5.5–5.6 |
| FR-39..47 (store) | `store/`, ADR-2, §4.2–4.3 |
| FR-137..139 (CSV bulk edit) | `store/csv_io.py`, §5.6, §10 CLI |
| FR-48..57 (mutability/ownership) | §6.3, `managed.yaml` |
| FR-58..71, 119..124 (publication) | `publish/`, `endpoints/`, §6.1, §8 |
| FR-72..77 (modes) | §10 CLI |
| FR-78..87, 125..128 (validation/verification) | `changeset/`, `verify/`, §6.2, §7 |
| FR-88..99, 129 (backup/rollback) | `publish/snapshot.py`, `rollback.py`, §6.4 |
| FR-100..103, 130 (reporting) | `report/`, §7 |
| FR-104..105 (mapping is data) | `fields.yaml` `confirmed`, §9 |
| FR-131..134 (truth) | omission-by-default in derive; defect routing in `report/`; no auto-resolution anywhere |
| FR-107..110, 135..136 (migration) | M6, §9 |
| NFR-1..15 | ADR-1/2, §4.3, §11 |
| INV-1..21 | §7 framework + `tests/corruptors/` + regression fixtures |
| AC-1..28 | §11 test map + §12 exit criteria |

---

## 14. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Rule vocabulary too small for brand #2 | ADR-5 makes gaps loud (unexpressible rule = core feature request); OQ-8 sizes brand #2 early, before M2 hardens |
| SQLite/export divergence | export is a pure projection; corrupt-store check (FR-39); no hand edits anywhere (FR-43) |
| BC API drift (limits, sentinel behaviour) | all BC semantics in `capabilities()` + adapter docs; FR-120 measures instead of assuming |
| Windows file locking on vendor sheets | temp-copy reads (FR-9), tested with a held-open fixture |
| Operator-attended halts blocking long runs | halts front-load into gates before write 0 (FR-79); mid-run halt only on verification mismatch (D-3), which must be attended anyway |
| The 292-vs-346 count ambiguity poisoning migration | OQ-1 blocks M6; migration diffs against live, not against either document |

---

*End of CT-PIM-ARCH-001 v1.0.*
