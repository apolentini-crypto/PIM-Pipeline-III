# Lindström Source Data Profile

| | |
|---|---|
| **Document ID** | `CT-PIM-DATA-001` |
| **Date** | 2026-08-19 |
| **Status** | Measured profile of the actual source files — input to the Lindström brand pack (`CT-PIM-ARCH-001 §9`) |
| **Profiled from** | `…\Brand Distribution\Lindstrom\2026\Data to Merge\` (14 data files) and `…\spreadsheet-dev\Lindstrom Data Load\` (v1 loader artifacts) |
| **Method** | Every sheet, every column, every row read programmatically (openpyxl / csv / json); counts below are measured, not quoted from any spec |

This document records what the Lindström dataset **actually contains** — the
column inventory, key spaces, coverage, and format hazards — and what each
finding implies for the brand pack. The dataset was assembled **additively over
many files**: a vendor PIM export was progressively joined with a price book,
a category assignment workbook, an ESD adjudication, a site scrape, an image
link audit, and an operational listing-updates workbook. That lineage is the
central fact of the profile: **no single file is complete, and every file is
authoritative for something.**

---

## 1. File inventory and lineage (the additive assembly)

| # | File | Role in the assembly | Keyed by | Rows |
|---|---|---|---|---|
| S1 | `Lindstrom 2026 - Merged Product Data and Price Book (FIXED).xlsx` :: `Hoja1` | Vendor PIM export (46 cols) **with the price book appended side-by-side** (7 more cols) — a two-block sheet | `PRODUCT` (356) / `Product Code` (335) | 358 |
| S1b | same file :: `Not Complete-v1` | Partial earlier merge attempt; 116 rows, only 24 with vendor data; **16,350 phantom columns** of formatting junk | `PRODUCT` | 116 |
| S1x | `…(FIXED).BACKUP-20260720.xlsx` | Snapshot of S1 — **373 rows vs the current 358, and the two differ by content hash** | `PRODUCT` | 373 |
| S2 | `Lindstrom - Category Assignments.xlsx` | Authoritative category tree (11 L2 · 46 L3) + per-SKU assignment | `Product (SKU)` (322) | 323 |
| S3 | `scraper_output.json` / `.csv` | Vendor-site scrape: name, HTML details, meta description, image URLs, **`specs{}` dict — 84 distinct spec keys** | `product_code` (322) | 322 |
| S4 | `technical_details_matrix.xlsx` / `.csv` | S3's specs pivoted wide: 88 columns, very sparse tail | `product_code` (312) | 313 |
| S5 | `Lindstrom - Q80 - 2026 Price Book - 8-1-26.xlsx` | 8-1-2026 price book: list, Q80 discount (45%), net, weight (LBS), Future Discontinued=`X`; **header on row 2** | `Product Code` (374) | 376 |
| S6 | `Lindstrom Image Links - FULL 322.xlsx` | Long-format asset audit: 3,907 rows = 322 products × 8 URL types, with `NOT FOUND` / `LOCAL FILE` notes | `Product Number` (322) | 3,908 |
| S7 | `Lindstrom - ESD Determination.xlsx` | Evidence-based ESD adjudication (ICONS-token rule), with legend, status, and change-tracking columns — an **operator ruling artifact**, not vendor data | `BC SKU` (322, **321 distinct — see §4.1**) | 323 |
| S8 | `Listing Updates.xlsx` | Operational change management: 6 sheets (Add to Store 35 · Excluded 48 · price Review 312 with Apply YES/SKIP/REVIEW · Not in Price Book 25 · In-Book-Not-In-Store 83 · Expansion-Categories) | `mpn` / `product_code` | — |
| S9 | `Missing Pricing.xlsx` | 20-SKU subset lacking prices (the call-for-price set's ancestor) | `PRODUCT` | 21 |
| — | `Import File Register.xlsx` | Tony's own register of the files (6 entries, one `tbd`) | — | 9 |
| — | `Publication Files/` (12 PDFs) | The physical documents that `Certificates` / `Manuals` columns reference | filename | — |
| — | `STOREFRONT-DATA-CONTRACT.md`, `CATEGORY-TILE-IMAGES.md` | Theme contract + category tile notes (docs, not data) | — | — |

**v1 loader artifacts** (in `Lindstrom Data Load\`) that are effectively part of
the dataset: `LINDSTROM-BC-FIELD-MAPPING.xlsx` — the operator-confirmed
source→BC field mapping workbook (72 BC fields, **275 registered source
columns across S1..S6**, derived-fields sheet) — plus `vocab.json` (frozen
facet vocabulary), `unit_overrides.json` (11 transposed mm/in corrections with
derivations), `category_map.json` (store-hash-scoped BC category ids),
`spec_docs_map.json`, `_esd_delta.json`, and an (empty) `exclusions.csv`.

### What "additive" means concretely

The dataset was built in layers, each layer keyed slightly differently and each
correcting or extending the last: vendor PIM export → price book pasted
alongside (S1's second block) → categories assigned (S2) → site scraped for
specs and images (S3/S4) → asset URLs audited (S6) → ESD adjudicated against
icon evidence (S7) → prices reviewed and staged (S8) → gaps tracked (S9,
`Missing Pricing`). Later files **override** earlier ones where they overlap
(S7's ESD verdict outranks anything inferable from S1/S3; S8's Review sheet
outranks S5 for what actually gets applied). The brand pack must encode this
as declared precedence, not file order.

---

## 2. Key spaces and joins (measured)

```
canonical MPN set     : 322  — S2, S3, S6 agree EXACTLY (322 = 322 = 322 ✓)
tech matrix (S4)      : 312  — strict subset of the 322; the 10 missing are
                              S3's scrape_status = error_404 products (10)
