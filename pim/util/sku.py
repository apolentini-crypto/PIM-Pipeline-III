"""The ONE SKU parser/builder (CT-PIM-SRS-001-A1 FR-150, FR-150a; operator ruling D-8).

Grammar text lives in ``store/store.yaml`` (``sku_grammar``), not here (D-6).
Every consumer — validation, derivative construction, endpoint matching, master/child
resolution — calls these functions. No fuzzy matching, ever (INV-9).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

EndingKind = Literal["master", "unit", "pack"]


class SkuError(ValueError):
    """A SKU that does not conform to the declared grammar. The message names the rule."""


@dataclass(frozen=True)
class SkuGrammar:
    part_separator: str
    condition_separator: str
    brand_pattern: str
    mpn_pattern: str
    condition_codes: tuple[str, ...]
    endings: dict  # {"master": "M", "unit": "[1-9][0-9]*", "pack": "P[1-9][0-9]*"}

    @classmethod
    def from_store(cls, store: dict) -> "SkuGrammar":
        g = store["sku_grammar"]
        return cls(
            part_separator=g["part_separator"],
            condition_separator=g["condition_separator"],
            brand_pattern=g["brand_pattern"],
            mpn_pattern=g["mpn_pattern"],
            condition_codes=tuple(g["condition_codes"]),
            endings=dict(g["endings"]),
        )

    # --- compiled pieces -------------------------------------------------
    def _re(self, pat: str) -> re.Pattern:
        return re.compile(f"^(?:{pat})$")

    def ending_kind(self, text: str) -> Optional[EndingKind]:
        for kind, pat in self.endings.items():
            if self._re(pat).match(text):
                return kind  # type: ignore[return-value]
        return None


@dataclass(frozen=True)
class Sku:
    brand: str
    mpn: str
    condition: Optional[str] = None
    ending_kind: Optional[EndingKind] = None
    ending: Optional[str] = None  # the literal ending text: "M", "3", "P10"

    @property
    def base(self) -> str:
        """brand.mpn — the operator's 'base'."""
        return f"{self.brand}.{self.mpn}"

    @property
    def pack_qty(self) -> Optional[int]:
        return int(self.ending[1:]) if self.ending_kind == "pack" else None

    @property
    def unit_seq(self) -> Optional[int]:
        return int(self.ending) if self.ending_kind == "unit" else None


def parse_sku(text: str, g: SkuGrammar) -> Sku:
    """Parse a SKU or raise SkuError naming the broken rule. Never guesses."""
    if not isinstance(text, str) or not text:
        raise SkuError("SKU is empty")
    if text != text.strip():
        raise SkuError(f"SKU {text!r} has leading/trailing whitespace")

    parts = text.split(g.part_separator)
    if len(parts) < 2:
        if re.match(f"^{g.brand_pattern}{re.escape(g.condition_separator)}", text):
            raise SkuError(f"SKU {text!r}: a dash directly after the brand number is forbidden (D-8) — use '{g.part_separator}'")
        raise SkuError(f"SKU {text!r}: expected '{{brand}}{g.part_separator}{{mpn}}' — no part separator found")
    if len(parts) > 3:
        raise SkuError(f"SKU {text!r}: too many parts ({len(parts)}); grammar allows brand.mpn[-cond][.ending]")

    brand, body = parts[0], parts[1]
    if not g._re(g.brand_pattern).match(brand):
        raise SkuError(f"SKU {text!r}: brand {brand!r} must match /{g.brand_pattern}/")
    if body.startswith(g.condition_separator):
        raise SkuError(f"SKU {text!r}: a dash directly after the brand number is forbidden (D-8)")

    ending_kind = ending = None
    if len(parts) == 3:
        ending = parts[2]
        ending_kind = g.ending_kind(ending)
        if ending_kind is None:
            raise SkuError(f"SKU {text!r}: ending {ending!r} is none of master/unit/pack ({g.endings})")

    # condition: last dash-segment of the body IF it is a declared condition code
    mpn, condition = body, None
    if g.condition_separator in body:
        head, _, tail = body.rpartition(g.condition_separator)
        if tail in g.condition_codes:
            mpn, condition = head, tail
    if not g._re(g.mpn_pattern).match(mpn):
        raise SkuError(f"SKU {text!r}: mpn {mpn!r} must match /{g.mpn_pattern}/ (dots are separators, never part of an MPN)")

    return Sku(brand=brand, mpn=mpn, condition=condition, ending_kind=ending_kind, ending=ending)


def build_sku(
    brand_id: int | str,
    mpn: str,
    g: SkuGrammar,
    *,
    condition: Optional[str] = None,
    pack_qty: Optional[int] = None,
    unit_seq: Optional[int] = None,
    master: bool = False,
) -> str:
    """Build a SKU from parts and prove it round-trips through parse_sku."""
    if sum(bool(x) for x in (pack_qty, unit_seq, master)) > 1:
        raise SkuError("a SKU has at most one ending: master, unit or pack")
    if condition is not None and condition not in g.condition_codes:
        raise SkuError(f"condition {condition!r} not in declared codes {g.condition_codes}")
    text = f"{brand_id}{g.part_separator}{mpn}"
    if condition:
        text += f"{g.condition_separator}{condition}"
    if master:
        text += f"{g.part_separator}{g.endings['master']}"
    elif unit_seq is not None:
        text += f"{g.part_separator}{unit_seq}"
    elif pack_qty is not None:
        if pack_qty < 1:
            raise SkuError("pack_qty must be a positive integer")
        text += f"{g.part_separator}P{pack_qty}"
    parse_sku(text, g)  # fail loud rather than emit an unparseable SKU
    return text


def normalise_mpn(raw: str, rule: dict) -> str:
    """Apply a brand pack's declared MPN normalisation (brand.yaml: mpn_normalisation).

    rule keys: upper (bool) · strip_whitespace (bool) · replace ({from: to}) ·
    allowed ("regex char class") · trim ("chars to strip from both ends").
    Not reversible — keep the raw MPN in its own field.
    """
    s = raw
    if rule.get("upper", True):
        s = s.upper()
    if rule.get("strip_whitespace", True):
        s = re.sub(r"\s+", "", s)
    for a, b in (rule.get("replace") or {}).items():
        s = s.replace(a, b)
    allowed = rule.get("allowed")
    if allowed:
        s = "".join(ch for ch in s if re.match(f"[{allowed}]", ch))
    trim = rule.get("trim")
    if trim:
        s = s.strip(trim)
    if not s:
        raise SkuError(f"MPN {raw!r} normalises to empty")
    return s
