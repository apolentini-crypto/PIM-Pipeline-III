# PIM-Pipeline-III

Third-generation Castletronics product data pipeline: ingest vendor spreadsheets
for **any brand**, normalise to one canonical row per SKU, derive facets/specs/
families, and publish to a commerce endpoint — validated, verified and reversible.

Nothing is implemented yet. This repository currently holds requirements only.

## Documents

| Path | What it is |
|---|---|
| [docs/requirements/MULTI-BRAND-LOADER-REQUIREMENTS.md](docs/requirements/MULTI-BRAND-LOADER-REQUIREMENTS.md) | Multi-Brand Product Data Loader — Requirements Specification **v1.1** (2026-08-17), status *For implementation*. Brand packs, endpoint plugin, change sets, validation, backup/rollback. |
| [docs/requirements/LOADER-NG-REQUIREMENTS.md](docs/requirements/LOADER-NG-REQUIREMENTS.md) | `CT-LOADER-NG-SRS-001` — Next-Generation Loader Requirements (2026-08-17), status *Draft for design — not baselined*. Generalization, gates and controls, BigCommerce write semantics, truth rules. |

Both are dated 2026-08-17 and overlap substantially. **Which one is binding has not
been decided** — resolve before any design or code is written against them.

## Ground rules carried forward from the first-generation loader

- Every catastrophic defect in this program's history was **silent**. A check that can
  only report success is not a check (`LOADER-NG §7`).
- Safety comes from **visibility and reversibility, never prohibition**. A field the
  operator cannot change is a defect, not a safeguard (`MULTI-BRAND §0.1, P2`).
- Never put anything on the site that isn't true. Where the vendor is silent, omit.

## Repository conventions

- Vendor spreadsheets, build output, ledgers, snapshots and logs are **not** committed
  (see `.gitignore`). Test fixtures that must be versioned are added with `git add -f`.
- Secrets are supplied at run time and never stored in the working folder (`NFR-003`).
- Line endings: LF in the repository, native in the working tree (see `.gitattributes`).
