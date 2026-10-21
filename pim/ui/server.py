"""`pim ui` — the local PIM window (setup → status → build → decide → derive → publish) (stdlib http.server, 127.0.0.1 only).

The page asks the questions; this module inspects files, renders the YAML (with the same
PyYAML the build reads), validates through the real validator, and writes brands/<slug>/.
The YAML files remain the only truth (D-6); this is a writer for them, nothing more.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import yaml

from pim.config.loader import validate_pack
from pim.ingest.readers import cell_text

REPO = Path(__file__).resolve().parents[2]
BRANDS = REPO / "brands"
STATIC = Path(__file__).resolve().parent / "static"

FORMATS = {".xlsx": "xlsx", ".xlsm": "xlsm", ".csv": "csv", ".json": "json"}


# ----------------------------------------------------------------- file inspection
def list_files(root: str) -> dict:
    p = Path(root)
    if not p.is_dir():
        return {"error": f"folder not found: {root}", "files": []}
    files = []
    for f in sorted(p.iterdir()):
        if f.is_file() and f.suffix.lower() in FORMATS and not f.name.startswith("~$"):
            files.append({"path": f.name, "format": FORMATS[f.suffix.lower()], "size": f.stat().st_size})
    return {"files": files, "root": str(p)}


def inspect(root: str, path: str, fmt: str, sheet: str | None, header_row: int, encoding: str = "utf-8-sig", max_cols: int = 80) -> dict:
    p = Path(path) if Path(path).is_absolute() else Path(root) / path
    if not p.exists():
        return {"error": f"file not found: {p}"}
    tmp = Path(tempfile.mkdtemp(prefix="pim-ui-")) / p.name
    shutil.copyfile(p, tmp)
    try:
        rows: list[list[str]] = []
        sheets: list[str] = []
        if fmt in ("xlsx", "xlsm"):
            import openpyxl
            wb = openpyxl.load_workbook(tmp, read_only=True, data_only=True)
            sheets = wb.sheetnames
            ws = wb[sheet] if sheet in wb.sheetnames else wb[wb.sheetnames[0]]
            sheet = ws.title
            for i, r in enumerate(ws.iter_rows(values_only=True, max_row=12, max_col=max_cols)):
                rows.append([cell_text(c) for c in r])
            total = ws.max_row
            wb.close()
        elif fmt == "csv":
            import csv
            with tmp.open("r", encoding=encoding, newline="") as fh:
                rd = csv.reader(fh)
                for i, r in enumerate(rd):
                    if i < 12:
                        rows.append(list(r)[:max_cols])
                total = i + 1
        else:  # json
            data = json.loads(tmp.read_text(encoding=encoding))
            if isinstance(data, dict):
                data = list(data.values())
            keys: list[str] = []
            nested: list[str] = []
            for rec in data[:50]:
                for k, v in rec.items():
                    if k not in keys:
                        keys.append(k)
                    if isinstance(v, dict) and k not in nested:
                        nested.append(k)
            rows.append(keys)
            for rec in data[:10]:
                rows.append([cell_text(rec.get(k)) if not isinstance(rec.get(k), (dict, list)) else f"<{type(rec.get(k)).__name__}>" for k in keys])
            total = len(data)
            return {"sheets": [], "sheet": None, "rows": rows, "total_rows": total, "headers": keys, "nested": nested}
        hr = max(1, header_row)
        headers = rows[hr - 1] if hr - 1 < len(rows) else []
        # trim trailing blank headers
        while headers and headers[-1] == "":
            headers = headers[:-1]
        return {"sheets": sheets, "sheet": sheet, "rows": rows, "total_rows": total, "headers": headers, "nested": []}
    except UnicodeDecodeError as e:
        return {"error": f"{p.name} is not {encoding}; try encoding cp1252 (byte {e.object[e.start:e.start+1]!r} at {e.start})"}
    except Exception as e:  # report, never crash the window
        return {"error": f"{type(e).__name__}: {e}"}
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


# ----------------------------------------------------------------- state -> pack files
def suggest_name(header: str) -> str:
    s = header.lower()
    s = re.sub(r"^[a-z]{2}_[a-z]{2}#", "", s)            # en_US#SHORT DESCRIPTION -> short description
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "field"


def _dump(doc: dict, header: str = "") -> str:
    body = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110)
    return (header + "\n" if header else "") + body


def render_pack(state: dict) -> dict[str, str]:
    b = state.get("brand", {})
    slug = b.get("slug") or "new-brand"
    brand = {
        "slug": slug,
        "display_name": b.get("display_name") or slug,
        "bc_brand_name": b.get("bc_brand_name") or b.get("display_name") or slug,
        "brand_id": int(b["brand_id"]) if str(b.get("brand_id") or "").strip().isdigit() else None,
        "mpn_normalisation": {"upper": True, "strip_whitespace": True, "replace": {".": "-"}, "allowed": "A-Z0-9_-", "trim": "-_"},
    }
    if b.get("text_fixes"):
        brand["text_fixes"] = b["text_fixes"]
    brand["environments"] = {
        "sandbox": {"kind": "sandbox", "store_hash_env": "BC_SANDBOX_STORE_HASH", "token_env": "BC_SANDBOX_ACCESS_TOKEN"},
        "live": {"kind": "live", "store_hash_env": "BC_STORE_HASH", "token_env": "BC_ACCESS_TOKEN"},
    }

    sources = []
    for s in state.get("sources", []):
        if not s.get("include"):
            continue
        d = {"id": s["id"], "path": s["path"], "format": s["format"]}
        if s["format"] in ("xlsx", "xlsm"):
            d["sheet"] = s.get("sheet")
        if s["format"] != "json" and int(s.get("header_row") or 1) != 1 or s["format"] in ("xlsx", "xlsm", "csv"):
            d["header_row"] = int(s.get("header_row") or 1)
        if s.get("blocks"):                      # declared in sources.yaml by hand; carried through untouched
            d["blocks"] = s["blocks"]
        elif s.get("key_index"):
            d["key_index"] = int(s["key_index"])
        else:
            d["key_column"] = s.get("key_column")
        if s.get("optional"):
            d["optional"] = True
        if s.get("multi"):
            d["multi"] = True
        if s.get("flatten"):
            d["flatten"] = s["flatten"]
        if s.get("encoding") and s["encoding"] != "utf-8-sig":
            d["encoding"] = s["encoding"]
        if s.get("max_cols"):
            d["max_cols"] = int(s["max_cols"])
        sources.append(d)
    sources_doc = {"source_root": b.get("source_root") or ".", "sources": sources}

    fields = {}
    for f in state.get("fields", []):
        prim = {"source": f["source"], "column": f["column"]}
        if f.get("block"):
            prim["block"] = f["block"]
        if f.get("where"):
            prim["where"] = f["where"]
        if f.get("column_unit"):
            prim["unit"] = f["column_unit"]
        d: dict = {"primary": prim}
        if f.get("aliases"):
            d["aliases"] = [{k: v for k, v in {"source": a["source"], "block": a.get("block"), "column": a["column"], "unit": a.get("unit"), "where": a.get("where")}.items() if v} for a in f["aliases"]]
        if f.get("unit_mode") == "in-value":
            d["unit"] = {"parse": "in-value", "expect": [u.strip() for u in (f.get("unit") or "").split(",") if u.strip()]}
            if f.get("decimal_comma"):
                d["unit"]["decimal_comma"] = True
        elif f.get("unit_mode") == "declared" and f.get("unit"):
            d["unit"] = {"parse": "declared", "unit": f["unit"]}
        if f.get("type") and f["type"] != "text":
            d["type"] = f["type"]
        if f.get("confirmed"):
            d["confirmed"] = "Y"
        if f.get("required"):
            d["required"] = True
        if f.get("alias_tolerance"):
            d["alias_tolerance"] = f["alias_tolerance"]
        fields[f["name"]] = d
    fields_doc = {"fields": fields}

    j = state.get("joins", {})
    joins_doc = {"primary_source": j.get("primary_source") or (sources[0]["id"] if sources else "S1"),
                 "key": {"rule": j.get("key_rule") or "trim-only"},
                 "associations": j.get("associations", [])}
    ex = state.get("expectations", {})
    expectations_doc = {"roster_count": int(ex["roster_count"]) if str(ex.get("roster_count") or "").isdigit() else None, "tolerance": 0}
    confirmed = [n for n, d in fields.items() if d.get("confirmed") == "Y"]
    managed_doc = {"managed": "all-mapped", "unmanaged": ["inventory_level", "is_visible", "sale_price"],
                   "owners": {n: "catalog" for n in confirmed}}
    endpoints_doc = {"endpoints": {"bc": {"adapter": "bigcommerce", "environments": ["sandbox", "live"],
                                          "field_map": {n: n for n in confirmed}, "custom_fields": [],
                                          "sentinel_empty_fields": ["related_products"]}}}
    pricing_doc = {"rules": [{"scope": "default", "basis": "msrp-passthrough", "basis_note": "setup default: price = list price; edit in pricing.yaml"}],
                   "unpriced_means": "hold"}
    return {
        "brand.yaml": _dump(brand, f"# {brand['display_name']} — brand identity. Written by `pim setup`; edit freely, it is the truth."),
        "sources.yaml": _dump(sources_doc, "# Files the build reads (READ-ONLY, FR-10). Headers are byte-exact (FR-111)."),
        "fields.yaml": _dump(fields_doc, "# canonical field -> source column. primary ELSE aliases (FR-18); disagreement halts (D-7)."),
        "joins.yaml": _dump(joins_doc, "# Roster = primary_source keys. Keys are trimmed, never altered inside (FR-15..17)."),
        "expectations.yaml": _dump(expectations_doc, "# Asserted counts; the build halts when measured != expected."),
        "managed.yaml": _dump(managed_doc, "# Managed fields and owners (FR-54..56). Confirmed fields are owned by `catalog`."),
        "endpoints.yaml": _dump(endpoints_doc, "# canonical -> endpoint field map (FR-104). Rename the right-hand side to the BC field names."),
        "pricing.yaml": _dump(pricing_doc, "# Pricing rules (A1 FR-154..159)."),
    }


def write_pack(state: dict, overwrite: bool) -> dict:
    slug = (state.get("brand", {}).get("slug") or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        return {"error": "slug must be lowercase letters, digits and dashes (e.g. pace-worldwide)"}
    d = BRANDS / slug
    files = render_pack(state)
    existing = [n for n in files if (d / n).exists()]
    if existing and not overwrite:
        return {"exists": existing}
    d.mkdir(parents=True, exist_ok=True)
    (d / "overrides").mkdir(exist_ok=True)
    (d / "decisions").mkdir(exist_ok=True)
    for n, text in files.items():
        (d / n).write_text(text, encoding="utf-8", newline="\n")
    for n, hdr in (("exclusions.csv", "sku,mpn,reason,date\n"), ("derivatives.csv", "parent_mpn,pack_qty,name,basis\n")):
        if not (d / n).exists():
            (d / n).write_text(hdr, encoding="utf-8", newline="\n")
    rep = validate_pack(d)
    return {"written": sorted(files), "dir": str(d), "errors": [str(e) for e in rep.errors], "warnings": [str(w) for w in rep.warnings]}


def validate_state(state: dict) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="pim-validate-"))
    try:
        for n, text in render_pack(state).items():
            (tmp / n).write_text(text, encoding="utf-8")
        rep = validate_pack(tmp)
        m = rep.measurement()
        return {"ok": rep.ok, "errors": [str(e) for e in rep.errors], "warnings": [str(w) for w in rep.warnings if "optional" not in str(w)],
                "files_valid": m["files_valid"], "files_present": m["files_present"]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def load_pack(slug: str) -> dict:
    """Best-effort: turn an existing pack back into window state so it can be edited."""
    d = BRANDS / slug
    if not d.is_dir():
        return {"error": f"no pack {slug}"}
    def rd(n):
        p = d / n
        return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    b, s, f, j, e = rd("brand.yaml"), rd("sources.yaml"), rd("fields.yaml"), rd("joins.yaml"), rd("expectations.yaml")
    sources = []
    for x in s.get("sources", []):
        sources.append({"include": True, "id": x["id"], "path": x["path"], "format": x["format"], "sheet": x.get("sheet"),
                        "header_row": x.get("header_row", 1), "key_column": x.get("key_column"), "key_index": x.get("key_index"),
                        "optional": x.get("optional", False), "multi": x.get("multi", False), "flatten": x.get("flatten", []),
                        "encoding": x.get("encoding", "utf-8-sig"), "max_cols": x.get("max_cols"), "blocks": x.get("blocks", [])})
    fields = []
    for name, x in f.get("fields", {}).items():
        u = x.get("unit") or {}
        fields.append({"name": name, "source": x["primary"]["source"], "column": x["primary"]["column"], "column_unit": x["primary"].get("unit"),
                       "block": x["primary"].get("block"), "where": x["primary"].get("where"),
                       "type": x.get("type", "text"), "unit_mode": u.get("parse", "none"),
                       "unit": ",".join(u.get("expect", [])) if u.get("parse") == "in-value" else u.get("unit", ""),
                       "decimal_comma": u.get("decimal_comma", False),
                       "required": x.get("required", False), "confirmed": x.get("confirmed") == "Y", "alias_tolerance": x.get("alias_tolerance"),
                       "aliases": x.get("aliases", [])})
    return {"brand": {"slug": b.get("slug"), "display_name": b.get("display_name"), "bc_brand_name": b.get("bc_brand_name"),
                      "brand_id": b.get("brand_id"), "source_root": s.get("source_root"), "text_fixes": b.get("text_fixes", {})},
            "sources": sources, "fields": fields,
            "joins": {"primary_source": j.get("primary_source"), "key_rule": (j.get("key") or {}).get("rule", "trim-only"), "associations": j.get("associations", [])},
            "expectations": {"roster_count": e.get("roster_count")}}


def _var() -> Path:
    import os
    return Path(os.environ.get("PIM_VAR_DIR") or (REPO / "var"))


def source_status(slug: str) -> dict:
    """FR-11: re-hash the files on disk and compare with the latest build's manifest."""
    import hashlib
    from pim.store.db import latest_build_id, open_db
    pack = BRANDS / slug
    src = yaml.safe_load((pack / "sources.yaml").read_text(encoding="utf-8")) if (pack / "sources.yaml").exists() else {}
    root = Path(src.get("source_root", "."))
    if not root.is_absolute():
        root = pack / root
    con = open_db(_var() / slug / "pim.db")
    bid = latest_build_id(con)
    last = {}
    created = None
    if bid:
        row = con.execute("SELECT manifest_json, created FROM builds WHERE build_id=?", (bid,)).fetchone()
        created = row[1]
        last = {m["id"]: m for m in json.loads(row[0]).get("sources", [])}
    con.close()
    out = []
    for sdecl in src.get("sources", []):
        p = Path(sdecl["path"]) if Path(sdecl["path"]).is_absolute() else root / sdecl["path"]
        rec = {"id": sdecl["id"], "path": sdecl["path"], "optional": sdecl.get("optional", False)}
        if not p.exists():
            rec["state"] = "missing"
        else:
            h = hashlib.sha256()
            with p.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            rec["sha256"] = h.hexdigest()[:12]; rec["size"] = p.stat().st_size
            prev = last.get(sdecl["id"])
            rec["state"] = "new" if not prev else ("unchanged" if prev["sha256"] == h.hexdigest() else "changed")
            if prev:
                rec["was_size"] = prev["size"]
        out.append(rec)
    gone = [i for i in last if i not in {s_["id"] for s_ in src.get("sources", [])}]
    return {"build_id": bid, "built": created, "sources": out, "removed_from_pack": gone,
            "summary": {k: sum(1 for r in out if r["state"] == k) for k in ("unchanged", "changed", "new", "missing")}}


