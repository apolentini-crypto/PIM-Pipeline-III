"""Gates implemented so far. Each is a Check with a corruptor in tests/corruptors/.

M0 ships G-PACK (FR-4) and G-SKU-GRAMMAR (A1 FR-150). Later milestones add the rest of
SRS §7.4 and A1 §3.9.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pim.config.loader import validate_pack
from pim.util.sku import SkuError, SkuGrammar, parse_sku

from .check import Measurement, register_check


@dataclass
class GPack:
    id: str = "G-PACK"
    requirement: str = "FR-4"

    def measure(self, ctx) -> Measurement:
        rep = validate_pack(Path(ctx["pack_dir"]))
        m = rep.measurement()
        return Measurement(self.id, rep.ok, m, details=[str(e) for e in rep.errors])


@dataclass
class GSkuGrammar:
    """Every SKU in ctx['skus'] parses under the store grammar (D-8)."""
    id: str = "G-SKU-GRAMMAR"
    requirement: str = "A1 FR-150"

    def measure(self, ctx) -> Measurement:
        g = SkuGrammar.from_store(ctx["store"])
        bad = []
        for s in ctx["skus"]:
            try:
                parse_sku(s, g)
            except SkuError as e:
                bad.append(str(e))
        return Measurement(self.id, not bad, {"skus": len(ctx["skus"]), "nonconforming": len(bad)}, details=bad)


register_check(GPack())
register_check(GSkuGrammar())


# ----------------------------------------------------------------- M1 build gates (FR-14, FR-20/D-7, FR-24, FR-25, INV-17)
def _build_measure(check_id: str, ctx, want_halt_substring: str | None):
    """Run a build on ctx['pack_dir'] with ctx['var_dir']; the gate passes when the build does NOT halt on this gate."""
    from pathlib import Path
    from pim.build import build
    from pim.normalize.core import HaltError
    try:
        r = build(Path(ctx["pack_dir"]), Path(ctx["var_dir"]), write=False)
    except HaltError as e:
        msg = str(e)
        hit = want_halt_substring is not None and want_halt_substring in msg
        return Measurement(check_id, not hit, {"halted": 1, "on_this_gate": int(hit)}, details=[msg] if hit else [])
    a = r.assertions.get(check_id)
    if a is not None:
        return Measurement(check_id, bool(a["ok"]), {"measured": a["measured"], "expected": a["expected"]}, details=a.get("details", []))
    return Measurement(check_id, True, {"rows": len(r.rows)})


@dataclass
class GRoster:
    id: str = "G-ROSTER"; requirement: str = "FR-14, expectations"
    def measure(self, ctx): return _build_measure(self.id, ctx, "G-ROSTER")


@dataclass
class GRequired:
    id: str = "G-REQUIRED"; requirement: str = "INV-17"
    def measure(self, ctx): return _build_measure(self.id, ctx, "G-REQUIRED")


@dataclass
class GEncoding:
    id: str = "G-ENCODING"; requirement: str = "FR-24"
    def measure(self, ctx): return _build_measure(self.id, ctx, "G-ENCODING")


@dataclass
class GAliasConflict:
    id: str = "G-ALIAS-CONFLICT"; requirement: str = "FR-20 / D-7"
    def measure(self, ctx): return _build_measure(self.id, ctx, "D-7 CONFLICT")


@dataclass
class GOverrideStale:
    id: str = "G-OVERRIDE-STALE"; requirement: str = "FR-25"
    def measure(self, ctx): return _build_measure(self.id, ctx, "STALE override")


@dataclass
class GKeyUnique:
    id: str = "G-KEY-UNIQUE"; requirement: str = "FR-14"
    def measure(self, ctx): return _build_measure(self.id, ctx, "duplicate key")


for _c in (GRoster(), GRequired(), GEncoding(), GAliasConflict(), GOverrideStale(), GKeyUnique()):
    register_check(_c)
