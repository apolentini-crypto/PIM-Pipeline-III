"""`pim` command tree (ARCH §10). Thin: no logic here, only wiring.

M0 verbs:  pim <brand> validate-pack · pim sku parse|build · pim schemas · pim checks
Later:     build · export · export-csv · import-csv · diff · snapshot · publish · verify · rollback …
Exit codes: 0 clean · 1 halt (gate/validation) · 3 refused.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pim.config.loader import load_store, validate_pack
from pim.config.schema_gen import write_schemas
from pim.util.sku import SkuError, SkuGrammar, build_sku, parse_sku

REPO = Path(__file__).resolve().parents[2]
STORE = REPO / "store" / "store.yaml"
BRANDS = REPO / "brands"
import os
VAR = Path(os.environ.get("PIM_VAR_DIR") or (REPO / "var"))   # PIM_VAR_DIR moves the store/exports elsewhere


def _pack(brand: str) -> Path:
    return Path(brand) if Path(brand).is_dir() else BRANDS / brand


def _current_rows(brand: str):
    from pim.store.db import latest_build_id, open_db, read_build
    con = open_db(VAR / brand / "pim.db")
    bid = latest_build_id(con)
    if not bid:
        print("no build yet — run: pim build <brand>"); return None, None
    return bid, read_build(con, bid)


def cmd_build(args) -> int:
    from pim.build import build
    from pim.normalize.core import HaltError
    pack = _pack(args.brand)
    try:
        r = build(pack, VAR, source_root_override=Path(args.source_root) if args.source_root else None, write=not args.dry_run)
    except HaltError as e:
        print(f"HALT: {e}"); return 1
    print(f"build {r.build_id}  brand={r.brand}  rows={len(r.rows)}  held={len(r.held)}  overrides={len(r.applied_overrides)}")
    for st in r.stamps:
        print(f"  source {st.source_id:4} sha256={st.sha256[:12]} size={st.size} mtime={st.mtime_iso}")
    for k, a in r.assertions.items():
        if k == "COVERAGE":
            cov = a["measured"]; n = len(r.rows)
            print("  coverage: " + ", ".join(f"{f}={c}/{n}" for f, c in cov.items()))
        else:
            print(f"  [{'PASS' if a['ok'] else 'FAIL'}] {k}: measured {a['measured']} expected {a['expected']}")
    for w in r.warnings:
        print(f"  warn  {w}")
    alias_notes = [n for n in r.notes if "alias" in n]
    print(f"  alias-supplied values: {len(alias_notes)}" + (f" (e.g. {alias_notes[0]})" if alias_notes else ""))
    if r.export_path:
        print(f"  export {r.export_path.relative_to(REPO)}  rows_sha256={r.rows_sha256[:16]}")
    return 0


def cmd_diff(args) -> int:
    from pim.store.export import diff_exports, read_export
    a = read_export(VAR / args.brand / "exports" / args.build_a / "rows.jsonl")
    b = read_export(VAR / args.brand / "exports" / args.build_b / "rows.jsonl")
    d = diff_exports(a, b)
    print(json.dumps(d["counts"]))
    for sku in d["added"][:20]: print(f"  + {sku}")
    for sku in d["removed"][:20]: print(f"  - {sku}")
    for sku, fs in list(d["changed"].items())[:40]:
        for f, c in fs.items():
            print(f"  ~ {sku}.{f}: {c['before']!r} -> {c['after']!r}")
    return 0


def cmd_builds(args) -> int:
    from pim.store.db import open_db
    con = open_db(VAR / args.brand / "pim.db")
    for bid, created, n in con.execute("SELECT build_id, created, row_count FROM builds ORDER BY created"):
        print(f"{bid}  {created}  rows={n}")
    return 0


def cmd_export_csv(args) -> int:
    from pim.store.csv_io import export_csv
    bid, rows = _current_rows(args.brand)
    if rows is None: return 1
    fields = args.fields.split(",") if args.fields else sorted({f for r in rows.values() for f in r})
    out = Path(args.out) if args.out else VAR / args.brand / "edits" / f"{args.brand}-{bid}.csv"
    p = export_csv(rows, fields, out, skus=args.rows.split(",") if args.rows else None)
    print(f"wrote {p} ({len(rows)} rows × {len(fields)} fields) + {p.with_suffix('.types.json').name}")
    return 0


def cmd_import_csv(args) -> int:
    from pim.config.loader import validate_pack as vp
    from pim.store.csv_io import import_csv, write_overrides
    bid, rows = _current_rows(args.brand)
    if rows is None: return 1
    declared = set(vp(_pack(args.brand)).models["fields.yaml"].fields)
    rep = import_csv(Path(args.file), rows, declared)
    c = rep["counts"]
    print(f"change set vs build {bid}: {c['changes']} change(s) across {len(c['by_field'])} field(s); {c['damage']} suspected damage; {c['unknown_skus']} unknown SKU(s); {c['unknown_columns']} unknown column(s)")
    for f, n in sorted(c["by_field"].items()): print(f"  {f}: {n}")
    for ch in rep["changes"][:30]: print(f"  ~ {ch['sku']}.{ch['field']}: {ch['before']!r} -> {ch['after']!r}")
    for dm in rep["damage"][:30]: print(f"  ! {dm['sku']}.{dm['field']}: {dm['before']!r} -> {dm['after']!r}  suspected {dm['suspected']}")
    if rep["unknown_columns"]: print(f"  refused: unknown columns {rep['unknown_columns']} (FR-138: declare the field first)")
    if not args.apply:
        print("dry run — nothing written. Add --apply to land these as overrides."); return 0
    if rep["damage"] or rep["unknown_columns"]:
        print("REFUSED: resolve suspected damage / unknown columns first (FR-139)"); return 1
    if not rep["changes"]:
        print("empty change set — nothing to apply (FR-83)"); return 0
    p = write_overrides(_pack(args.brand), rep["changes"], args.who, args.why or f"csv import {Path(args.file).name}")
    print(f"wrote {p} — rebuild to apply: pim build {args.brand}")
    return 0


def _store():
    return load_store(STORE)


def cmd_validate_pack(args) -> int:
    pack = BRANDS / args.brand if not Path(args.brand).is_dir() else Path(args.brand)
    rep = validate_pack(pack)
    m = rep.measurement()
    print(f"G-PACK {pack}: files present {m['files_present']}/{m['files_declared']} · valid {m['files_valid']} · errors {m['errors']} · warnings {m['warnings']}")
    for w in rep.warnings:
        print(f"  warn  {w}")
    for e in rep.errors:
        print(f"  ERROR {e}")
    print("RESULT: " + ("pack valid" if rep.ok else f"HALT — {m['errors']} error(s); fix the pack, nothing was read"))
    return 0 if rep.ok else 1


def cmd_sku(args) -> int:
    g = SkuGrammar.from_store(_store())
    try:
        if args.sku_cmd == "parse":
            for s in args.sku:
                k = parse_sku(s, g)
                print(f"{s}: brand={k.brand} mpn={k.mpn} condition={k.condition} ending={k.ending_kind}:{k.ending}")
        else:
            print(build_sku(args.brand_id, args.mpn, g, condition=args.condition, pack_qty=args.pack, unit_seq=args.unit, master=args.master))
        return 0
    except SkuError as e:
        print(f"HALT: {e}")
        return 1


def cmd_schemas(args) -> int:
    for p in write_schemas(REPO / "docs" / "schemas"):
        print(f"wrote {p.relative_to(REPO)}")
    return 0


def cmd_checks(args) -> int:
    import pim.verify.gates  # noqa: F401  registers the checks
    from pim.verify.check import checks, corruptors
    try:
        sys.path.insert(0, str(REPO))
        import tests.corruptors  # noqa: F401  registers the corruptors (ADR-7)
    except ImportError as e:
        print(f"note: corruptors not importable ({e}); run from the repo root")

    cs, cr = checks(), corruptors()
    for cid, c in cs.items():
        print(f"{cid:16} {c.requirement:12} corruptor={'yes' if cid in cr else 'MISSING'}")
    missing = [c for c in cs if c not in cr]
    print(f"checks {len(cs)} · with corruptor {len(cs) - len(missing)} · missing {len(missing)}")
    return 1 if missing else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pim", description="Castletronics PIM Pipeline III")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate-pack", help="G-PACK: validate a brand pack, every error at once")
    p.add_argument("brand", help="brand slug under brands/ or a pack directory")
    p.set_defaults(fn=cmd_validate_pack)

    p = sub.add_parser("sku", help="parse or build SKUs under the store grammar (D-8)")
    ss = p.add_subparsers(dest="sku_cmd", required=True)
    pp = ss.add_parser("parse"); pp.add_argument("sku", nargs="+")
    pb = ss.add_parser("build")
    pb.add_argument("brand_id"); pb.add_argument("mpn")
    pb.add_argument("--condition"); pb.add_argument("--pack", type=int); pb.add_argument("--unit", type=int)
    pb.add_argument("--master", action="store_true")
    p.set_defaults(fn=cmd_sku)

    p = sub.add_parser("build", help="stages 1-4: ingest, merge, overrides, store, canonical export (no network)")
    p.add_argument("brand"); p.add_argument("--source-root", help="override sources.yaml source_root"); p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("builds", help="list builds in the store"); p.add_argument("brand"); p.set_defaults(fn=cmd_builds)
    p = sub.add_parser("diff", help="diff two builds' canonical exports (FR-42)")
    p.add_argument("brand"); p.add_argument("build_a"); p.add_argument("build_b"); p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("export-csv", help="bulk-edit sheet of the current build (FR-137)")
    p.add_argument("brand"); p.add_argument("--fields"); p.add_argument("--rows"); p.add_argument("-o", "--out"); p.set_defaults(fn=cmd_export_csv)
    p = sub.add_parser("import-csv", help="diff an edited sheet against the build; --apply lands overrides (FR-138/139)")
    p.add_argument("brand"); p.add_argument("file"); p.add_argument("--apply", action="store_true")
    p.add_argument("--who", default="operator"); p.add_argument("--why"); p.set_defaults(fn=cmd_import_csv)

    p = sub.add_parser("schemas", help="write JSON schemas for pack files to docs/schemas/")
    p.set_defaults(fn=cmd_schemas)

    p = sub.add_parser("checks", help="list registered checks and whether each has a corruptor")
    p.set_defaults(fn=cmd_checks)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
