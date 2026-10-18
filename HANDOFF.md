# PIM Pipeline III — Session Handoff

| | |
|---|---|
| **Prepared** | 2026-08-19 |
| **For** | Any Cowork session, login, or engineer picking this up cold |
| **State** | Requirements and design complete and baselined. **No code written yet.** |
| **Read first** | This file, then `docs/requirements/PIM-BASELINE-REQUIREMENTS.md` |

This file is self-contained on purpose. Everything needed to continue is in this
repository — no chat history, no session memory, no prior context required.

---

## 1. What is being built, in one paragraph

Castletronics distributes multiple vendor brands. Each brand's product
information arrives spread across many spreadsheets that accumulated over
time — a vendor PIM export, a price book, a category assignment sheet, a site
scrape, an image audit, operator adjudications. **The system assembles that
scattered information into one complete record per product code, holds it as a
database, and publishes it to sales channels** (BigCommerce first) with full
backup, verification and rollback. Adding a brand means writing declarations
that describe its data — never touching engine code.

The operator's own statement of purpose (2026-08-19, quoted at the top of the
requirements spec):

> *"The entire point is to assemble brand information that aligns to a key,
> like product code, and build up information from a number of files. This
> will be a database of complete information that can then be processed to
> export data, load to a site, etc."*

Two subsystems, one contract between them:

- **PIM core** — ingest → normalize (per-brand) → merge on the key → apply
  overrides → derive → **product database** (the system of record)
- **Distribution chain** — change set → snapshot + gates → staged publish →
  verify → report, through swappable channel adapters

`docs/architecture/PIM-WORKFLOW.html` draws this; open it in a browser.

---

## 2. Document map — read in this order

| # | Document | What it is | Status |
|---|---|---|---|
| 1 | `docs/requirements/PIM-BASELINE-REQUIREMENTS.md` | **`CT-PIM-SRS-001` v1.0 — THE BINDING SPEC.** 139 FRs, 15 NFRs, 21 invariants (real production failures), 32 acceptance criteria, 7 operator decisions, open questions. §12 logs how the two source specs were reconciled; §13 traces every source requirement. | **Baselined — binding** |
| 2 | `docs/architecture/PIM-ARCHITECTURE-DESIGN.md` | `CT-PIM-ARCH-001` v1.0 — the implementing design. 7 ADRs, codebase layout, SQLite schema, brand-pack shapes, BigCommerce adapter, verification framework, CLI, testing strategy, M0–M6 roadmap. | For review |
| 3 | `docs/architecture/PIM-WORKFLOW.html` | The workflow diagram — data flow plus the four operator control points. | Current |
| 4 | `docs/data/LINDSTROM-DATA-PROFILE.md` | `CT-PIM-DATA-001` — measured profile of the real Lindström files: lineage, key spaces, column inventory, format hazards, defects found. | Measured 2026-08-19 |
| 5 | `docs/data/V1-ASSEMBLY-REFERENCE.md` | `CT-PIM-V1-ASM-001` — how the existing loader actually assembles the dataset, read from its source. **This is what the Lindström brand pack gets authored from.** | Measured 2026-08-19 |
| 6 | `docs/architecture/V1-LOADER-ASSESSMENT.md` | `CT-PIM-V1-ASSESS-001` — why the existing loader cannot extend to other brands (file:line evidence), and what to harvest from it. | Complete |
| — | `docs/requirements/MULTI-BRAND-LOADER-REQUIREMENTS.md`<br>`docs/requirements/LOADER-NG-REQUIREMENTS.md` | The two 2026-08-17 source specs. **Superseded by #1** — retained for provenance only. Never cite as binding. | Superseded |

---

## 3. Binding operator decisions (D-1 … D-7)

All ruled by Tony on 2026-08-19. These are recorded in SRS §0.1 and are not
open for re-litigation without him.

