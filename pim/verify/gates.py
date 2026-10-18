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
