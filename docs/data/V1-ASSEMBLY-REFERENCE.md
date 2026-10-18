# V1 Loader Assembly Reference — How the Lindström Dataset Is Actually Put Together

| | |
|---|---|
| **Document ID** | `CT-PIM-V1-ASM-001` |
| **Date** | 2026-08-19 |
| **Read from** | The v1 pipeline source in full: `build_library.py` (1,008 lines), `normalize.py`, `config.py`, `pricebook_source.py`, `adds_ingest.py`, `build_products.py`, `bc_loader.py` (assembly-relevant sections), `read_mapping.py`, `field_map.json`, `vocab.json` |
| **Purpose** | The measured record of how v1 merges the `Data to Merge` files into one row per SKU — every join, precedence chain, derivation and packing rule — so the v2 Lindström brand pack encodes what actually ships, not what any document says ships |
| **Companions** | `LINDSTROM-DATA-PROFILE.md` (what the files contain) · `V1-LOADER-ASSESSMENT.md` (why the code doesn't generalize) |

The v1 pipeline runs in four phases: **build_library** (merge + derive →
`build/library.csv`, ~80 columns), **build_products** (library + mapping
workbook → BC payload JSON), **bc_loader** (gates → upsert → sub-resources →
relations pass 2 → verify), with **price_refresh** as a separate price tool.
This document records phases 1–3, where the dataset is assembled.

---

## 1. The merge spine and join rules

**S2 `Category Assignments :: Product Categories` is the spine.** The build
iterates its 322 rows; a roster MPN missing from S1 is a halt, not a skip.
Everything else joins onto the roster MPN.

**Join keys are trimmed and NEVER normalized inside** (`normalize.key`):
hyphens, spaces, underscores and dots are significant — `TL 15A-GW` ≠
`TL 15AGW` (two real products), `8167L_` is a genuine part number. Slugging
happens only for facet values and family grouping, never for identity.

**S1 `Hoja1` is joined as a two-block sheet.** The build keys on `PRODUCT`
(unique, covers 322/322) and takes the price-block cells from the *same row*.
It proves in-run that `Product Code` is the wrong key: it covers fewer roster
rows and carries colliding values (`15AGW` collides exactly the two tweezers
above). Per-row merge sources:

| Library field | Source and precedence |
|---|---|
| title (`name`) | S1 `en_US#SHORT DESCRIPTION P` **else** S3 `product_name` |
| `description_html` | S3 `description_html` **else** S1 `en_US#PRODUCT DETAILS` (pipe-split → `<ul>`) — the fallback exists for the 10 scrape-404 SKUs |
| `meta_description` | S3 |
| identity extras | `EAN CODE` via float→int repair (`7314150103003.0` → integer string); `vendor_sku` from S3 kept only to *cross-check* MPN — a mismatch is human review, never auto-adopted (caught `HS6001_`) |
| classification | chapter/section from S2; `en_US#GROUP` + `PRODUCT BLOCK` from S1 |
| capacity | S3 `specs["Cutting Capacity (mm)"]` **else** S4 same column **else** S4 `Cutting Capacity Soft Wire (mm)` (closes TRX-8180A, P6160 → cutters 96/96) |
| ESD | **entirely S6** — `ESD Safe`, `ESD Source`, `Resistivity`; the build interprets nothing, it carries the adjudication |
| images | S5 long-format → main (`PRODUCT IMAGE NAME`) + gallery (`ADDITIONAL IMAGE NAME`, capped 12); http URLs only; APPLICATION/DRAWINGS/Certificates deliberately excluded |
| pliers `jaw_surface` | S4, **pliers only** — validated 22/26 rows are the live pliers; the other 2 (HS6000/6001) are inverted vs their own names |
| tweezer `tip_shape` | **parsed from S1 `PRODUCT DETAILS` prose** (`Tip description:` segment; shape words straight/curved/angled/bent; numeric degrees → angled; `flat` deliberately excluded; never falls back to `group`, which mis-files TL 51S-SA) |
| weights | THREE independents carried: price-block `Weight (LBS)` (the loaded one), PIM `UNITWEIGHT kg`, scrape weight (unit parsed from value) — cross-checked at 3× tolerance, never derived from one another, never divided by `PACKAGE QTY` (those columns were hand-modified to 1) |
| dimensions | `UNIT*` mm columns (single sellable item incl. retail pack), converted mm→in at payload time **+ 0.5 in packing adder**; `PACK*` is the master carton and is never used per-unit |

**Prices are then overwritten by `pricebook_source.py`** — the 8-1-26 book,
not the PIM (the PIM's `2026 List Price` is pre-increase; using it is the
288-product revert). Join: the price run's `bc_sku → book code` association
(Review sheet), operator overrides on top, then the Add-to-Store bridge for
`TL …` tweezers, then raw MPN. Operator rulings baked in (2026-08-17):
**list price IS the MSRP** (`price` and `retail_price` both take it); book
net → cost; **`sale_price` is never written** (23 live sales protected by
omission); `15AGWM` is the book code for `59-TL 15A-GW` (not `15AGW`); 3
unconfirmed HS joins held at live.

## 2. Spec display strings (the 16 `spec_*` fields)

Built as **finished display strings** from S4/S3 spec columns
(`config.SPEC_FIELDS`, in render order):

- **Dual-unit compose**: `(mm_col, in_col)` → `133.5 mm / 5.25 in`; decimal
  commas normalized *first* (`1,3` read as two numbers corrupts the pair);
  range separators rewritten to en-dash **only between digits**; an inch
  value that rounds to `0.00` is rebuilt from the mm side at 2→4 dp
  (`repair_inches` — `0.00 in` on a cutting tool reads as zero capacity);
  a genuine 0 stays `0`.
- **Alias chains** (`SPEC_ALIASES`): `spec_length`: `Length (mm)` →
  `Length` → `Total length`; `spec_tip_width`: `Tip Width (mm)` →
  `Tip Width, mm` → `Tip Width`. Unit parsed from **inside** the value
  (`Length` carries `130 mm` on one row, `4,72 in` on 115); never converted
  to the missing unit (that would invent a measurement).
- **⚠ Primary-vs-alias disagreement — shipped behavior differs from every
  spec.** Both columns are always read (so the conflict branch is reachable);
  on disagreement beyond 2% the shipped code **keeps the PRIMARY and reports
  the conflict** (`alias_conflicts.json`) — a Design correction dated
  2026-07-22, reasoned "the primary is the designated source; an absent row
  reads as not-applicable, a different falsehood; what is banned is an
  *unrecorded* guess." The config comment and the run report still say "load
  NEITHER" — v1 is internally inconsistent about its own rule. **See §5,
  OQ-19: the baseline's FR-20 currently codifies load-neither and must be
  ruled on.**
- **Unit overrides, two tiers** (from `unit_overrides.json` /
  `tier_b_conflicts.json`): Tier A = arithmetically provable transpositions,
  applied **only while the recorded `before` still matches** (else HALT — the
  stale-override guard FR-25 inherits); Tier B = irreconcilable pairs,
  printed **mm-only, row kept**. Raw pre-correction values are stashed to
  `spec_raw.json` because deriving the override map from corrected output
  once silently emptied it (circularity).
- Per-SKU **alias provenance** (`alias_sources.csv`, which column supplied
  each value) — the FR-19/47 ancestor.
- Packing: 16 keys `cr cc tw ht hs rs hn ln hh hw hk wt co` + appended
  `tt bh bw`, joined `key=value;…`; empty keys omitted; `;`/`=` inside a
  value HALTS (never escaped); >250 chars HALTS with instructions to split
  by render order, never truncate. Measured max: 216 (`59-BAH8156`).

## 3. Facets, families, SEO, call-for-price

**Facets** (`facets_for`, 10 controlled keys + exempt `cap_disp`):

| Key | Rule as shipped |
|---|---|
| `type` | slug of L3 section |
| `cut` | S4 `Bevel / Cut Result` **else** trademark term in title (ultra-flush / micro-bevel / flush) |
| `head` | **per-chapter declared source** (`SHAPE_SOURCE`): Cutters→`head_type` · Tweezers→`tip_shape` · Pliers→`jaw_surface` (head_type IS the section there) · Screwdrivers→`group`; chapters with a declared source get **no fallback** (absence is real); rail-less chapters fall back `head_type` else `group` for card display |
| `size` | `Head Size` slug (XS/S/M/L) |
| `cap` | upper bound of capacity → 5 bands at 0.8 / 1.0 / 1.25 / 1.6 / ∞, **upper-inclusive** (52 of 94 cutters sit exactly on a boundary), with an explicit NaN guard (NaN would otherwise silently land in the heaviest band) |
| `handle` | SKU prefix RX→ergo, HS→long (HS6000/6001 exempted — HS is the model there), else `\bERGO\b` in the **name only** (P6160; description text gave 68 false positives), else standard |
| `esd` | `yes`/`no` from S6 only — `no` means "not stated" |
| `block` | slug of `PRODUCT BLOCK` |
| `series` | cutters+pliers only: handle first (long→hs, ergo→rx), else first digit read **through** letter prefixes (7→sup, 8→s80), else omit; both scope halves asserted (over-application halts) |
| `tipw` | tweezers only: `Tip Width, mm` (decimal-comma) banded <0.20/<0.50/<1.00/≥1.00; key deliberately not `tw` (collides with spec_display's tip-width key) |

Vocabulary is frozen in `vocab.json` (G2): any packed value outside it halts
naming SKU/key/value; `cap_disp` alone is exempt (free vendor text).

**Families** (`derive_related`): union of (a) the **slugged** `PRODUCT BLOCK`
group — slugging is what reunites `RX 8133-RX 8165_` with `RX-8133-RX-8165_`,
which otherwise orphans RX8155 — and (b) **handle twins**: same base number
after stripping an RX/HS prefix (`8130`/`RX-8130`/`HS-8130`), HS6000/6001
exempt. Payload time prunes members to SKUs the build will actually create
(51 links to held SKUs at the time), and pass 2 filters again to ids present
in BC.

**Categories beyond the chapter** — two opposite operator rulings, declared
separately: **DUAL-LIST** spare parts (keep chapter + add `Parts and
Accessories`; both section spellings matched) vs **MOVE** tweezer sets
(replace with `Kits & Sets`; exact match only — a loose "set" match would
also catch Shear Cutter sets, unruled).

**SEO**: `Lindström {short} {mpn} | Castletronics` with a 7-entry curated
short-section table; 60 chars is a target — overflow measured and reported,
never truncated. Meta: `{Section} from Lindström. {Cut }{Head }— {mpn}.
Authorized Lindström Distributor. Ships in 24 hours.` + `ESD safe.` only
where true; segments with absent sources omitted entirely (no dangling
separators); ≤160 hard.

**Call-for-price** (20 SKUs): `price=0` + `is_price_hidden=true` +
label `Request a Quote` (the theme's existing string — a fourth phrasing was
rejected) + `availability=disabled` (un-orderable). `$0` without the flag is
a false price tag; the combination was verified against a live call-for-price
product plus two negative controls.

**Holds**: dead-vendor-URL (10) held pending vendor answer; unpriced released
2026-07-22 when the theme shipped Request-a-Quote; discontinued loaded, not
gated. The 2026-08 additions (`adds_ingest`) append as ordinary rows so every
gate runs on them; their MPNs come only from the operator's Add-to-Store
sheet (the scraped site `sku` is a page-level value that collapsed
RX8137MX/RX8138MX onto one code).

## 4. Payload formation (phase 3) and write-path facts

`build_products.py` is a **pure mapper**: every BC body field comes from
`field_map.json`, generated from the mapping workbook (`read_mapping.py`) —
`lib` column + transform (`int_str`, `round2`, `mm_to_in`+adder,
`bool_or_skip`…) + `load_on` + CONFIRMED. Nothing body-level is decided in
code; the four custom fields (`filter_metadata`, `esd_safe`,
`ct_page_type=tool`, `spec_display`) plus verbatim `spec_docs` are added
under runbook gates. Category names → ids at load (G5, never create); brand
resolved to id by exact string, never sent as name (spelling split risk).
On update the body pops price/retail_price/custom_fields (the FR-50 defect);
custom fields reconcile by name — **prune legacy names first**, PUT existing,
POST missing, delete duplicates; images carry a `src:` fingerprint.
Asserted limits: name/custom-field ≤250, url ≤255, ≤1000 images, required
create fields, zero-weight, malformed float GTINs, is_visible/inventory
leak = 0. Duplicate names allowed (BC relaxed; 23 exist; one-flag MPN-suffix
remedy kept OFF).

## 5. What this changes for v2 (decisions and corrections)

1. **OQ-16 is substantially answered by the code + operator record.**
   `TL 15A-GW` and `TL 15AGW` are **two real products** (normalize.py rule 1),
   and the 2026-08-17 rulings pin the book joins: `15AGWM` ↔ `59-TL 15A-GW`;
   `15AGWM` is NOT an add (creating it would duplicate a live product). The
   collision the data profile found is in the **ESD workbook's `BC SKU`
   column**, which drops the hyphen for one of them — a workbook cell to fix,
   not a product-identity question. Residual for Tony: confirm the live store
   carries two distinct SKUs (`59-TL 15A-GW`, `59-TL 15AGW`) and fix the S6
   cell.
2. **OQ-19 — RULED (operator, 2026-08-19; SRS D-7).** Baseline FR-20 said
   *load neither and report* (both source specs); the **shipped loader keeps
   the primary and reports** (deliberate Design correction, 2026-07-22), and
   v1's own comments/report text still describe the old rule. **Ruling: v2
   HALTS on the conflict — naming SKU, field, both values, both columns —
   and the operator rules via an override.** Neither value ships un-ruled.
   Migration fidelity is unaffected: 0 of 322 products trigger the branch,
   so shipped, baselined and ruled behaviors are byte-identical on current
   data (FR-107's zero-unintended-diff holds).
3. **Lindström pack price semantics settled**: price source = current price
   book (not PIM); `price` = `retail_price` = book list; `cost` = book net;
   `sale_price` unmanaged (protected by omission, drift-reported under
   FR-57); price associations = Review sheet + operator overrides + adds
   bridge, with held joins as holds.
4. **Rule-vocabulary additions for ADR-5** surfaced by real rules the closed
   set must express: prose-extract (regex segment + keyword list, for
   `tip_shape`), title-keyword precedence (`cut`), name-keyword tie-break
   with field scoping (`handle`/P6160), first-digit-through-prefix
   (`series`), unit-repair (inch-zero rebuild), n-way independent
   cross-check with tolerance (weights), SEO template compose with
   omit-empty-segments, category move/dual-list, per-chapter source
   selection with no-fallback semantics (`head`), and NaN/blank-safe banding.
5. **Migration fixtures to carry verbatim**: the boundary-value banding set
   (52/94 on a boundary), the `RX 8133`/`RX-8133` block-spelling reunite,
   P6160, HS6000/6001, the 10 dead-URL holds, the 23 duplicate names, the
   `spec_raw.json` circularity lesson (overrides derive from pre-correction
   values only), and the NaN-lands-in-heaviest-band guard.

---

*Provenance: all statements trace to the staged v1 source read 2026-08-19;
line-level citations available in `V1-LOADER-ASSESSMENT.md` for the
structural findings.*