| ID | Decision | Why it matters |
|---|---|---|
| **D-1** | The two source specs are **merged into one baseline**; neither is independently binding. | They overlapped and disagreed; §12 of the SRS logs every resolution. |
| **D-2** | Built data is **SQLite (authoritative) + a deterministic canonical text export**. Diffs, determinism and version control operate on the export. | Real queries plus a diffable artifact; the export is a projection, regenerable at any time. |
| **D-3** | On post-write verification failure: **halt and wait for the operator**. Never auto-rollback. | The operator stays the authority over live state. |
| **D-4** | Stack chosen in the design doc: **Python 3.12+, single CLI** (ADR-1, with justification). | Continuity with v1, workstation-friendly, best spreadsheet tooling. |
| **D-5** | Two subsystems: **PIM core** (system of record) + **Distribution chain** (channels), joined by the built-data contract. | Stages 1–4 never see an endpoint; stage 5 never sees a vendor file. |
| **D-6** | **Code must not drive the supported brands.** The engine defines *operations*; the brand pack defines *everything about the data* — fields, types, formats, amounts, relationships. No field name, brand, count or format in code. The canonical field set is **open**. | The core directive. Enforced by AC-23: a second brand must load with zero engine diffs. |
| **D-7** | **Primary/alias conflicts HALT** naming SKU, field, both values, both columns; the operator rules via an override. Neither value ships un-ruled. | Resolves OQ-19. Supersedes both the source specs' "load neither" and v1's shipped "keep primary". |

### The three mandatory flexibility guarantees (operator, 2026-08-19)

1. **Nothing is unwritable** — create, update or delete anything (FR-48/50/51; AC-5).
   Code-level field exclusions are prohibited outright.
2. **Backup and rollback are mandatory** — automatic pre-write snapshot, per-row
   before-images, every run individually reversible (FR-88..99; AC-11..13).
   The system refuses to write if a snapshot can't be taken.
3. **Per-field change selection** — update one field across the catalogue without
   touching anything else (FR-53/74/76/77; AC-8).

Plus **CSV bulk edit** (FR-137..139): export the combined dataset, edit in Excel,
import back — imports land as *reversible overrides*, are diffed before applying,
and are screened for spreadsheet damage (float-ified EANs, lost leading zeros).

---

## 4. Open questions — what still needs Tony

| ID | Question | Blocks |
|---|---|---|
| **OQ-1** | **True live product count.** The two source specs say 292 and 346; the Listing Updates workbook shows **312** BC listings with product ids; the canonical roster is **322** SKUs. Take the authoritative number from the store at migration time. | Migration (M6) |
| **OQ-2** | Confirm the new system **inherits** the `related_products = [-1]` fix directed 2026-08-17 (11 in-scope + 152 released) rather than re-deriving it. | Migration (M6) |
| **OQ-16** | *Mostly resolved.* `TL 15A-GW` and `TL 15AGW` are **two real products** (v1 code + 2026-08-17 rulings). The collision found in the data profile is **one bad cell** in the ESD workbook's `BC SKU` column (drops the hyphen). Residual: fix that cell, confirm the live store carries both SKUs. | Lindström pack |
| **OQ-17** | The merged workbook (358 rows) and its `.BACKUP-20260720` (373 rows, *newer* mtime) diverge. Which is authoritative? | Lindström pack |
| **OQ-18** | The 34 price-book-only codes in Hoja1 (the "Add to Store" expansion set): in scope for the first v2 build, or a follow-on run? | Scope |
| **OQ-3..15** | Thresholds, retention, second endpoint, sale-price policy, verification depth, etc. — full list in SRS §11.2. Defaults are proposed for each; none block starting. | — |

**OQ-19 is closed** by D-7.

---

## 5. Where things live on Tony's machine

| What | Path (device `dell-ct1`) |
|---|---|
| This repository | `C:\Users\apole\Castletronics-local\Dev\repos\PIM-Pipeline-III` |
| Lindström source data (14 files) | `C:\Users\apole\OneDrive - Castletronics\Castletronics Shared\Business Folders\Brand Distribution\Lindstrom\2026\Data to Merge` |
| Existing v1 loader + mapping workbook | `C:\Users\apole\Castletronics-local\Dev\repos\spreadsheet-dev\Lindstrom Data Load` |

A new session will need those folders connected (Add folder in the Cowork
desktop app) to read them. **The source data folder is read-only** — corrections
belong in overrides, never written back there (it is a copy taken from masters;
the next copy silently overwrites any edit).

### Artifacts to harvest from v1 into the Lindström brand pack

Do not rewrite these — import them:

