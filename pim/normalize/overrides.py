"""Operator overrides (FR-25/26, FR-43): applied after merge, before derivation, only
while the recorded pre-value still matches; deleting one restores the source value."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from pim.config.models import Override, OverrideFile

from .core import CanonicalRow, FieldValue, HaltError, Provenance


def load_overrides(pack_dir: Path) -> list[tuple[str, Override]]:
    """Returns [(override_id, Override)] in deterministic file/line order."""
    out = []
    d = pack_dir / "overrides"
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.yaml")) + sorted(d.glob("*.yml")):
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        try:
            of = OverrideFile.model_validate(doc)
        except ValidationError as e:
            raise HaltError(f"overrides/{p.name}: {e.errors()[0]['loc']}: {e.errors()[0]['msg']}")
        for i, o in enumerate(of.overrides, start=1):
            out.append((f"{p.name}#{i}", o))
    return out


def apply_overrides(rows: dict[str, CanonicalRow], overrides: list[tuple[str, Override]], declared_fields: set[str]) -> list[str]:
    """Mutates rows. Returns the list of applied override ids. Halts on stale or dangling overrides."""
    applied = []
    for oid, o in overrides:
        if o.field not in declared_fields:
            raise HaltError(f"override {oid}: field {o.field!r} is not a declared canonical field")
        row = rows.get(o.sku)
        if row is None:
            raise HaltError(f"override {oid}: SKU {o.sku!r} is not in the roster")
        current = row.fields.get(o.field)
        cur_val = current.value if current else None
        if (cur_val or None) != (o.before or None):
            raise HaltError(
                f"STALE override {oid} on {o.sku}.{o.field}: recorded before={o.before!r} but the build produced {cur_val!r}. "
                f"The source moved since this override was written — re-rule it (FR-25)."
            )
        if o.after is None or o.after == "":
            row.fields.pop(o.field, None)
        else:
            row.fields[o.field] = FieldValue(o.after, Provenance("override", oid), current.unit if current else None)
        applied.append(oid)
    return applied
