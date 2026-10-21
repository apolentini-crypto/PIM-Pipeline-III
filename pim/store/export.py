"""Canonical export — the diff surface (ADR-2, FR-39/41/42).

rows.jsonl: one SKU per line, ascending; keys sorted at every level; all values text;
no timestamps (those live in manifest.json only); LF; UTF-8 without BOM.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def row_line(sku: str, fields: dict, held: str | None) -> str:
    obj = {
        "sku": sku,
        "fields": {f: {"v": v, **({"u": u} if u else {}), "p": f"{pk}:{pr}"} for f, (v, u, pk, pr) in sorted(fields.items())},
        "held": held or False,
    }
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_export(out_dir: Path, rows: dict, held: dict[str, str], manifest: dict) -> tuple[Path, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "rows.jsonl"
    text = "".join(row_line(s, rows[s], held.get(s)) + "\n" for s in sorted(rows))
    p.write_bytes(text.encode("utf-8"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    (out_dir / "manifest.json").write_bytes((json.dumps({**manifest, "rows_sha256": digest}, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))
    return p, digest


def read_export(path: Path) -> dict[str, dict]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            out[o["sku"]] = o
    return out


def diff_exports(a: dict[str, dict], b: dict[str, dict]) -> dict:
    """FR-42: added, removed and changed rows, field by field. Compares values only (provenance may legitimately move)."""
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed = {}
    for sku in sorted(set(a) & set(b)):
        fa, fb = a[sku]["fields"], b[sku]["fields"]
        diffs = {}
        for f in sorted(set(fa) | set(fb)):
            va = fa.get(f, {}).get("v")
            vb = fb.get(f, {}).get("v")
            if va != vb:
                diffs[f] = {"before": va, "after": vb}
        if a[sku].get("held") != b[sku].get("held"):
            diffs["_held"] = {"before": a[sku].get("held"), "after": b[sku].get("held")}
        if diffs:
            changed[sku] = diffs
    n_cells = sum(len(d) for d in changed.values())
    return {"added": added, "removed": removed, "changed": changed,
            "counts": {"added": len(added), "removed": len(removed), "changed_rows": len(changed), "changed_cells": n_cells,
                       "unchanged_rows": len(set(a) & set(b)) - len(changed)}}


CATALOG_META_KEYS = ("kind", "held", "price_basis", "unpriced", "parent_mpn", "pack_qty")


def read_catalog_export(path: Path) -> dict[str, dict]:
    return read_export(path)


def diff_catalogs(a: dict[str, dict], b: dict[str, dict]) -> dict:
    """Stage 2b diff — one row per CT SKU. Compares field values AND the decision-level facts
    (held, price basis, unpriced, kind, pack qty), so a changed decision is visible even when no
    canonical value moved (FR-42 applied to the catalog)."""
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    changed = {}
    for sku in sorted(set(a) & set(b)):
        ra, rb = a[sku], b[sku]
        diffs = {}
        for k in CATALOG_META_KEYS:
            if ra.get(k) != rb.get(k):
                diffs[f"_{k}"] = {"before": ra.get(k), "after": rb.get(k)}
        fa, fb = ra["fields"], rb["fields"]
        for f in sorted(set(fa) | set(fb)):
            va = fa.get(f, {}).get("v")
            vb = fb.get(f, {}).get("v")
            if va != vb:
                diffs[f] = {"before": va, "after": vb}
        if diffs:
            changed[sku] = diffs
    n_cells = sum(len(d) for d in changed.values())
    return {"added": added, "removed": removed, "changed": changed,
            "counts": {"added": len(added), "removed": len(removed), "changed_rows": len(changed), "changed_cells": n_cells,
                       "unchanged_rows": len(set(a) & set(b)) - len(changed)}}


def write_catalog_export(out_dir: Path, rows: dict, meta: dict) -> Path:
    """catalog.jsonl — one line per CT SKU (Stage 2b output), same determinism rules as rows.jsonl."""
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "catalog.jsonl"
    lines = []
    for sku in sorted(rows):
        m = meta[sku]
        obj = {"sku": sku, "mpn": m["mpn"], "kind": m["kind"], "parent_mpn": m["parent_mpn"], "pack_qty": m["pack_qty"], "held": m["held"] or False,
               "price_basis": m["price_basis"], "unpriced": m["unpriced"],
               "margin_pct": (round(m["margin_pct"], 2) if m["margin_pct"] is not None else None),
               "fields": {f: {"v": v, **({"u": u} if u else {}), "p": f"{pk}:{pr}"} for f, (v, u, pk, pr) in sorted(rows[sku].items())}}
        lines.append(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    p.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return p