S1 Hoja1 PRODUCT      : 356  — the 322 + 34 price-book-only codes appended
                              (expansion candidates: 815, 8211, 8247…)
price book (S5)       : 374  — raw key join to the 322: 179 match
                              normalized (strip spaces/hyphens): 186
                              → ~136 of 322 need the association table
BC live listings (S8) : 312  — Review sheet carries bc_sku + bc_product_id
```

Join-shape facts the pack must declare:

- **BC SKU rule:** `59-` + MPN (confirmed in mapping workbook: `CONST '59-' +
  S2|Product Categories|Product (SKU)`).
- **The price book speaks a different code dialect.** 115 of the 322 MPNs are
  `TL `-prefixed tweezer codes (`TL 15A-GW`); the book writes them compact
  (`15AGWM`). S8's Review sheet already embeds the resolved association
  (`join` column: `exact` / `hs` / `tl`) — that column **is** the seed of
  `joins.yaml`'s association table.
- **S1's Hoja1 is a declared two-block sheet** (FR-12): columns 1–46 are the
  vendor PIM block keyed on `PRODUCT`; columns 48–54 are the price-book block
  keyed on `Product Code`, row-aligned by a `True/False` marker column (col 47,
  header blank). Column 48 ≠ column 1 on 34 rows.
- **Header row varies:** S5 headers are on row 2 (row 1 blank). Header row is
  per-source declaration, exactly as FR-6 requires.

---

## 3. Column inventory highlights

### 3.1 S1 Hoja1 — vendor PIM block (46 columns, 322 rows populated)

Identity/classification: `PRODUCT`, `en_US#BRAND`, `EAN CODE` (321 distinct of
322 — one duplicate EAN), `PRODUCT BLOCK` (209 distinct — the family-ladder
source), `en_US#CHAPTER` (11), `en_US#SECTION` (46), `en_US#GROUP` (55).
Content: `en_US#SHORT DESCRIPTION P` / `PB`, `en_US#PRODUCT DETAILS`
(pipe-delimited bullet lists), website/PDF URLs (322 each). Assets:
`PRODUCT IMAGE NAME`, `ADDITIONAL IMAGE NAME`, `APPLICATION IMAGE NAME`,
`DRAWINGS NAME`, `Certificates`, `Manuals` — all **pipe-delimited multi-value
cells** — `Exploded Views` (empty, 0 of 322). Logistics: MOQ/qty (constant
`1`), `UNITWEIGHT kg`, `PACKWEIGHT` (**value carries its own unit:**
`0.0060 kg`), pack/unit dims in mm (headers misspelled: `PACKLENGHTmm`,
`UNITLENGHT mm`, `PACKWIDT mm`), `UNIT NET WEIGHT` (**one negative value:
−0.0280 — a plausibility-bound violation, INV-14**), ECOTYPE/ECOWEIG columns,
`EAN BOX CODE` (187), `STANOCU`/`CUSTOM STATISTICAL NO` (duplicated columns,
5 distinct HS codes), country of origin (317 code / 322 name — **5 rows have a
name but no code**), `YOU TUBE LINK` (43).

### 3.2 S3/S4 — the spec surface (84 keys, heavily faceted by chapter)

Coverage tiers across 322 products:

| Tier | Keys (examples) | Coverage |
|---|---|---|
| Near-universal | `Weight` (299) | one key, five sibling unit forms elsewhere |
| Cutter/plier core | `Length (mm)` 164 · `Lenght (in)` 157 (sic) · `Head Height/Width/Thickness (mm/in)` ~154–157 · `Head Type` 155 (22 distinct) · `Head Size` 155 (XS/S/M/L) · `Bevel / Cut Result` 131 (6) · `Cutting Capacity (mm)/(in)` 128 · `Resistivity` 128 (always `Dissipative`) | the facet backbone |
| Tweezer block | `Tip Width, mm` 108 · `Tip thickness, mm/in` 108 · `Pincet shape` 104 (70 distinct) · `Tweezer Height/Width` 104 | tweezers only |
| Long tail | 60+ keys with n ≤ 40 (`Edge Width` 40, `Jaw Surface` 26, torque ranges, pentalobe sizes, `Cutting Capacity 1000V` n=1…) | sparse, chapter-specific |

