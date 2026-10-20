# M1 — core build (2026-10-19)

Implements CT-PIM-ARCH-001 §12 M1: ingest → merge → aliases + provenance → units/encoding → overrides
→ SQLite store → canonical export → build diff → CSV bulk-edit round trip. **No network, no derivation yet.**

## Run (Windows) — each block is self-contained

```powershell
cd "C:\Users\apole\Castletronics-local\Dev\repos\PIM-Pipeline-III"
python -m pytest                              # 68 tests, incl. 8 gates proven red on corrupted fixtures
python -m pim.cli.main build lindstrom        # reads the 8 files in Data to Merge; writes var\lindstrom\
python -m pim.cli.main builds lindstrom
python -m pim.cli.main export-csv lindstrom --fields name,book_list_price,book_net_price,esd_safe
python -m pim.cli.main import-csv lindstrom var\lindstrom\edits\lindstrom-<build>.csv          # diff only
python -m pim.cli.main import-csv lindstrom var\lindstrom\edits\lindstrom-<build>.csv --apply  # lands overrides\
python -m pim.cli.main diff lindstrom <build_a> <build_b>
```

## Measured on the real Lindström files (2026-10-19)

- 322 rows from 8 sources (S1 two-block Hoja1, S2 roster, S3 scrape json, S4 tech matrix, S5 image audit,
  S6 ESD ruling, S7 price book, S8 Listing Updates). Every value carries its source cell.
- Rebuild is byte-identical (AC-3): same build id, same `rows_sha256`.
- Price book joins: 114 declared associations generated from the Review sheet (`tl`/`hs`), e.g. `15AGWM → TL 15A-GW`.
- Alias chains supplied 1,595 values (length 164→302 of 322; tweezer tip widths 239).
- Encoding gate found 8 cells of `º`-for-degree the August profile said were absent; fixed by a declared
  `text_fixes` in brand.yaml, each application noted.
- Reported, not guessed: 8 prose capacities (`Max 0.5 mm`), 108 inch-only tip widths (now `tip_width_in`),
  1 unit-less length pair (331A).

## What is where

| Path | Purpose | Requirement |
|---|---|---|
| `pim/ingest/readers.py` | xlsx/csv/json readers, text-first, temp-copy, hashed; blocks, blank-header keys, json flatten, multi-row | FR-6..13, FR-111 |
| `pim/normalize/core.py` | key function, association table, alias chains + provenance, unit parse, encoding sweep, D-7 conflict halt | FR-14..24, D-7 |
| `pim/normalize/overrides.py` | pre-value-matched, reversible overrides | FR-25/26 |
| `pim/build.py` | the stage runner, assertions with measured numbers, manifest | FR-40, FR-101 |
| `pim/store/db.py` · `export.py` · `csv_io.py` | SQLite store · canonical JSONL + diff · CSV round trip with damage detection | ADR-2, FR-39..42, FR-137..139 |
| `pim/verify/gates.py` | G-ROSTER, G-REQUIRED, G-ENCODING, G-ALIAS-CONFLICT, G-OVERRIDE-STALE, G-KEY-UNIQUE (+M0's two) | FR-87 |
| `brands/lindstrom/` | sources (8), joins (114 associations), fields (58), expectations, managed, endpoints, pricing | FR-107 prep |

## Exit criteria (ARCH §12 M1)
- byte-identical rebuild — `test_rebuild_is_byte_identical` + measured on Lindström ✔
- FR-20/D-7 fixture — `test_d7_alias_conflict_halts` + G-ALIAS-CONFLICT corruptor ✔
- provenance report — every field value carries `p:` in `rows.jsonl`; alias notes in the build output ✔
- AC-29..32 — `tests/test_csv_roundtrip.py` ✔

## Next: M2 — derivation + Stage 2b (A1)
Rule vocabulary (copy/map/slug/band/precedence/sku-pattern/compose/pack/family), facets with frozen vocabulary,
`filter_metadata` + `spec_display` packing with the 250-char halt, families, SEO strings, HTML cleaning — on
CATALOG rows (carry state, derivatives, SKU rule, pricing rules, fulfillment). First target: reproduce the
shipped Lindström facet and spec keys from `pipeline/vocab.json`.
