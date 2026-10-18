"""`pim` command tree (ARCH §10). Thin: no logic here, only wiring.

M0 verbs:  pim <brand> validate-pack · pim sku parse|build · pim schemas · pim checks
Later:     build · export · export-csv · import-csv · diff · snapshot · publish · verify · rollback …
Exit codes: 0 clean · 1 halt (gate/validation) · 3 refused.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pim.config.loader import load_store, validate_pack
from pim.config.schema_gen import write_schemas
from pim.util.sku import SkuError, SkuGrammar, build_sku, parse_sku

REPO = Path(__file__).resolve().parents[2]
STORE = REPO / "store" / "store.yaml"
BRANDS = REPO / "brands"


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

    p = sub.add_parser("schemas", help="write JSON schemas for pack files to docs/schemas/")
    p.set_defaults(fn=cmd_schemas)

    p = sub.add_parser("checks", help="list registered checks and whether each has a corruptor")
    p.set_defaults(fn=cmd_checks)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