The tail is why FR-112 (emit every key the chapter declares, and only those)
matters: most spec columns apply to a small declared subset, and
over-application is invisible without an absence-set assertion (FR-29).

### 3.3 S8 Listing Updates — change management as data

`Review` (312 rows): old/new price and cost with Δ%, margins, sale prices,
**`Apply` ∈ {YES, SKIP, REVIEW}**, `join` ∈ {exact, hs, tl}, and a `flags`
column carrying exactly the defects the SRS legislates for: *"TWIN with
59-HS-7290: both map to book '7290' — approve ONE"*, *"NO-BOOK-MATCH
(renumbered? line dropped? ask Lindström)"*. This workbook is the operating
model of §4.8 already in embryo — review-workbook round-trip (answers OQ-12's
shape in practice), blast-radius eyeballing, explicit apply flags.

---

## 4. Defects and hazards found (new findings first)

### 4.1 ⚠ NEW — BC SKU collision inside the canonical 322

`TL 15A-GW` and `TL 15AGW` are **two different MPNs** in S2/S7 that both
produce **`59-TL 15AGW`** as BC SKU (S7's BC SKU column: 322 values, 321
distinct). Any SKU-keyed upsert treats them as one product — one will
silently overwrite the other. Related: S8 notes `Same as 15A-GW?` against
`15AGWM`. **Needs an operator ruling** (are these one product under two codes,
or two products needing distinct SKUs?) before the Lindström pack is built.
This is INV-9/INV-10 live in the current data, not history.

### 4.2 ⚠ NEW — S1 and its backup diverge

`(FIXED).xlsx` has 358 rows; `(FIXED).BACKUP-20260720.xlsx` has **373** and a
different hash, and the backup's file mtime is *newer* than the primary's.
Which is authoritative must be declared (INV-12 — hash-verify mirrored
artifacts); the build manifest's source-hash recording (FR-11) will catch any
future drift automatically.

### 4.3 Format hazards (each maps to an SRS requirement)

