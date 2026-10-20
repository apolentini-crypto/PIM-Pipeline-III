"""CSV bulk-edit round trip (FR-137..139, ARCH §5.6).

export-csv: one row per SKU, one column per field, every cell text, UTF-8 BOM, CRLF,
all fields quoted, plus a companion .types.json with per-cell fingerprints for identity-like
columns so spreadsheet damage can be told from an edit.
import-csv: diff against the current build → report; --apply writes overrides/, never the store.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import yaml

from pim.normalize.core import HaltError

DAMAGE_PATTERNS = {
    "float-ified integer": lambda before, after: re.fullmatch(r"\d+", before or "") is not None and after == before + ".0",
    "lost leading zeros": lambda before, after: (before or "").startswith("0") and after == (before or "").lstrip("0") and after != before,
    "date-coerced code": lambda before, after: re.fullmatch(r"\d{4}-\d{2}-\d{2}(T.*)?", after or "") is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", before or ""),
    "mojibake": lambda before, after: any(m in (after or "") for m in ("Ã", "â€", "�")) and not any(m in (before or "") for m in ("Ã", "â€", "�")),
    "scientific notation": lambda before, after: re.fullmatch(r"\d+", before or "") is not None and re.fullmatch(r"\d(\.\d+)?E\+\d+", after or "", re.I) is not None,
}


def _fp(v: str) -> str:
    return f"{len(v)}:{hashlib.sha1(v.encode('utf-8')).hexdigest()[:10]}"


def export_csv(rows: dict, fields: list[str], out: Path, *, skus: list[str] | None = None) -> Path:
    """rows: {sku: {field: (value, unit, pk, pr)}}"""
    sel = sorted(skus) if skus else sorted(rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        w.writerow(["sku", *fields])
        for sku in sel:
            w.writerow([sku, *[rows.get(sku, {}).get(f, ("",))[0] for f in fields]])
    types = {"fields": fields, "fingerprints": {sku: {f: _fp(rows.get(sku, {}).get(f, ("",))[0]) for f in fields} for sku in sel}}
    out.with_suffix(".types.json").write_text(json.dumps(types, indent=1, sort_keys=True), encoding="utf-8")
    return out


def import_csv(path: Path, rows: dict, declared_fields: set[str]) -> dict:
    """Compute the change set. Never writes. Returns {changes:[...], damage:[...], unknown_skus:[...], unknown_columns:[...], counts}."""
    types_path = path.with_suffix(".types.json")
    types = json.loads(types_path.read_text(encoding="utf-8")) if types_path.exists() else None
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        header = rd.fieldnames or []
        recs = list(rd)
    if not header or header[0] != "sku":
        raise HaltError("import-csv: first column must be 'sku'")
    unknown_cols = [c for c in header[1:] if c not in declared_fields]
    changes, damage, unknown_skus = [], [], []
    for r in recs:
        sku = r.get("sku", "")
        if sku not in rows:
            unknown_skus.append(sku)
            continue
        for col in header[1:]:
            if col in unknown_cols:
                continue
            after = r.get(col, "") or ""
            before = rows[sku].get(col, ("",))[0]
            if after == before:
                continue
            kinds = [k for k, test in DAMAGE_PATTERNS.items() if test(before, after)]
            if types and types["fingerprints"].get(sku, {}).get(col) and types["fingerprints"][sku][col] != _fp(before):
                kinds.append("exported value differs from current build (stale export)")
            entry = {"sku": sku, "field": col, "before": before, "after": after}
            if kinds:
                damage.append({**entry, "suspected": kinds})
            else:
                changes.append(entry)
    by_field: dict[str, int] = {}
    for c in changes:
        by_field[c["field"]] = by_field.get(c["field"], 0) + 1
    return {"changes": changes, "damage": damage, "unknown_skus": unknown_skus, "unknown_columns": unknown_cols,
            "counts": {"rows_in_file": len(recs), "changes": len(changes), "damage": len(damage), "by_field": by_field,
                       "unknown_skus": len(unknown_skus), "unknown_columns": len(unknown_cols)}}


def write_overrides(pack_dir: Path, changes: list[dict], basis_who: str, basis_why: str, allow: set[tuple[str, str]] = frozenset()) -> Path:
    """Land accepted changes as a reversible override file (FR-138). Returns its path."""
    d = pack_dir / "overrides"
    d.mkdir(exist_ok=True)
    when = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    name = d / f"csv-import-{when.replace(':', '').replace('-', '')[:15]}.yaml"
    doc = {"overrides": [{"sku": c["sku"], "field": c["field"], "before": c["before"] or None, "after": c["after"] or None,
                          "basis": {"who": basis_who, "when": when, "why": basis_why}} for c in changes]}
    name.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return name
