"""Emit JSON Schemas for every brand-pack file into docs/schemas/ (ADR-4)."""
from __future__ import annotations

import json
from pathlib import Path

from .models import PACK_FILES


def write_schemas(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, (model, _req) in PACK_FILES.items():
        schema = model.model_json_schema()
        schema["$comment"] = f"Generated from pim.config.models.{model.__name__}; do not edit by hand."
        p = out_dir / (name.rsplit(".", 1)[0] + ".schema.json")
        p.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        written.append(p)
    return written