| Measured fact | Requirement it exercises |
|---|---|
| 1,787 of 4,995 tech-matrix cells carry the unit **inside the value** (`133.5` vs `170 mm` vs `4,33 in` under the same header family); 36 of 88 headers carry a unit suffix; some columns have both | FR-21 (parse unit in-value), FR-8 |
| **535 spec values use decimal commas** (`0,08 mm`, `4,72 in`, `7,87 in`) | FR-22 |
| Headers containing commas: `Tip Width, mm` · `Tip thickness, in` · `Tip thickness, mm` | FR-111 (never normalise headers) |
| Near-duplicate headers that are **different columns with different data**: `Tip Width (mm)` (127 rows) vs `Tip Width, mm` (108 rows, tweezers); `Total Length` (1) vs `Total length` (17); `Lenght (in)` misspelled alongside `Length (in)` | FR-111, alias chains FR-18 |
| Trailing space in a header: `'Description '` (S5, S1 block 2) | FR-111 byte-exact matching |
| `#NAME?` Excel formula errors shipped as cell values (3 cells: `Distance screw end`, `Min T-handle width`, `T-handle lenght`) | FR-78 validation; treat as empty + report |
| EAN read as float renders `7314150103003.0` (observed in the mapping workbook's own sample) | FR-8 (text by default) |
| Legitimate non-ASCII that must survive round-trip: `®` (149), `™` (45), `°` (28), `·` (8, in `N·m`), en-dash (5) | FR-24 codepoint checks — verify by codepoint, don't strip |
| Pipe `\|` as multi-value delimiter inside S1 asset/detail cells while `\|` is also `spec_docs`' packing delimiter | FR-33/FR-116 delimiter safety |
| Negative `UNIT NET WEIGHT` (−0.0280) · one zero-weight SKU · `Weight` expressed in **five unit forms** across sources (g, LBS, oz, Kg, kg) | INV-13/14 cross-check + plausibility bounds |
| 10 products `scrape_status = error_404` (the "dead vendor URL" held-back set in S8) | FR-46 holds with reason; FR-124 |
| `Resistivity` is constant `Dissipative` (128 rows) — carries no ESD signal | FR-131 corollary: esd never inferred from resistivity |
| S1b `Not Complete-v1` reports 16,350 columns (formatting ghosts) | reader must bound reads by declared range (FR-6) |
| Category ids in `category_map.json` are **store-hash-scoped** (`_note` says non-portable) | FR-123 resolve-by-name per environment, never reuse ids |

### 4.4 Confirmations of spec claims (now measured firsthand)

The `130 mm`/`4,72 in` mixed-unit single column: **confirmed** (`Length`, 121
rows: `170 mm`, `4,33 in`, `2,56 in`). Alias-column dependency: **confirmed**
(`Length (mm)` covers only 164 of 322 — the rest need the `Length`/
`Total length` chain; tweezer tip widths live only in `Tip Width, mm`).
The `8211`-in-`RX8211` name-match trap, the `15AGWM ↔ TL 15A-GW` association,
HS/TL join dialects: all visible in S8's join/flags columns. The transposed
mm/in cells: `unit_overrides.json` holds 11 SKUs (HS-8140…HS-8586), each with
before/after and the arithmetic derivation — exactly the FR-132 logged,
reversible override shape. The U+00BA-for-degree defect cited in the specs was
**not found** in these files (28 correct U+00B0 degree signs present) — it was
presumably already corrected upstream; the codepoint sweep stays (FR-24).

---

## 5. What this profile settles for the brand pack

**sources.yaml** — nine declared sources (S1 with two blocks, S1b ignored or
declared optional-diagnostic, S5 with `header_row: 2`, S3 as json, S4 as xlsx,
S6 long-format, S7, S8 as override/hold/review inputs, S9 diagnostic). The
backup file is *not* a source (one declared authority per file, §4.2).

**joins.yaml** — key function: uppercase, strip spaces/hyphens for book
matching **only as a candidate generator**; the actual mapping comes from the
declared association table seeded from S8 `Review[mpn, book code, join]`
(300 resolved pairs). The `59-` SKU construction rule. The `TL 15A-GW` /
`TL 15AGW` collision blocks pack completion until ruled (§4.1).

**fields.yaml** — the v1 `LINDSTROM-BC-FIELD-MAPPING.xlsx` already expresses
per-field source selectors (`S1|Hoja1|EAN CODE`), fallbacks, transforms and
CONFIRMED status for 72 BC fields over 275 registered source columns — it is
the direct ancestor of `fields.yaml` and should be imported, not rewritten.
Alias chains to declare (primary → fallbacks): length `Length (mm)` →
`Length` → `Total length`/`Total Length`; tip width `Tip Width (mm)` →
`Tip Width` → `Tip Width, mm`; weight `Weight (g)` → `Weight` → `Weight (oz)`
→ S5 `Weight (LBS)` (with declared unit conversions and cross-check, INV-13).

**derive.yaml** — facet sources confirmed against real distributions:
`head` from `Head Type` (22 distinct) ELSE `en_US#GROUP` (55); `size` from
`Head Size` (XS/S/M/L exactly); `cut` from `Bevel / Cut Result` (6 distinct)
else title trademark; `cap` bands from `Cutting Capacity (mm)` upper bound
(128 rows); `tipw` bands from `Tip Width, mm` (108); `esd` **only** from S7's
adjudicated `ESD Safe` column (never ICONS re-derivation, never Resistivity);
`block` from `PRODUCT BLOCK` (209 distinct); family ladder from
`PRODUCT BLOCK` ∪ S8 twin flags. `vocab.json` from the v1 pipeline is the
frozen starting vocabulary (FR-30).

**Change-management inputs** — S8 is not product data; its sheets map to:
Add to Store → FR-44 operator-supplied additions; Excluded → FR-45 exclusion
list; Review + Apply → the FR-74 change-set review round-trip with S8's
YES/SKIP/REVIEW as the confirmation record; held-back dead-URL set → FR-46
holds with reason.

**Open items this profile adds to the SRS list:**

| ID | Question |
|---|---|
| **OQ-16** | `TL 15A-GW` vs `TL 15AGW` (§4.1): one product or two? If two, what distinct BC SKUs? |
| **OQ-17** | S1 current (358 rows) vs backup (373 rows, newer mtime): which is authoritative, and should the 15 missing rows exist? |
| **OQ-18** | The 34 price-book-only codes in S1 Hoja1 (the S8 "Add to Store" expansion set): in scope for the first v2 Lindström build, or a follow-on run? |

*(On OQ-1 — the 292 vs 346 live-count question — this folder's evidence:
322 canonical SKUs, of which S8's Review sheet shows **312 live BC listings
with product ids**. Neither prior figure matches; the authoritative count
should be taken from the store at migration time, per the architecture's M6
plan.)*

---

## Appendix — reproduction

Profile generated by direct reads of every sheet (openpyxl `data_only=True`,
values-as-text), `scraper_output.json` (322 records), and
`scraper_output.csv`. Counts in this document are from those reads on
2026-08-19; source mtimes as listed in §1. Re-running the same sweep after any
file change is the manual precursor of the pipeline's own FR-11 source-hash
manifest.
