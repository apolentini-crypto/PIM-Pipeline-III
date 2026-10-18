# V1 Loader Assessment — Is the Lindström Load Expandable to Other Brands?

| | |
|---|---|
| **Document ID** | `CT-PIM-V1-ASSESS-001` |
| **Date** | 2026-08-19 |
| **Assessed** | `…\spreadsheet-dev\Lindstrom Data Load\` — `pipeline/` (5,594 lines across 9 modules + 2 JSON), `tools/` (17 utilities), config artifacts |
| **Question** | Operator, 2026-08-19: *"unclear if it is expandable, modifyable for other brands, has the flex I am looking for."* |
| **Method** | Firsthand code inspection — every structural claim below cites file:line or a measured count from the actual source |

---

## 1. Verdict

**As a codebase: no.** The v1 loader is not expandable to a second brand by
configuration, and it structurally lacks all three of the flexibility
guarantees you named on 2026-08-19 (unrestricted create/update/delete;
mandatory backup/rollback; per-field change selection). Adding a brand means
writing and re-testing Python, not describing the brand.

**As raw material: substantially yes.** About a fifth of what "the v1 loader"
really is turns out to be *data and operational discipline*, not code — and
that part transfers almost directly into the v2 brand pack. The right read of
v1 is: **a successful single-brand load whose hard-won rules must be
harvested, and whose structure must not be inherited.** This is the same
conclusion both requirement specs reached; the evidence below is now verified
against the code itself rather than quoted.

---

## 2. Why it does not expand (measured evidence)

### 2.1 The brand is woven into the code, not declared

| Evidence | Where |
|---|---|
| Absolute OneDrive source path and six fixed source files `S1..S6` hardcoded | `config.py` (SRC path; `S1_PRICEBOOK` … `S6_ESD`) |
| Expected shape constants that halt on drift: `ROSTER_COUNT = 322`, `SCRAPE_OK = 312`, `SCRAPE_404 = 10`, `PRICED_COUNT = 302`, `UNPRICED_COUNT = 20` | `config.py` — right instinct (expectations), wrong home (code) |
| `BC_SKU_PREFIX = "59-"`, the 11 `L2_CHAPTERS` by name, capacity-band ladder, price buckets, `SERIES_CHAPTERS`, `SERIES_BY_DIGIT = {"7": "sup", "8": "s80"}` | `config.py` |
| Brand-name / `59-` literals across modules: config 19 · bc_loader 9 · price_refresh 7 | grep counts, all 9 modules |
| Hardcoded Lindström counts appear in 8 of 9 modules | grep counts |

### 2.2 Derivation is Python, so a new brand is a new program

`build_library.py` (1,008 lines) implements every rule as code:
`derive_cut()` (trademark parsing), `spec_fields_for()` (~94 lines of
per-chapter spec packing), `facets_for()`, `seo()`, `derive_related()` (family
ladder), plus `FACET_KEYS` as a module constant. `normalize.py` carries
RX/HS SKU-prefix rules in `startswith()` calls. None of this is reusable for
a brand whose facets differ — it is Lindström's product logic transcribed
into Python. (The v2 answer is the closed rule vocabulary, ADR-5: the *rule
types* here — precedence, banding, slug, prefix-map, block-ladder — are
exactly the vocabulary the rules engine must express; the *rule instances*
move to `derive.yaml`.)

### 2.3 It fails all three of your named flexibility requirements — in code

| Your requirement | v1 reality |
|---|---|
| **Nothing unwritable** | `bc_loader.py:525-531` — `build_body()` pops `price`, `retail_price`, `custom_fields` on every update. These fields are unreachable by this tool, permanently, by design. (SRS §9.3: this is what made MSRP owned-by-nobody; the `price_refresh.py.bak-msrp` file sitting in the repo is the scar of patching around it.) |
| **Backup/rollback mandatory** | The pipeline has no snapshot, no before-images, no rollback. `snapshot_live.py` and `diff_vs_live.py` exist as separate, manually-run tools bolted on later; the ledger (`build/ledger.csv`) records actions but not prior values, so nothing a run did can be reversed from it. |
| **Choose exactly what changes** | No field selection exists. `do_load` writes the whole body (minus the popped fields); prices go through a different program (`price_refresh.py`, 695 lines) with its own ledger — the split write authority that caused the two-week MSRP defect. There is no `--fields`, no managed/unmanaged concept, no repair mode. |

### 2.4 Endpoint coupling

`bc_loader.py` is 1,541 lines mixing what v2 separates into five components:
gates (G4/G5/G6), payload building, image sync, custom-field reconciliation,
channel/template assignment, relations, and verification — all speaking raw
BigCommerce paths. A second channel (or even a BC API change) touches the
same file that owns load orchestration.

---

## 3. What v1 gets right — and what to harvest

The discipline in this codebase is genuinely good, and most of it is already
codified in the baseline SRS. Concretely reusable:

| Asset | What it is | Where it goes in v2 |
|---|---|---|
| `vocab.json` | The frozen facet vocabulary, 11 keys, exactly the FR-30 shape | `brands/lindstrom/vocabulary.json` — near-verbatim |
| `field_map.json` + `LINDSTROM-BC-FIELD-MAPPING.xlsx` + `read_mapping.py`'s CONFIRMED discipline | Declarative field mapping with `lib`/`const` source, `transform`, `load_on`, `confirmed` per field | Seed of `fields.yaml` + `managed.yaml` (FR-104/105) — this is the one part of v1 that is already "mapping is data" |
| `unit_overrides.json` | 11 logged, reversible corrections with arithmetic derivations | `overrides/` (FR-25/26, FR-132) — format is already right |
| `exclusions.csv`, `category_map.json` (+ its "ids are per-store" note), `spec_docs_map.json`, `_esd_delta.json` | Exclusion list; gate-produced category ids; docs map; ESD delta | Exclusions and docs map import directly (FR-108); category resolution stays name-based per environment (FR-123) |
| Gate practice: G5 never-auto-create categories, G4 existing-SKU query, G6 image HEAD-checks; `reconcile_custom_fields()` matching by name (PUT/POST/DELETE) | Correct semantics, proven live | The BC adapter (§8.2) reimplements the same semantics behind the interface |
| `tools/verify_*` (ct_page_type with a non-line control SKU, msrp, callforprice), `ruling_scan.py` | Post-hoc verification with controls | The Check framework (§7) absorbs their assertions as first-class checks |
| The measured-expectations instinct (`ROSTER_COUNT = 322` with "measured, not copied" comment) | Right idea, wrong home | `expectations.yaml` (FR-40) |
| Config comments as institutional memory (band boundary rulings, series revert, holdback release history) | Decision provenance | Already captured in the SRS WHYs and the ruling ledger practice (FR-130) |

Rough proportion: of ~5.6k pipeline lines, the **structure** (readers wired to
six sources, derivation-as-code, monolithic loader) is not carried forward;
the **semantics** (gate rules, reconciliation-by-identity, halt conditions,
verification assertions) are carried as requirements the SRS already encodes;
and the **data artifacts** (~all of the JSON/xlsx config) move into the brand
pack nearly as-is.

---

## 4. Could v1 be refactored instead of replaced?

Considered and rejected — same conclusion as both source specs, now with the
code in view. To make v1 brand-flexible you would need to: externalize every
derivation rule (rewrite `build_library.py`), remove the field pops and build
the diff/blast-radius/verify/rollback machinery that makes that safe (§0.2 —
they are one mechanism), split `bc_loader.py` into adapter vs orchestration,
unify the two write paths, add before-images and per-run reversal, and add
managed-field declarations. That touches every load-bearing line of all three
major modules — a rewrite wearing a refactor's name, but performed *inside*
the only tool currently able to load the live store. The v2 plan (M0–M6)
builds alongside instead, runs v1 and v2 side by side (FR-109), and proves
equivalence before cutover — including the MSRP change-and-rollback
demonstration v1 can perform in neither direction (FR-110).

**One nuance worth naming:** v1 stays in service as-is until v2's Lindström
build diffs clean against live (FR-107, phase M6). Nothing here says stop
using v1 for interim operational needs; it says stop *investing structure*
in it.

---

## 5. Disposition summary

| Keep using (until M6 cutover) | Harvest into the brand pack | Do not carry forward |
|---|---|---|
| v1 as the operational loader for interim Lindström needs | vocab.json · field_map.json + mapping workbook · unit_overrides.json · exclusions.csv · spec_docs_map.json · expectations (as data) · ledger + remote ids (FR-108) | Derivation-as-code · six fixed readers · field pops (FR-50 prohibits) · split price/product write paths · monolithic bc_loader.py · counts/paths/prefixes in code |

The three flexibility guarantees you asked about are not retrofit targets on
v1 — they are the design center of v2 (§4.6, §4.9, §4.10 of the SRS), and
AC-5/AC-8/AC-11 are the tests that prove each one end-to-end.
