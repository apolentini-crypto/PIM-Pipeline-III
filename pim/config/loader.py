"""Load and validate a brand pack — every error at once (FR-4), before any file read (G-PACK).

Cross-file checks live here too (a source id referenced by fields.yaml must exist, every
managed field needs an owner, …). Validation returns a report; it never raises on content
errors, so the CLI can print all of them and exit 1.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .models import PACK_DIRS, PACK_FILES, PACK_OPTIONAL_CSV


@dataclass
class PackError:
    file: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.file}:{self.where}: {self.message}"


@dataclass
class PackReport:
    pack_dir: Path
    errors: list[PackError] = field(default_factory=list)
    warnings: list[PackError] = field(default_factory=list)
    models: dict[str, Any] = field(default_factory=dict)  # file name → validated model
    files_checked: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def measurement(self) -> dict:
        """FR-101: numbers, not verdicts."""
        return {
            "files_declared": len(PACK_FILES),
            "files_present": self.files_checked,
            "files_valid": len(self.models),
            "errors": len(self.errors),
            "warnings": len(self.warnings),
        }


def _read_doc(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def _pydantic_errors(file: str, exc: ValidationError) -> list[PackError]:
    out = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e["loc"]) or "<root>"
        out.append(PackError(file, loc, e["msg"]))
    return out


def load_store(store_path: Path) -> dict:
    return _read_doc(store_path)


def validate_pack(pack_dir: Path) -> PackReport:
    rep = PackReport(pack_dir=pack_dir)
    if not pack_dir.is_dir():
        rep.errors.append(PackError(str(pack_dir), "<dir>", "brand pack directory does not exist"))
        return rep

    # 1. per-file schema validation — collect everything, stop for nothing
    for name, (model, required) in PACK_FILES.items():
        p = pack_dir / name
        if not p.exists():
            if required:
                rep.errors.append(PackError(name, "<file>", "required pack file is missing"))
            continue
        rep.files_checked += 1
        try:
            doc = _read_doc(p)
        except Exception as exc:  # yaml/json syntax
            rep.errors.append(PackError(name, "<parse>", f"cannot parse: {exc}"))
            continue
        if doc is None:
            rep.errors.append(PackError(name, "<root>", "file is empty"))
            continue
        try:
            rep.models[name] = model.model_validate(doc)
        except ValidationError as exc:
            rep.errors.extend(_pydantic_errors(name, exc))

    for d in PACK_DIRS:
        if not (pack_dir / d).is_dir():
            rep.warnings.append(PackError(d + "/", "<dir>", "optional directory absent; created on first use"))
    for c in PACK_OPTIONAL_CSV:
        if not (pack_dir / c).exists():
            rep.warnings.append(PackError(c, "<file>", "optional file absent"))

    # unknown files are reported: a misnamed pack file silently does nothing otherwise
    known = set(PACK_FILES) | set(PACK_OPTIONAL_CSV) | set(PACK_DIRS) | {"README.md"}
    for p in sorted(pack_dir.iterdir()):
        if p.name not in known and not p.name.startswith("."):
            rep.warnings.append(PackError(p.name, "<file>", "not a recognised pack file; it is ignored"))

    # 2. cross-file checks — only where both sides validated
    m = rep.models
    if "sources.yaml" in m and "fields.yaml" in m:
        ids = {s.id for s in m["sources.yaml"].sources}
        for fname, decl in m["fields.yaml"].fields.items():
            refs = [decl.primary, *decl.aliases]
            for r in refs:
                if r.source not in ids:
                    rep.errors.append(PackError("fields.yaml", f"fields.{fname}", f"references unknown source id {r.source!r} (declared: {sorted(ids)})"))
    if "sources.yaml" in m and "joins.yaml" in m:
        ids = {s.id for s in m["sources.yaml"].sources}
        j = m["joins.yaml"]
        if j.primary_source not in ids:
            rep.errors.append(PackError("joins.yaml", "primary_source", f"unknown source id {j.primary_source!r}"))
        for i, a in enumerate(j.associations):
            for side in ("from_source", "to_source"):
                if getattr(a, side) not in ids:
                    rep.errors.append(PackError("joins.yaml", f"associations[{i}].{side}", f"unknown source id {getattr(a, side)!r}"))
    if "brand.yaml" in m and "endpoints.yaml" in m:
        envs = set(m["brand.yaml"].environments)
        for ename, ep in m["endpoints.yaml"].endpoints.items():
            for e in ep.environments:
                if e not in envs:
                    rep.errors.append(PackError("endpoints.yaml", f"endpoints.{ename}.environments", f"environment {e!r} not declared in brand.yaml (declared: {sorted(envs)})"))
    if "managed.yaml" in m and "endpoints.yaml" in m:
        # FR-55: every managed field has an owner. Owners are declared per field or per group.
        mg = m["managed.yaml"]
        mapped = set()
        for ep in m["endpoints.yaml"].endpoints.values():
            mapped |= set(ep.field_map) | set(ep.custom_fields)
        managed = mapped if mg.managed == "all-mapped" else set(mg.managed)
        managed -= set(mg.unmanaged)
        owned = set(mg.owners)
        ownerless = sorted(f for f in managed if f not in owned and "*" not in owned)
        if ownerless:
            rep.errors.append(PackError("managed.yaml", "owners", f"managed fields with no owner (FR-55): {ownerless}"))
    if "derive.yaml" in m and "vocabulary.json" in m:
        facets = set(m["derive.yaml"].facets)
        vocab = set(m["vocabulary.json"].facets)
        for pk, pr in m["derive.yaml"].packed.items():
            for k in pr.keys:
                if k in pr.vocabulary_exempt:
                    continue
                if k not in facets:
                    rep.errors.append(PackError("derive.yaml", f"packed.{pk}.keys", f"packed key {k!r} is not a declared facet"))
                elif k not in vocab:
                    rep.errors.append(PackError("vocabulary.json", "facets", f"facet {k!r} is packed but has no frozen vocabulary (FR-30)"))
    if "brand.yaml" in m and m["brand.yaml"].brand_id is None:
        rep.warnings.append(PackError("brand.yaml", "brand_id", "no BigCommerce brand id yet — catalog SKUs cannot be built until it is set"))

    return rep