def list_builds(slug: str) -> dict:
    from pim.store.db import open_db
    con = open_db(_var() / slug / "pim.db")
    rows = [{"build_id": b, "created": c, "rows": n} for b, c, n in con.execute("SELECT build_id, created, row_count FROM builds ORDER BY created DESC")]
    con.close()
    return {"builds": rows}


def diff_builds(slug: str, a: str, b: str) -> dict:
    from pim.store.export import diff_exports, read_export
    ea = _var() / slug / "exports" / a / "rows.jsonl"; eb = _var() / slug / "exports" / b / "rows.jsonl"
    if not ea.exists() or not eb.exists():
        return {"error": "export not found for one of the builds"}
    d = diff_exports(read_export(ea), read_export(eb))
    d["changed"] = dict(list(d["changed"].items())[:300])
    return d


def csv_export(slug: str, fields: list[str], out: str | None) -> dict:
    from pim.store.csv_io import export_csv
    from pim.store.db import latest_build_id, open_db, read_build
    con = open_db(_var() / slug / "pim.db"); bid = latest_build_id(con)
    if not bid:
        return {"error": "no build yet"}
    rows = read_build(con, bid); con.close()
    fields = fields or sorted({f for r in rows.values() for f in r})
    p = Path(out) if out else _var() / slug / "edits" / f"{slug}-{bid}.csv"
    export_csv(rows, fields, p)
    return {"path": str(p), "rows": len(rows), "fields": fields, "build_id": bid}


