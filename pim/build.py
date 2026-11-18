"""`pim <brand> build` — Stages 1, 2 and 4 (M1). Stage 2b (decide) and Stage 3 (derive) arrive in M2.

Order (ARCH §5.1): validate pack → ingest (hash) → merge → aliases+provenance → units/encoding
→ overrides (pre-value matched) → expectations → gates → write store → canonical export → manifest.
Every halt names SKU, field, observed value and the rule.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from pim import __version__
from pim.config.loader import PackReport, validate_pack
from pim.ingest.readers import IngestError, RawFrame, SourceStamp, read_source
from pim.normalize.core import CanonicalRow, HaltError, Merger, encoding_issues, resolve_field
from pim.normalize.overrides import apply_overrides, load_overrides
from pim.store.db import open_db, write_build, write_catalog
from pim.store.export import write_export, write_catalog_export


@dataclass
class BuildResult:
    brand: str
    build_id: str
    rows: dict[str, CanonicalRow]
    held: dict[str, str]
    stamps: list[SourceStamp]
    warnings: list[str]
    notes: list[str]
    assertions: dict[str, dict]          # name -> {"measured":..., "expected":..., "ok":...}
    applied_overrides: list[str]
    catalog: dict = field(default_factory=dict)          # sku -> CatalogRow (Stage 2b)
    decide_counts: dict = field(default_factory=dict)
    export_path: Path | None = None
    rows_sha256: str | None = None
    manifest: dict = field(default_factory=dict)


def _pack_hash(pack_dir: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(pack_dir.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            # line endings are normalised so the same pack gives the same build id on Windows
            # (git autocrlf, Excel-saved CSV) and elsewhere; content bytes otherwise untouched
            h.update(p.relative_to(pack_dir).as_posix().encode()); h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def build(pack_dir: Path, var_dir: Path, *, source_root_override: Path | None = None, write: bool = True) -> BuildResult:
    rep: PackReport = validate_pack(pack_dir)
    if not rep.ok:
        raise HaltError("G-PACK: " + "; ".join(str(e) for e in rep.errors))
    m = rep.models
    brand = m["brand.yaml"]
    sources = m["sources.yaml"]
    joins = m["joins.yaml"]
    fields = m["fields.yaml"].fields
    expectations = m.get("expectations.yaml")
    warnings: list[str] = [str(w) for w in rep.warnings]
    notes: list[str] = []

    # ---- Stage 1: ingest (FR-6..13)
    root = source_root_override or Path(sources.source_root)
    if not root.is_absolute():
        root = (pack_dir / root).resolve()
    frames: dict[str, list[RawFrame]] = {}
    stamps: list[SourceStamp] = []
    for s in sources.sources:
        try:
            fl, st = read_source(s, root)
        except IngestError as e:
            raise HaltError(f"INGEST {e}")
        if st is None:
            warnings.append(f"{s.id}: optional source absent ({s.path}) — FR-13")
            continue
        frames[s.id] = fl
        stamps.append(st)

    # ---- Stage 2: merge (FR-14..17)
    merger = Merger(joins, frames)
    roster = merger.roster()
    rows: dict[str, CanonicalRow] = {}
    conflicts: list[str] = []
    enc_issues: list[str] = []
    missing_required: list[str] = []
    for key in roster:
        row = CanonicalRow(key)
        for fname, decl in fields.items():
            fv, fnotes = resolve_field(fname, decl, merger, key)
            notes.extend(fnotes)
            if fv is None:
                if decl.required:
                    missing_required.append(f"{key}.{fname}")
                continue
            for bad, good in brand.text_fixes.items():
                if bad in fv.value:
                    fv.value = fv.value.replace(bad, good)
                    notes.append(f"{key}.{fname}: text fix {bad!r}->{good!r} applied (brand.yaml text_fixes)")
            for issue in encoding_issues(fv.value):
                enc_issues.append(f"{key}.{fname}: {issue} in {fv.value[:40]!r}")
            row.fields[fname] = fv
        rows[key] = row

    # ---- overrides (FR-25/26)
    applied = apply_overrides(rows, load_overrides(pack_dir), set(fields))

    # ---- holds (FR-46): decisions/ arrives in M2; for M1 a simple holds.csv is honoured if present
    held: dict[str, str] = {}
    hp = pack_dir / "decisions" / "holds.csv"
    if hp.exists():
        import csv
        with hp.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("sku") in rows:
                    held[r["sku"]] = r.get("reason", "") or "held"

    # ---- assertions (FR-40, FR-101: measured numbers)
    assertions: dict[str, dict] = {
        "G-ROSTER": {"measured": len(roster), "expected": expectations.roster_count if expectations else None,
                     "ok": expectations is None or expectations.roster_count is None or abs(len(roster) - expectations.roster_count) <= expectations.tolerance},
        "G-REQUIRED": {"measured": len(missing_required), "expected": 0, "ok": not missing_required, "details": missing_required[:50]},
        "G-ENCODING": {"measured": len(enc_issues), "expected": 0, "ok": not enc_issues, "details": enc_issues[:50]},
    }
    # per-field coverage: a number the operator can read
    coverage = {f: sum(1 for r in rows.values() if f in r.fields) for f in fields}
    assertions["COVERAGE"] = {"measured": coverage, "expected": None, "ok": True}

    # ---- Stage 2b: DECIDE (A1) — only when the pack declares pricing.yaml and the brand has an id
    catalog = {}
    decide_counts = {}
    if m.get("pricing.yaml") is not None:
        from pim.decide.core import decide
        from pim.config.loader import load_store
        from pim.util.sku import SkuGrammar
        store_path = Path(__file__).resolve().parents[1] / "store" / "store.yaml"
        dres = decide(rows, pack_dir, brand, m["pricing.yaml"], SkuGrammar.from_store(load_store(store_path)), held)
        catalog = dres.catalog
        decide_counts = dres.counts
        notes.extend(dres.notes)
        assertions.update(dres.assertions)

    # ---- build id (deterministic over inputs — NFR-1)
    h = hashlib.sha256()
    for st in stamps:
        h.update(st.source_id.encode()); h.update(st.sha256.encode())
    h.update(_pack_hash(pack_dir).encode()); h.update(__version__.encode())
    build_id = h.hexdigest()[:16]
    created = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    manifest = {
        "brand": brand.slug, "build_id": build_id, "created": created, "tool_version": __version__,
        "sources": [{"id": s.source_id, "sha256": s.sha256, "size": s.size, "mtime": s.mtime_iso, "path": s.path} for s in stamps],
        "overrides_applied": applied, "row_count": len(rows), "held_count": len(held),
        "assertions": assertions, "warnings": warnings,
    }
    failed = [k for k, a in assertions.items() if not a["ok"]]
    manifest["catalog_rows"] = len(catalog); manifest["carry_counts"] = decide_counts
    res = BuildResult(brand.slug, build_id, rows, held, stamps, warnings, notes, assertions, applied, catalog=catalog, decide_counts=decide_counts, manifest=manifest)
    if failed:
        det = "; ".join(f"{k}: measured {assertions[k]['measured']} expected {assertions[k]['expected']} {assertions[k].get('details', '')[:5] if isinstance(assertions[k].get('details'), list) else ''}" for k in failed)
        raise HaltError(f"BUILD HALT — failed assertions {failed}: {det}")

    if write:
        flat = {sku: {f: (fv.value, fv.unit, fv.prov.kind, fv.prov.ref) for f, fv in r.fields.items()} for sku, r in rows.items()}
        con = open_db(var_dir / brand.slug / "pim.db")
        write_build(con, build_id, created, __version__, _pack_hash(pack_dir), "", flat, held, manifest)
        con.close()
        res.export_path, res.rows_sha256 = write_export(var_dir / brand.slug / "exports" / build_id, flat, held, manifest)
        manifest["rows_sha256"] = res.rows_sha256
        if catalog:
            cflat = {sku: {f: (fv.value, fv.unit, fv.prov.kind, fv.prov.ref) for f, fv in r.fields.items()} for sku, r in catalog.items()}
            cmeta = {sku: {"mpn": r.mpn, "kind": r.kind, "parent_mpn": r.parent_mpn, "pack_qty": r.pack_qty, "held": r.held, "price_basis": r.price_basis, "unpriced": r.unpriced, "margin_pct": r.margin_pct} for sku, r in catalog.items()}
            con = open_db(var_dir / brand.slug / "pim.db")
            write_catalog(con, build_id, cflat, cmeta)
            con.close()
            write_catalog_export(var_dir / brand.slug / "exports" / build_id, cflat, cmeta)
    return res


# ----------------------------------------------------------------- decision sheet round trip (A1 FR-171a/b/c)
# One implementation for the window and the command line.
STORE_PATH = Path(__file__).resolve().parents[1] / "store" / "store.yaml"


def _grammar():
    from pim.config.loader import load_store
    from pim.util.sku import SkuGrammar
    return SkuGrammar.from_store(load_store(STORE_PATH))


def export_decision_sheet(pack_dir: Path, var_dir: Path, extra_fields: list[str], out: Path | None = None, *, source_root_override: Path | None = None, write: bool = True) -> dict:
    """Dry-run build, then write the one-row-per-CT-SKU sheet. Returns path, counts and a preview."""
    from pim.decide.core import decision_sheet_rows, load_decisions, load_derivatives, write_sheet
    rep = validate_pack(pack_dir)
    if not rep.ok:
        raise HaltError("G-PACK: " + "; ".join(str(e) for e in rep.errors))
    r = build(pack_dir, var_dir, write=False, source_root_override=source_root_override)
    brand = rep.models["brand.yaml"]; pricing = rep.models["pricing.yaml"]
    if pricing is None:
        raise HaltError("this brand has no pricing.yaml — the Decide stage needs it (A1 §3.5)")
    header, rows = decision_sheet_rows(r.rows, load_decisions(pack_dir), load_derivatives(pack_dir), pricing, extra_fields,
                                       catalog=r.catalog, brand=brand, grammar=_grammar())
    out = out or (var_dir / brand.slug / "edits" / f"{brand.slug}-decisions.csv")
    if write:
        write_sheet(out, header, rows)
    counts: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for row in rows:
        counts[row[3]] = counts.get(row[3], 0) + 1
        k = "pack" if row[2].startswith("pack") else row[2]
        kinds[k] = kinds.get(k, 0) + 1
    return {"path": str(out), "written": write, "rows": len(rows), "counts": counts, "kinds": kinds, "header": header, "preview": rows[:12],
            "unpriced": sum(1 for row in rows if row[header.index("— unpriced")] == "yes")}


def import_decision_sheet(pack_dir: Path, var_dir: Path, sheet_path: Path, *, apply: bool, who: str = "", why: str = "", source_root_override: Path | None = None) -> dict:
    """Diff (and with apply=True, save) an edited sheet. Every editable cell is validated first (FR-171b)."""
    import csv
    from pim.decide.core import apply_sheet, diff_decisions, load_decisions, load_derivatives
    rep = validate_pack(pack_dir)
    if not rep.ok:
        raise HaltError("G-PACK: " + "; ".join(str(e) for e in rep.errors))
    pricing = rep.models["pricing.yaml"]
    r = build(pack_dir, var_dir, write=False, source_root_override=source_root_override)
    with sheet_path.open("r", encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        missing = [c for c in ("mpn", "carry_state") if c not in (rd.fieldnames or [])]
        if missing:
            return {"error": f"this is not a decision sheet — column(s) {missing} are missing (export one from the Decide stage)"}
        sheet = list(rd)
    derivs = load_derivatives(pack_dir)
    d = diff_decisions(load_decisions(pack_dir), sheet, set(r.rows), derivs, pricing.fulfillment_vocabulary if pricing else [], who, why)
    res = {"changes": d["changes"][:300], "unknown": d["unknown_mpns"][:50], "counts": d["counts"], "errors": len(d["errors"])}
    if apply:
        if d["errors"]:
            res["refused"] = "fix the errors first"
        elif not d["changes"]:
            res["refused"] = "no changes — nothing to apply"
        else:
            w = apply_sheet(pack_dir, d, derivs, who, why, sheet_path.name)
            res["written"] = w["decisions"]
            if "derivatives" in w:
                res["written_derivatives"] = w["derivatives"]
    return res
