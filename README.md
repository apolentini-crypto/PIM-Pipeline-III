# PIM-Pipeline-III

Third-generation Castletronics product data pipeline: assemble any brand's
product information from an arbitrary set of vendor files, aligned to a product
code, into one complete record per SKU — then publish that database to sales
channels, validated, verified and reversible.

**Built:** M0 (pack validation, SKU grammar), M1 (build), the local window (`PIM.bat`),
M2a (Decide). **Not built yet:** Derive and Publish (M2b, M3–M5). Brand packs: Lindström,
Pace Worldwide.

## Documents

| Path | What it is |
|---|---|
| [docs/requirements/PIM-BASELINE-REQUIREMENTS.md](docs/requirements/PIM-BASELINE-REQUIREMENTS.md) | **`CT-PIM-SRS-001` v1.0 — BASELINED, BINDING.** The single requirements specification: merges and supersedes both source specs, with a conflict-resolution log (§12) and full traceability (§13). Where anything disagrees, this document wins. |
| [docs/requirements/PIM-SRS-A1-CATALOG-DECISIONS.md](docs/requirements/PIM-SRS-A1-CATALOG-DECISIONS.md) | `CT-PIM-SRS-001-A1` v0.3 — **approved** amendment adding Stage 2b Decide (carry states, packs and kits, SKU grammar D-8, pricing, decision sheet). FR-140..173a. |
| `README-M0.md` · `README-M1.md` · `README-UI.md` · `README-M2a.md` | Milestone notes: what each built, how it runs, snags found. |
| [docs/architecture/PIM-ARCHITECTURE-DESIGN.md](docs/architecture/PIM-ARCHITECTURE-DESIGN.md) | `CT-PIM-ARCH-001` v1.0 — top-down architecture and design: ADRs, codebase layout, SQLite schema, brand-pack design, BigCommerce adapter, verification framework, CLI, testing strategy, M0–M6 roadmap. |
| [docs/architecture/PIM-WORKFLOW.html](docs/architecture/PIM-WORKFLOW.html) | The system workflow diagram — data flow and the operator control points. Open in a browser. |
| [docs/data/LINDSTROM-DATA-PROFILE.md](docs/data/LINDSTROM-DATA-PROFILE.md) | `CT-PIM-DATA-001` — measured column-level profile of the real Lindström sources: lineage, key spaces, coverage, format hazards, defects found. |
| [docs/data/V1-ASSEMBLY-REFERENCE.md](docs/data/V1-ASSEMBLY-REFERENCE.md) | `CT-PIM-V1-ASM-001` — how the existing loader assembles the dataset (joins, precedence, derivation, packing), read from its source. The authoring basis for the Lindström brand pack. |
| [docs/architecture/V1-LOADER-ASSESSMENT.md](docs/architecture/V1-LOADER-ASSESSMENT.md) | `CT-PIM-V1-ASSESS-001` — why the existing loader cannot extend to other brands, with file:line evidence, and what to harvest from it. |
| [docs/requirements/MULTI-BRAND-LOADER-REQUIREMENTS.md](docs/requirements/MULTI-BRAND-LOADER-REQUIREMENTS.md)<br>[docs/requirements/LOADER-NG-REQUIREMENTS.md](docs/requirements/LOADER-NG-REQUIREMENTS.md) | The two 2026-08-17 source specifications. **Superseded** by the baseline — retained for provenance. Never cite as binding. |

## Binding decisions (operator, 2026-08-19)

- **D-1** Source specs **merged**; the baseline is the only binding document.
- **D-2** Built data: **SQLite authoritative + deterministic canonical text export**
  for diffing and version control.
- **D-3** On verification failure: **halt and wait for the operator**; never auto-rollback.
- **D-4** Stack: **Python 3.12+ single CLI**, justified in ADR-1.
- **D-5** Two subsystems: **PIM core** (system of record) and **Distribution chain**
  (channel publication), joined by the built-data contract.
- **D-6** **Code must not drive the brands:** the engine defines operations; the brand
  pack defines everything about the data — fields, types, formats, amounts,
  relationships. No field name, brand, count, or format in code.
- **D-7** **Primary/alias conflicts halt** for operator ruling via override; neither
  value ships un-ruled.
- **D-8** (A1, 2026-10-18) SKU grammar `{brand}.{mpn}[-{cond}][.M|.n|.P<qty>]` — dots between
  the parts, never a dash after the brand number.

Mandatory guarantees: nothing unwritable · backup and rollback on every run ·
per-field change selection · CSV export/import for bulk edits.

Open questions are tracked in the baseline spec **§11.2** and A1 **§6**.

## Ground rules carried forward from the first-generation loader

- Every catastrophic defect in this program's history was **silent**. A check that can
  only report success is not a check (`SRS §0.3, §4.9`).
- Safety comes from **visibility and reversibility, never prohibition**. A field the
  operator cannot change is a defect, not a safeguard (`SRS §0.2, P2`).
- Never put anything on the site that isn't true. Where the vendor is silent, omit
  (`SRS §4.12`).

## Repository conventions

- Vendor spreadsheets, build output (`var/`), ledgers, snapshots and logs are **not**
  committed (see `.gitignore`). Test fixtures that must be versioned are added with
  `git add -f`.
- Secrets are supplied at run time and never stored in the working folder (`NFR-14`).
- Line endings: LF in the repository, native in the working tree (see `.gitattributes`).