def csv_import(slug: str, path: str, apply: bool, who: str, why: str) -> dict:
    from pim.store.csv_io import import_csv, write_overrides
    from pim.store.db import latest_build_id, open_db, read_build
    con = open_db(_var() / slug / "pim.db"); bid = latest_build_id(con)
    if not bid:
        return {"error": "no build yet"}
    rows = read_build(con, bid); con.close()
    declared = set(yaml.safe_load((BRANDS / slug / "fields.yaml").read_text(encoding="utf-8"))["fields"])
    rep = import_csv(Path(path), rows, declared)
    rep["build_id"] = bid; rep["changes"] = rep["changes"][:300]; rep["damage"] = rep["damage"][:100]
    if apply:
        if rep["damage"] or rep["unknown_columns"]:
            rep["refused"] = "resolve suspected damage / unknown columns first (FR-139)"
        elif not rep["counts"]["changes"]:
            rep["refused"] = "empty change set — nothing to apply (FR-83)"
        else:
            rep["written"] = str(write_overrides(BRANDS / slug, rep["changes"], who or "operator", why or f"csv import {Path(path).name}"))
    return rep


def decision_sheet(slug: str, fields: list[str]) -> dict:
    import csv
    from pim.build import build
    from pim.decide.core import decision_sheet_rows, load_decisions, load_derivatives
    from pim.normalize.core import HaltError
    pack = BRANDS / slug
    rep = validate_pack(pack)
    if not rep.ok:
        return {"error": "; ".join(str(e) for e in rep.errors)}
    try:
        r = build(pack, _var(), write=False)
    except HaltError as e:
        return {"error": str(e)}
    header, rows = decision_sheet_rows(r.rows, load_decisions(pack), load_derivatives(pack), rep.models["pricing.yaml"], fields)
    out = _var() / slug / "edits" / f"{slug}-decisions.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL, lineterminator="\r\n"); w.writerow(header); w.writerows(rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row[1]] = counts.get(row[1], 0) + 1
    return {"path": str(out), "rows": len(rows), "counts": counts, "preview": rows[:12], "header": header}


