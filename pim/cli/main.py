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
            if isinstance(a["expected"], str):  # a count reported now, enforced at publish
                print(f"  [INFO] {k}: {a['measured']} — {a['expected']}")
            else:
                print(f"  [{'PASS' if a['ok'] else 'FAIL'}] {k}: measured {a['measured']} expected {a['expected']}")
    for w in r.warnings:
        print(f"  warn  {w}")
    alias_notes = [n for n in r.notes if "alias" in n]
    print(f"  alias-supplied values: {len(alias_notes)}" + (f" (e.g. {alias_notes[0]})" if alias_notes else ""))
    if r.decide_counts:
        print(f"  decide: {r.decide_counts} → catalog rows {len(r.catalog)} " + str({k: sum(1 for c in r.catalog.values() if c.kind == k) for k in ("original", "pack", "kit")}))
        for n in [x for x in r.notes if x.startswith("PLAUSIBILITY") or x.startswith("kit ") or "decision for" in x][:10]:
            print(f"  note  {n}")
    if r.export_path:
        ep = r.export_path
        try:
            ep = ep.relative_to(REPO)
        except ValueError:
            pass
        print(f"  export {ep}  rows_sha256={r.rows_sha256[:16]}")
    return 0


def cmd_diff(args) -> int:
    from pim.store.export import diff_catalogs, diff_exports, read_export
    da, db = VAR / args.brand / "exports" / args.build_a, VAR / args.brand / "exports" / args.build_b

    def show(d: dict) -> None:
        print("  " + json.dumps(d["counts"]))
        for sku in d["added"][:20]: print(f"  + {sku}")
        for sku in d["removed"][:20]: print(f"  - {sku}")
        for sku, fs in list(d["changed"].items())[:40]:
            for f, c in fs.items():
                print(f"  ~ {sku}.{f}: {c['before']!r} -> {c['after']!r}")

    print("products (one per vendor part number):")
    show(diff_exports(read_export(da / "rows.jsonl"), read_export(db / "rows.jsonl")))
    if (da / "catalog.jsonl").exists() and (db / "catalog.jsonl").exists():
        print("catalog (one per CT SKU — decisions, packs, kits, prices):")
        show(diff_catalogs(read_export(da / "catalog.jsonl"), read_export(db / "catalog.jsonl")))
    else:
        print("catalog: no catalog export for one of the builds")
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


def _models(brand):
    rep = validate_pack(_pack(brand))
    if not rep.ok:
        print("HALT: " + "; ".join(str(e) for e in rep.errors)); return None
    return rep.models


def cmd_export_decisions(args) -> int:
    """FR-171a: the decision sheet — one row per CT SKU (packs under their parent, kits last) + context."""
    from pim.build import export_decision_sheet
    from pim.normalize.core import HaltError
    extra = [f.strip() for f in (args.fields or "").split(",") if f.strip()]
    try:
        r = export_decision_sheet(_pack(args.brand), VAR, extra, Path(args.out) if args.out else None, source_root_override=Path(args.source_root) if args.source_root else None)
    except HaltError as e:
        print(f"HALT: {e}"); return 1
    print(f"wrote {r['path']} ({r['rows']} rows: {r['kinds']}). carry states: {r['counts']}; unpriced: {r['unpriced']}")
    print("Edit the columns without a '—' prefix (mpn is the key; a pack's key is PARENT.P5). '—' columns are context, ignored on import.")
    return 0


def cmd_import_decisions(args) -> int:
    from pim.build import import_decision_sheet
    from pim.normalize.core import HaltError
    try:
        d = import_decision_sheet(_pack(args.brand), VAR, Path(args.file), apply=args.apply, who=args.who or "", why=args.why or "", source_root_override=Path(args.source_root) if args.source_root else None)
    except HaltError as e:
        print(f"HALT: {e}"); return 1
    if "error" in d:
        print(f"ERROR: {d['error']}"); return 1
    c = d["counts"]
    print(f"decision changes: {c['changes']} across {len(c['by_field'])} column(s); {c['unknown']} unknown key(s); {c['errors']} error(s); {c['new_packs']} new pack(s)")
    for ch in d["changes"][:60]:
        print(f"  row {ch.get('row','?')}  {ch['mpn']}.{ch['field']}: {ch['before']!r} -> {ch['after']!r}" + (f"  ERROR {ch['error']}" if "error" in ch else ""))
    if d["unknown"]: print(f"  unknown (ignored): {d['unknown'][:20]}")
    if not args.apply:
        print("dry run — nothing written. Add --apply to save these decisions."); return 0
    if d.get("refused"):
        print(f"REFUSED: {d['refused']}"); return 1 if d["errors"] else 0
    print(f"wrote {d['written']}" + (f" and {d['written_derivatives']}" if d.get("written_derivatives") else "") + f" — run: pim build {args.brand}")
    return 0


