# M0 — skeleton (2026-10-18)

Implements CT-PIM-ARCH-001 §12 M0 and the SKU grammar of CT-PIM-SRS-001-A1 (D-8).

## Install (Windows, once) — run as one block

```powershell
cd "C:\Users\apole\Castletronics-local\Dev\repos\PIM-Pipeline-III"
python -m pip install -e ".[dev]"
```

## Use

```powershell
cd "C:\Users\apole\Castletronics-local\Dev\repos\PIM-Pipeline-III"
python -m pytest                              # 32 tests: pack validation, SKU grammar, falsifiability, import contract
python -m pim.cli.main validate-pack lindstrom
python -m pim.cli.main sku parse 59.RX8130 2.53131A-U.1 59-8130
python -m pim.cli.main sku build 59 RX8130 --pack 10
python -m pim.cli.main checks                 # every registered check and whether it has a corruptor
python -m pim.cli.main schemas                # regenerate docs/schemas/*.schema.json
```

## What is here

| Path | Purpose | Requirement |
|---|---|---|
| `store/store.yaml` | store-wide data: SKU grammar (D-8), brand ids | D-6, A1 FR-150 |
| `pim/util/sku.py` | the ONE SKU parser/builder; grammar read from store.yaml | A1 FR-150a |
| `pim/config/models.py` | pydantic models for every brand-pack file, unknown keys rejected | ADR-4, FR-1..5 |
| `pim/config/loader.py` | validate a pack, every error at once, cross-file checks (ownerless field = error) | FR-4, FR-55 |
| `pim/config/schema_gen.py` → `docs/schemas/` | JSON schemas for IDE validation of packs | ADR-4 |
| `pim/verify/check.py`, `gates.py` | Check framework: measurement + registry; G-PACK, G-SKU-GRAMMAR | ADR-7, FR-101 |
| `tests/corruptors/` + `test_falsifiability.py` | every check proven RED on corrupted input | FR-87, AC-17, INV-1 |
| `tests/test_import_contract.py` | ADR-3 dependency rule enforced by AST scan | NFR-9 |
| `tests/fixtures/brands/fixture-brand/` | minimal complete valid pack | AC-27 |
| `brands/lindstrom/` | stub pack (brand, 7 sources, joins, 6 fields); full map in M1 | FR-107 |

## Exit criteria (ARCH §12 M0)
- G-PACK demonstrated red and green — `tests/test_falsifiability.py` ✔
- AC-27 (typo'd key fails loud) — `test_unknown_key_is_rejected` ✔
- Bonus: AC-6 (ownerless managed field fails the build naming the field) — `test_ownerless_managed_field_fails` ✔

## Next: M1 — core build
ingest readers (text-first, temp-copy, no write lock) → merge on key → aliases + provenance → units/encoding → overrides →
SQLite store + canonical JSONL export + CSV round trip. First target: the Lindström sources rebuild byte-identically.