def decision_import(slug: str, path: str, apply: bool, who: str, why: str) -> dict:
    import csv, datetime as dt
    from pim.build import build
    from pim.decide.core import diff_decisions, load_decisions, write_decisions
    from pim.normalize.core import HaltError
    pack = BRANDS / slug
    try:
        r = build(pack, _var(), write=False)
    except HaltError as e:
        return {"error": str(e)}
    p = Path(path)
    if not p.exists():
        return {"error": f"file not found: {path}"}
    with p.open("r", encoding="utf-8-sig", newline="") as fh:
        sheet = list(csv.DictReader(fh))
    d = diff_decisions(load_decisions(pack), sheet, set(r.rows))
    res = {"changes": d["changes"][:300], "unknown": d["unknown_mpns"][:50], "counts": d["counts"]}
    if apply:
        if d["errors"]:
            res["refused"] = "fix the errors first"
        elif not d["changes"]:
            res["refused"] = "no changes — nothing to apply"
        else:
            when = dt.datetime.now().date().isoformat()
            for ch in d["changes"]:
                nd = d["new_decisions"][ch["mpn"]]
                nd.who = nd.who or (who or "operator"); nd.when = nd.when or when; nd.why = nd.why or (why or f"decision sheet {p.name}")
            res["written"] = str(write_decisions(pack, d["new_decisions"]))
    return res