def cmd_seed_decisions(args) -> int:
    """One-time: derive starting carry states from fields already in the build (declared on the command line)."""
    from pim.build import build
    from pim.decide.core import Decision, load_decisions, write_decisions
    from pim.normalize.core import HaltError
    import datetime as dt
    try:
        r = build(_pack(args.brand), VAR, write=False)
    except HaltError as e:
        print(f"HALT: {e}"); return 1
    cur = load_decisions(_pack(args.brand))
    if cur and not args.force:
        print(f"{len(cur)} decisions already exist; use --force to overwrite"); return 1
    when = dt.datetime.now().date().isoformat()
    out = {}; counts = {}
    for mpn, row in r.rows.items():
        state, reason = "undecided", ""
        if args.carry_if and args.carry_if in row.fields and row.fields[args.carry_if].value:
            state = "carry"
        if args.hold_if:
            f, _, v = args.hold_if.partition("=")
            if f in row.fields and row.fields[f].value == v:
                state, reason = "carry", f"{f}={v}"
        out[mpn] = Decision(mpn, state, reason, "", "", "", args.who, when, f"seeded: carry_if={args.carry_if} hold_if={args.hold_if}")
        counts[state + (" (held)" if reason else "")] = counts.get(state + (" (held)" if reason else ""), 0) + 1
    p = write_decisions(_pack(args.brand), out)
    print(f"wrote {p}: {counts}")
    return 0


def cmd_ui(args) -> int:
    from pim.ui.server import serve
    serve(port=args.port, open_browser=not args.no_browser)
    return 0


def cmd_status(args) -> int:
    from pim.ui.server import source_status
    st = source_status(args.brand)
    print(f"last build: {st['build_id'] or '(none)'} {st['built'] or ''}")
    for r in st["sources"]:
        extra = f"  size {r.get('was_size')} -> {r.get('size')}" if r["state"] == "changed" else ""
        print(f"  {r['state']:9} {r['id']:4} {r['path']}{extra}")
    s = st["summary"]
    print(f"unchanged {s['unchanged']} · changed {s['changed']} · new {s['new']} · missing {s['missing']}" + ("  → run: pim build " + args.brand if (s['changed'] or s['new']) else ""))
    return 0


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

    p = sub.add_parser("export-decisions", help="decision sheet: one row per CT SKU (A1 FR-171a)")
    p.add_argument("brand"); p.add_argument("--fields", help="extra context columns"); p.add_argument("-o", "--out"); p.add_argument("--source-root", help="override sources.yaml source_root"); p.set_defaults(fn=cmd_export_decisions)
    p = sub.add_parser("import-decisions", help="diff an edited decision sheet; --apply saves decisions/decisions.csv")
    p.add_argument("brand"); p.add_argument("file"); p.add_argument("--apply", action="store_true"); p.add_argument("--who", default="operator"); p.add_argument("--why"); p.add_argument("--source-root", help="override sources.yaml source_root"); p.set_defaults(fn=cmd_import_decisions)
    p = sub.add_parser("seed-decisions", help="one-time starting carry states from existing fields")
    p.add_argument("brand"); p.add_argument("--carry-if", help="field that, when non-empty, means carry (e.g. bc_product_id_live)")
    p.add_argument("--hold-if", help="field=value that marks a carried row as held (e.g. scrape_status=error_404)")
    p.add_argument("--who", default="operator"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_seed_decisions)

    p = sub.add_parser("ui", help="open the PIM window in your browser (local only)")
    p.add_argument("--port", type=int, default=8766); p.add_argument("--no-browser", action="store_true"); p.set_defaults(fn=cmd_ui)
    p = sub.add_parser("status", help="which source files changed since the last build (FR-11)")
    p.add_argument("brand"); p.set_defaults(fn=cmd_status)

    p = sub.add_parser("schemas", help="write JSON schemas for pack files to docs/schemas/")
    p.set_defaults(fn=cmd_schemas)

    p = sub.add_parser("checks", help="list registered checks and whether each has a corruptor")
    p.set_defaults(fn=cmd_checks)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
