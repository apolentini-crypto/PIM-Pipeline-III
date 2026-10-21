# M2a — Decide (2026-10-20)

Implements CT-PIM-SRS-001-A1 §3.1–3.5, 3.8, 3.9 (Stage 2b): canonical rows (one per vendor MPN)
→ **catalog rows (one per CT SKU)**.

## Run (Windows)

```powershell
cd "C:\Users\apole\Castletronics-local\Dev\repos\PIM-Pipeline-III"
python -m pim.cli.main export-decisions lindstrom
python -m pim.cli.main import-decisions lindstrom var\lindstrom\edits\lindstrom-decisions.csv
python -m pim.cli.main import-decisions lindstrom var\lindstrom\edits\lindstrom-decisions.csv --apply --who Tony --why "range review"
python -m pim.cli.main build lindstrom
```
Or in the window: **4 Decide → Export decision sheet → edit in Excel → Preview → Apply → 3 Build**.

## The decision sheet — one row per CT SKU (A1 FR-171a/b/c, 2026-10-20)

Rows: every vendor part number (even `undecided`/`skip`, so it can be decided), each pack directly under its
parent (key `MSF.P5`), kits at the end. Edit the columns **without** a "—" prefix; "—" columns are context and
are ignored on import. `mpn` is the key — never change it.

| column | values | effect |
|---|---|---|
| `carry_state` | `undecided` · `carry` · `skip` · `derivatives-only` · `carry+derivatives` (a pack/kit row: `carry` or `skip` only) | which catalog rows exist |
| `hold_reason` | free text | carried but withheld from publishing; a pack/kit's own hold beats the parent's |
| `fulfillment` | from `pricing.yaml → fulfillment_vocabulary` | checked on import |
| `initial_qty` | whole number ≥ 0 | starting stock, written on create only |
| `price` | money (`99`, `99.95`, `$1,234.5` all accepted → stored `1234.50`) | hand-set price; beats every rule, on packs and kits too |
| `new_pack_qty` | `5` or `5;10` on a **parent** row | adds packs to `derivatives.csv` on apply (parent must allow derivatives) |
| `who` `when` `why` | basis; `when` is `yyyy-mm-dd` (Excel's `m/d/yyyy` is accepted and normalised) | filled in on Apply if blank |
| `— sku` `— kind` `— parent` `— components` | context | what the store will get |
| `— unpriced` `— price now` `— basis` | context | what the last build resolved (`not built` if the row is not carried) |
| `— cost` `— list` `— margin% at list` `— category` `— name` | context | vendor figures (pack = N × each, kit = sums) |

Import validates every cell (scientific notation, non-numbers, bad dates, unknown fulfillment, part numbers
Excel turned into dates, stripped leading zeros) and refuses the whole sheet while any error stands, naming
sheet row and column. Derivative decisions live in the same `decisions/decisions.csv`, keyed `MSF.P5` / the kit
MPN; a derivative with no row is `carry` (FR-173a).

## Derivatives — `brands/<brand>/derivatives.csv`

```
kind,parent_mpn,pack_qty,mpn,components,name,who,when,why
pack,MSF,5,,,,Tony,2026-10-20,spatulas sell better as a 5-pack        → 59.MSF.P5
kit,,,MS-KIT5,MSEF:1;MSF:2;MSM:1;MSL:1,"Spatula Set, 5 pc",Tony,…      → 59.MS-KIT5
```
Pack: cost, list and weight = N × each; name = parent name + " — N-pack"; dimensions never computed (FR-147).
Kit: cost, list and weight = sums of the components; name yours; the rest inherited from the first component.
The parent's (or every component's) `carry_state` must be `derivatives-only` or `carry+derivatives` (G-DERIV).

## Pricing — `pricing.yaml`
`purchase_unit: each` (ruling 2026-10-20: the vendor's PACKAGE QTY is never used). `fields:` binds cost / list /
weight / category / group. Rules resolve most-specific first: `row` → `derivative` → `category` → `brand` →
`default`; basis `markup-on-cost` | `discount-off-msrp` | `fixed` | `msrp-passthrough`; rounding `nearest-cent` |
`.95` | `.99` | `whole-dollar` | `none`. A hand-set price on the sheet beats every rule. `margin_floor_pct` flags,
never refuses. `unpriced_means: hold | price-hidden` is the explicit meaning of "no price" (FR-156).

## Gates added
G-DECIDED (undecided count; must be 0 before publish) · G-SKU-UNIQUE · G-PRICE (unpriced count) · G-DERIV (parent
state, components exist) · MARGIN-FLOOR (report) · PLAUSIBILITY notes (INV-14: a per-each weight ≥ 20× or ≤ 1/20 of
its section's median). G-DERIV and G-SKU-UNIQUE have corruptors.

## Lindström state
`decisions/decisions.csv` seeded: 312 carry (live in the store today), 10 carry + held (dead vendor URL),
0 undecided. Spatulas MSF/MSEF/MSM/MSL = `carry+derivatives` with the example pack and kit above.
Build: 324 catalog rows = 322 singles + 1 pack + 1 kit; 29 unpriced (price-hidden); plausibility flagged
MSL (160 g vs 1.3 g median) and 3 others.

## Not yet
A form for derivatives and pricing rules in the window (CSV/YAML today) · customs columns on the sheet (A1 §3.6,
M2b) · field overrides on derived rows (overrides apply to canonical rows; pack/kit names and prices come from
derivatives.csv and the sheet).

## Operator walk, 2026-10-20 — snags found and fixed
1. Readiness checklist (and the Save/Build buttons) were stale after **Open** — now refreshed on open.
2. `G-PRICE`, `G-DECIDED`, `MARGIN-FLOOR` showed as **PASS … expected 0** while measuring 29 — they are
   counts the build reports and Publish enforces; shown as **INFO** now (window and CLI).
3. Preview/Apply in *What changed* with a blank path returned a raw `ValueError: WindowsPath('.')` —
   blank, missing, folder and non-CSV paths now get a plain-English refusal (both sheet importers).
4. Prices showed `99` for a hand-set 99 and `99.00` from rules — prices now always carry two decimals.
5. **Compare** only diffed the canonical rows, so skipping CC230 and repricing RX-8130 reported *0 changed*.
   Compare (and `pim diff`) now show two diffs: **Products** (one per vendor MPN) and **Catalog** (one per
   CT SKU — decisions, packs, kits, prices, held). Versions table shows catalog row counts.
6. Build ids differed between machines for the same pack (CRLF) — pack hash is now line-ending-insensitive.
7. The two Preview/Apply pairs (field sheet vs decision sheet) looked alike — relabelled *Preview decisions / Apply decisions* and *Preview field edits / Apply as overrides*.