def catalog_view(slug: str) -> dict:
    from pim.store.db import latest_build_id, open_db, read_catalog
    con = open_db(_var() / slug / "pim.db"); bid = latest_build_id(con)
    if not bid:
        return {"error": "no build yet"}
    rows, meta = read_catalog(con, bid); con.close()
    out = []
    for sku in sorted(rows):
        f = rows[sku]; m = meta[sku]
        g = lambda k: f.get(k, ("",))[0]
        out.append({"sku": sku, "kind": m["kind"], "mpn": m["mpn"], "name": g("name")[:80], "price": g("price"), "basis": m["price_basis"],
                    "margin": (f"{m['margin_pct']:.1f}" if m["margin_pct"] is not None else ""), "held": m["held"] or "", "fulfillment": g("fulfillment"), "qty": g("initial_qty")})
    kinds = {k: sum(1 for r in out if r["kind"] == k) for k in ("original", "pack", "kit")}
    return {"build_id": bid, "rows": out[:500], "total": len(out), "kinds": kinds, "held": sum(1 for r in out if r["held"]), "unpriced": sum(1 for m in meta.values() if m["unpriced"])}


def run_build(slug: str, write: bool) -> dict:
    from pim.build import build
    from pim.normalize.core import HaltError
    try:
        r = build(BRANDS / slug, _var(), write=write)
    except HaltError as e:
        return {"ok": False, "halt": str(e)}
    except Exception as e:
        return {"ok": False, "halt": f"{type(e).__name__}: {e}"}
    cov = r.assertions.get("COVERAGE", {}).get("measured", {})
    return {"ok": True, "rows": len(r.rows), "build_id": r.build_id, "written": write, "overrides": r.applied_overrides,
            "decide_counts": r.decide_counts, "catalog_rows": len(r.catalog),
            "assertions": {k: {"ok": a["ok"], "measured": a["measured"], "expected": a["expected"]} for k, a in r.assertions.items() if k != "COVERAGE"},
            "coverage": cov, "warnings": r.warnings, "alias_notes": len([n for n in r.notes if "alias" in n]),
            "notes": [n for n in r.notes if "alias" not in n][:40]}


