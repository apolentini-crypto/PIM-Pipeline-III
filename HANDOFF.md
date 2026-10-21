# HANDOFF — PIM-Pipeline-III (read this first in a new session)

Last updated 2026-10-20 evening (America/Denver). Owner: TP (Tony), Castletronics.
Repo on TP's PC: `C:\Users\apole\Castletronics-local\Dev\repos\PIM-Pipeline-III` (git, branch `main`).

## What this is, in one paragraph

A pipeline that adds a vendor brand's products to castletronics.com (BigCommerce). It reads
whatever the brand gives us (xlsx / csv / json scrapes), lines everything up by vendor part
number (MPN), stores a numbered build, lets TP decide what to carry and at what price
(including packs and kits we invent, e.g. a 5-pack of spatulas), assigns Castletronics SKUs,
and — later — pushes to the store through the API with a diff and rollback. Designed from the
store format backwards. Specs first, code second; every gate measures a number, never a verdict.

Four generations exist. Only this one matters now:
`PIM-Pipeline` (May) → `PIM2` (Jun–Jul, Flask, never loaded live) → `Lindstrom Data Load`
(loaded 346 products live Jul–Aug, hardcoded) → **`PIM-Pipeline-III`** (specs + this code).

## Where things are

| thing | where |
|---|---|
| Baseline spec (139 FRs, D-1..D-7) | `docs/requirements/` — CT-PIM-SRS-001, CT-PIM-ARCH-001 |
| Amendment A1 — Decide stage (FR-140..173c) | `docs/requirements/PIM-SRS-A1-CATALOG-DECISIONS.md` v0.3 |
| Milestone notes | `README-M0.md`, `README-M1.md`, `README-UI.md`, `README-M2a.md` (walk snags at the end) |
| Code | `pim/` — `config/` (pydantic models + pack validation), `ingest/`, `normalize/`, `decide/`, `store/` (SQLite + JSONL export + CSV round trip), `verify/` (gates), `cli/main.py`, `ui/` (local window) |
| Store-wide config | `store/store.yaml` — SKU grammar (D-8) and the brand → BC brand-id table |
| Brand packs (data, not code) | `brands/<slug>/` — brand.yaml, sources.yaml, joins.yaml, fields.yaml, expectations.yaml, managed.yaml, endpoints.yaml, pricing.yaml, derivatives.csv, decisions/decisions.csv, overrides/ |
| Lindström pack (the worked example, 322 products) | `brands/lindstrom/` |
| Lindström source files (READ-ONLY, never written) | `C:/Users/apole/OneDrive - Castletronics/Castletronics Shared/Business Folders/Brand Distribution/Lindstrom/2026/Data to Merge` (path is in sources.yaml `source_root`) |
| Builds, exports, edit sheets | `var/<slug>/` — `pim.db`, `exports/<build_id>/{rows,catalog}.jsonl + manifest.json`, `edits/*.csv` |
| Tests (91, all pass on TP's PC and in the sandbox) | `tests/` — fixture brand in `tests/fixtures/brands/fixture-brand` |
| Launcher | `PIM.bat` — double-click; opens the window at http://127.0.0.1:8766 |

## How TP runs it

- **Window:** double-click `PIM.bat`. Stages down the left: Brand & files → What changed → Build →
  Decide → (Derive & review, Publish: planned). A stale window hands over to a new one on its own.
- **Command line** (always give TP complete commands, with the `cd`):
  ```
  cd "C:\Users\apole\Castletronics-local\Dev\repos\PIM-Pipeline-III"
  python -m pim.cli.main validate-pack lindstrom
  python -m pim.cli.main build lindstrom --dry-run
  python -m pim.cli.main build lindstrom
  python -m pim.cli.main export-decisions lindstrom
  python -m pim.cli.main import-decisions lindstrom var\lindstrom\edits\lindstrom-decisions.csv --apply --who Tony --why "range review"
  python -m pim.cli.main diff lindstrom <build_a> <build_b>
  python -m pytest -q
  ```
  TP's Python is 3.14. `pip install -e .[dev]` was done.

## The architecture in one picture

```
 brand files ──► Phase 1 BUILD (M0/M1) ──► rows.jsonl   one row per vendor MPN, all values text + provenance
 (read-only)        pack = data, gates      │
                                            ▼
                 Phase 2 DECIDE (M2a) ──► catalog.jsonl  one row per CT SKU (59.MSF, 59.MSF.P5, 59.MS-KIT5)
                    decisions.csv, derivatives.csv, pricing.yaml
                                            │
                 Phase 3 DERIVE + PUBLISH (M2b, M3–M5: not built) ──► BigCommerce via API, diff first, rollback
```

## Rulings that must not be re-litigated (all TP's, verbatim where quoted)

- **D-8 SKU grammar:** `<brand number>.<mpn>` base; optional ending `.M` (master), `.N` (serialized
  unit), `.P<qty>` (pack); condition with a dash on the part number before any dot ending
  (`2.53131A-U.1`). "All dots between the parts, never a dash after the brand number." An MPN
  containing `.` gets it substituted (Lindström: `.` → `-`). Code: `pim/util/sku.py`, `store/store.yaml`.
- **Purchase unit (2026-10-20):** vendor PACKAGE QTY is what the *factory* buys inbound — "All items
  are purchased by distributors as each." Never divide pack figures. A pack of N costs N × each.
  Dimensions are never computed for derivatives (FR-147).
- **Carry states:** undecided · carry · skip · derivatives-only · carry+derivatives. "dont forget just
  carrying each item as is or not selecting items."
- **Spatula example:** castletronics.com/tools/spatulas — sell singles and a 5-pack / a set.
  Lindström pack: MSF P5; kit MS-KIT5 = MSEF:1;MSF:2;MSM:1;MSL:1.
- **Sheet shape (2026-10-20):** one row per CT SKU, packs under their parent, kits at the end;
  derivatives get their own hold/price/qty; import validates every cell (A1 FR-171a/b/c, FR-173a).
- **Edit surface:** CSV round trip first, browser forms later.
- **Terminus (OQ-21):** whether loads go through the CT Hub import door or straight to BigCommerce is
  for TP's hub design session. Hub ruled 2026-08-03 that loads terminate at the Hub; hub SKU grammar
  is `{brand}.{mpn}[.seq]`, `.M`, `-U/-OB/-R` — matches D-8.
- **Lindström live SKUs are `59-<mpn>`** (non-conforming, OQ-20b) — rename is a later, separate job.
- **Brand #2 = Pace Worldwide** (files not yet received; brand id not yet in store.yaml).
- Live store is never written without TP's explicit go. `Data to Merge` is read-only.

## State of work

Done: M0 (pack validation, SKU grammar), M1 (build: readers, merge, aliases, D-7 conflict halt,
units, overrides, SQLite + deterministic export, CSV round trip with damage detection, gates with
corruptors), the local window + launcher, M2a Decide (states, packs, kits, pricing rules, decision
sheet, catalog export, G-DECIDED/G-SKU-UNIQUE/G-PRICE/G-DERIV), an operator walk with 7 snags fixed
(see README-M2a.md). Lindström: 322 products build clean; decisions seeded 317 carry + 1 skip (CC230,
from the walk) + 4 carry+derivatives; RX-8130 hand-priced 99.00 (from the walk); 29 unpriced (no
list price in the vendor book); 10 held for dead vendor URLs.

**Done 2026-10-20 late:** FR-171a/b/c + FR-173a — decision sheet one row per CT SKU, derivative decisions
keyed `MSF.P5` / kit MPN in decisions.csv, every cell validated on import, `new_pack_qty` column. Shared
implementation in `pim/build.py` (`export_decision_sheet`, `import_decision_sheet`) used by window and CLI.
Verified on the real Lindström data by reading the written file back (324 rows) and a simulated Excel round trip.

**Next (TP asked for it 2026-10-20):** a **field review** in the Derive & review stage — one row per FIELD:
from (source column + fallback), coverage (n/322, n from fallback), changed since previous build, odd values
flagged, unit, publish flag, one-line verdict (ok / missing N / sparse / EMPTY — stale column? / review N);
click-through to just the products behind a number. Purpose: see stale or wrong columns without reading 322 rows.

Next after that: M2b Derive (facets, filter_metadata/spec_display packing with the 250-char halt,
families, SEO, HTML cleaning — reproduce the Lindström vocab.json keys), customs columns on the
sheet, window forms for derivatives and pricing rules, then M3–M5 Publish once OQ-21 is settled.

## Git / GitHub

Commits are made on TP's PC. Last: `78a582b` "M2a walk: …". **Push is blocked** until TP puts a new
GitHub token (Contents read/write on PIM-Pipeline-III) in
`C:\Users\apole\Castletronics-local\Dev\repos\castletronics_hub\.ct-gh-token` (the current one is
scoped to the hub repo → 403). Never print a token. Push command for TP:
```
cd "C:\Users\apole\Castletronics-local\Dev\repos\PIM-Pipeline-III"
git push origin main
```

## Working-with-the-machine notes (for Claude)

- The sandbox shell on TP's PC is Linux (Python 3.10) with the repo mounted at
  `$HOME/mnt/PIM-Pipeline-III`. SQLite cannot write on that mount — run builds there with
  `PIM_VAR_DIR=$HOME/pimvar3`. His real Windows Python (3.14) runs the window and tests fine.
- Deliver files with `device_commit_files` from `/mnt/user-data/outputs/...`, then verify by md5 on
  his side. Single-file commits have silently not landed before — always check the hash.
- `git commit` there needs delete permission (index.lock) — request it once per session.
- The built-in browser pane can reach http://127.0.0.1:8766 on his PC for walking the window.
- After changing server/page code the running window must be restarted (double-click PIM.bat).
- TP: plain English; he's visual — diagrams help; commands complete with `cd`; look at the actual
  output files, not just the code ("you should look at the file outputs to be sure they are as you
  expect").