- `pipeline/vocab.json` — the frozen facet vocabulary (11 keys)
- `pipeline/field_map.json` + `LINDSTROM-BC-FIELD-MAPPING.xlsx` — declarative
  field mapping, 72 BC fields over 275 registered source columns, with
  per-field CONFIRMED flags. Ancestor of `fields.yaml` / `managed.yaml`.
- `unit_overrides.json` — 11 logged, reversible corrections with derivations
- `exclusions.csv`, `spec_docs_map.json` — rulings, not data; never re-derive
- The ledger and remote ids (FR-108) so BigCommerce identities are preserved

---

## 6. What the existing loader teaches (and why it is not the base)

The v1 loader successfully loaded the Lindström catalogue and **stays in
service until v2 proves equivalent** (FR-107/109). It is not the foundation:
the brand is woven into the code (source paths, expected counts, chapter
names, SKU prefixes, facet rules in Python across 8 of 9 modules), prices and
products are written by two different tools, `bc_loader.py:525-531` pops
`price` / `retail_price` / `custom_fields` on update (making MSRP permanently
unreachable — SRS §9.3), and there is no snapshot, before-image or rollback
anywhere in the pipeline.

Its *semantics*, however, are hard-won and are already encoded as requirements:
never auto-create categories, reconcile custom fields by name, HEAD-check image
URLs, write explicit `[]` rather than leaving BigCommerce's `[-1]` sentinel,
halt rather than truncate, and every check must be able to fail.
`docs/data/V1-ASSEMBLY-REFERENCE.md` records the full assembly — join rules,
precedence chains, derivation rules, packing — as the authoring source for the
Lindström pack.

---

## 7. Next steps, in order

1. **Get OQ-1 and OQ-2 answered** (blocks migration only — not the build).
2. **M0 — Skeleton**: repo layout per architecture §3, brand-pack schema models
   with every-error-at-once validation, CLI shell, CI with the import-linter
   contract and the falsifiability harness scaffold.
   *Exit: the pack-validation gate demonstrated red and green; AC-27.*
3. **M1 — Core build**: ingest, normalize, merge, aliases, units, encoding,
   overrides; SQLite store + canonical export + build diff; CSV round trip.
   *Exit: byte-identical rebuild (AC-3), alias-conflict halt fixture, provenance
   report, AC-29..32.*
4. **M2 — Derivation**: rule vocabulary, facets, completeness, packing, families.
   *Exit: all derivation gates red/green; Lindström pack builds and matches the
   shipped facet and spec key sets.*
5. **M3–M5** — change management, publish + safety loop, BigCommerce adapter.
6. **M6 — Lindström migration**: pack reproduces live with zero unintended
   diffs; MSRP change-and-rollback demonstrated; v1 retired.

Full phase table with exit criteria: architecture doc §12.

---

## 8. Working agreements to preserve

- **Truth**: never publish a claim the vendor did not make. Where the vendor is
  silent, omit. `esd=no` means "not stated", never "not ESD safe". Authority
  over what is true rests with the operator (FR-131..134).
- **Every catastrophic defect in this program's history was silent.** A check
  that can only report success is not a check. Every gate must be demonstrated
  failing on a corrupted fixture before its passing result is trusted (FR-87,
  FR-125, AC-17).
- **Safety comes from visibility and reversibility, never prohibition.** A field
  the operator cannot change is a defect, not a safeguard (SRS §0.2).
- **Report measured numbers, not verdicts.** "0 defects" from a query that
  returned 0 rows proves nothing — always before-and-after counts (FR-101/126).
- Tony's style: direct and technically precise; expects verified information
  over confident assertion, and pushback when reasoning doesn't hold.

---

## 9. Provenance of this state

Produced in a Cowork session on 2026-08-19 with Tony. The work: merged and
baselined the two source specs (resolving each conflict, logged in SRS §12);
wrote the architecture and design; profiled all 14 Lindström source files
column-by-column programmatically; read the v1 loader source in full and
documented both its assembly logic and its structural limits; and captured
seven operator decisions plus the three flexibility guarantees as binding
requirements. All findings in these documents are measured from the actual
files and code, not quoted from prior documents — where a prior document
disagreed with what was measured, the discrepancy is recorded rather than
silently resolved (see OQ-1, OQ-17, and SRS FR-20).