# ----------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            data = (STATIC / "app.html").read_bytes()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        elif path == "/api/brands":
            self._json({"brands": sorted(p.name for p in BRANDS.iterdir() if p.is_dir()) if BRANDS.exists() else [], "repo": str(REPO)})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        path = urlparse(self.path).path
        try:
            if path == "/api/ls":
                self._json(list_files(body.get("root", "")))
            elif path == "/api/inspect":
                self._json(inspect(body.get("root", ""), body["path"], body["format"], body.get("sheet"), int(body.get("header_row") or 1), body.get("encoding") or "utf-8-sig"))
            elif path == "/api/render":
                self._json({"files": render_pack(body.get("state", {}))})
            elif path == "/api/validate":
                self._json(validate_state(body.get("state", {})))
            elif path == "/api/save":
                self._json(write_pack(body.get("state", {}), bool(body.get("overwrite"))))
            elif path == "/api/load":
                self._json(load_pack(body.get("slug", "")))
            elif path == "/api/build":
                self._json(run_build(body.get("slug", ""), bool(body.get("write"))))
            elif path == "/api/status":
                self._json(source_status(body.get("slug", "")))
            elif path == "/api/builds":
                self._json(list_builds(body.get("slug", "")))
            elif path == "/api/diff":
                self._json(diff_builds(body.get("slug", ""), body.get("a", ""), body.get("b", "")))
            elif path == "/api/decision_sheet":
                self._json(decision_sheet(body.get("slug", ""), [f for f in (body.get("fields") or "").split(",") if f.strip()]))
            elif path == "/api/decision_import":
                self._json(decision_import(body.get("slug", ""), body.get("path", ""), bool(body.get("apply")), body.get("who", ""), body.get("why", "")))
            elif path == "/api/catalog":
                self._json(catalog_view(body.get("slug", "")))
            elif path == "/api/export_csv":
                self._json(csv_export(body.get("slug", ""), [f for f in (body.get("fields") or "").split(",") if f.strip()], body.get("out")))
            elif path == "/api/import_csv":
                self._json(csv_import(body.get("slug", ""), body.get("path", ""), bool(body.get("apply")), body.get("who", ""), body.get("why", "")))
            elif path == "/api/suggest":
                self._json({"name": suggest_name(body.get("header", ""))})
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def serve(port: int = 8766, open_browser: bool = True) -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"PIM window: {url}   (close this console window to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
