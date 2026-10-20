"""Stage 2 — normalise and merge (FR-14..26, D-7).

Identity comes from declared keys and the association table only (FR-15..17, INV-9).
Alias chains fire only when the primary is empty (FR-18); every value records the
source cell that supplied it (FR-19/47); a populated primary that disagrees with a
populated alias beyond tolerance HALTS for an operator ruling (D-7).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from pim.config.models import ColumnRef, FieldDecl, Fields, Joins, UnitSpec
from pim.ingest.readers import RawFrame


class HaltError(Exception):
    """A build halt: the message names SKU, field, observed values and the rule (FR-102)."""


@dataclass(frozen=True)
class Provenance:
    kind: str            # source_cell | alias_cell | override | derived | operator_supplied | inherited | association
    ref: str             # "S1/Hoja1!r42:EAN CODE" | override id | rule name

    def __str__(self) -> str:
        return f"{self.kind}:{self.ref}"


@dataclass
class FieldValue:
    value: str
    prov: Provenance
    unit: Optional[str] = None       # parsed unit token when the field declares one


@dataclass
class CanonicalRow:
    key: str                              # vendor MPN (roster key)
    fields: dict[str, FieldValue] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)   # non-halting observations for the report


# ----------------------------------------------------------------- keys and joins
def key_fn(raw: str, rule: str) -> str:
    """Declared key function (FR-15). trim-only never alters a key's interior."""
    s = raw.strip()
    if rule == "upper-trim":
        s = s.upper()
    return s


class SourceIndex:
    """Index a frame by its (trimmed) key. Duplicate keys inside one source halt (FR-14)."""

    def __init__(self, frame: RawFrame, rule: str):
        self.frame = frame
        self.rule = rule
        self.by_key: dict[str, list[dict[str, str]]] = {}
        for r in frame.rows:
            k = key_fn(r.get(frame.key_name, ""), rule)
            if not k:
                continue
            self.by_key.setdefault(k, []).append(r)
        if not frame.multi:
            dups = {k: len(v) for k, v in self.by_key.items() if len(v) > 1}
            if dups:
                sample = ", ".join(f"{k}×{n}" for k, n in list(dups.items())[:5])
                raise HaltError(f"{frame.source_id}/{frame.block_id}: {len(dups)} duplicate key(s) in column {frame.key_name!r}: {sample} — one row per key, or declare the source `multi: true`")

    def get(self, key: str) -> list[dict[str, str]]:
        return self.by_key.get(key, [])


class Merger:
    def __init__(self, joins: Joins, frames: dict[str, list[RawFrame]]):
        self.joins = joins
        self.rule = joins.key.rule
        # index every frame: (source_id, block_id) -> SourceIndex
        self.idx: dict[tuple[str, str], SourceIndex] = {}
        for sid, fl in frames.items():
            for f in fl:
                self.idx[(sid, f.block_id)] = SourceIndex(f, self.rule)
        # associations: (source, roster_key) -> that source's key  (FR-16; always wins)
        self.assoc: dict[tuple[str, str], str] = {}
        for a in joins.associations:
            self.assoc[(a.from_source, key_fn(a.to_key, self.rule))] = key_fn(a.from_key, self.rule)

    def roster(self) -> list[str]:
        ps = self.joins.primary_source
        prim = [k for (sid, _b), ix in self.idx.items() if sid == ps for k in ix.by_key]
        if not prim:
            raise HaltError(f"primary source {ps!r} produced an empty roster")
        return sorted(set(prim))

    def lookup(self, ref: ColumnRef, roster_key: str) -> tuple[Optional[dict[str, str]], str]:
        """Return (row, how) where how ∈ {direct, association, none}. Never fuzzy (INV-9/10)."""
        block = ref.block or ref.source
        ix = self.idx.get((ref.source, block))
        if ix is None:
            return None, "none"
        rows = ix.get(roster_key)
        how = "direct"
        if not rows and (ref.source, roster_key) in self.assoc:
            rows = ix.get(self.assoc[(ref.source, roster_key)])
            how = "association"
        if not rows:
            return None, "none"
        if ref.where:
            rows = [r for r in rows if all(r.get(c, "") == v for c, v in ref.where.items())]
            if not rows:
                return None, "none"
        if len(rows) > 1 and not ix.frame.multi:
            raise HaltError(f"{ref.source}: {len(rows)} rows for key {roster_key!r}")
        return rows[0], how

    def cell(self, ref: ColumnRef, roster_key: str) -> tuple[str, Optional[Provenance]]:
        row, how = self.lookup(ref, roster_key)
        if row is None:
            return "", None
        if ref.column not in row and ref.column not in self.idx[(ref.source, ref.block or ref.source)].frame.headers:
            raise HaltError(f"{ref.source}: column {ref.column!r} is not a header of this source (FR-111: byte-exact). Headers include: {self.idx[(ref.source, ref.block or ref.source)].frame.headers[:10]}…")
        kind = "source_cell" if how == "direct" else "association"
        return row.get(ref.column, ""), Provenance(kind, f"{ref.source}/{ref.block or ref.source}!r{row.get('_row', '?')}:{ref.column}")


# ----------------------------------------------------------------- units (FR-21..23)
_UNIT_RE = re.compile(r"^\s*([-+]?\d+(?:[.,]\d+)?(?:\s*[-–]\s*[-+]?\d+(?:[.,]\d+)?)?)\s*([A-Za-zµ°″\"']+(?:/[A-Za-z]+)?)?\s*$")


def parse_unit_value(text: str, spec: UnitSpec, column_unit: Optional[str] = None) -> tuple[str, Optional[str]]:
    """'4,72 in' -> ('4.72', 'in'); '133.5' -> ('133.5', declared unit or None). Never converts."""
    t = text.strip()
    if not t:
        return "", None
    m = _UNIT_RE.match(t)
    if not m:
        return t, None  # not a bare measurement; leave verbatim (a range in prose, a code, …)
    num, unit = m.group(1), m.group(2)
    if spec.decimal_comma or ("," in num and "." not in num):
        num = num.replace(",", ".")
    num = re.sub(r"\s*[-–]\s*", "–", num)   # ranges use an en-dash between digits (FR-115)
    if unit is None:
        unit = column_unit or spec.unit
    elif spec.expect and unit not in spec.expect:
        return "", f"unexpected unit {unit!r} in {text!r} (declared {spec.expect}); value not adopted"
    return num, unit


# ----------------------------------------------------------------- encoding (FR-24)
_MOJIBAKE = ("Ã", "â€", "Â", "�")


def encoding_issues(text: str) -> list[str]:
    out = []
    if "�" in text:
        out.append("U+FFFD replacement char")
    for ch in text:
        o = ord(ch)
        if 0x80 <= o <= 0x9F:
            out.append(f"C1 control U+{o:04X}")
            break
    for m in _MOJIBAKE[:3]:
        if m in text:
            out.append(f"mojibake marker {m!r}")
            break
    if "º" in text and re.search(r"\dº", text):
        out.append("U+00BA masculine ordinal used as degree sign")
    return out


# ----------------------------------------------------------------- field resolution (FR-18..20, D-7)
def _numeric(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _within_tolerance(a: str, b: str, tol: Optional[str]) -> bool:
    if a == b:
        return True
    na, nb = _numeric(a), _numeric(b)
    if na is None or nb is None:
        # text: Unicode-normalised, case-folded, whitespace runs collapsed — a double space is formatting, not a different fact
        norm = lambda s: re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip().casefold()
        return norm(a) == norm(b)
    if tol is None:
        return na == nb
    if tol.endswith("%"):
        return abs(na - nb) <= abs(na) * float(tol[:-1]) / 100
    return abs(na - nb) <= float(tol)


def resolve_field(name: str, decl: FieldDecl, merger: Merger, key: str) -> tuple[Optional[FieldValue], list[str]]:
    """Primary ELSE aliases, with provenance. Returns (value or None, notes). Halts on D-7 conflict."""
    notes: list[str] = []
    pv, pp = merger.cell(decl.primary, key)
    unit = None
    if decl.unit:
        pv, unit = parse_unit_value(pv, decl.unit, decl.primary.unit)
        if not pv and unit and unit.startswith("unexpected unit"):
            notes.append(f"{key}.{name}: primary {pp.ref}: {unit}"); unit = None
        if pv and unit is None and decl.unit.parse == "in-value":
            # NFR-3 fail-closed: a bare number in a unit-bearing column is not a measurement
            notes.append(f"{key}.{name}: primary {pp.ref} = {pv!r} carries no unit; not adopted (FR-21)")
            pv = ""
    chosen: Optional[FieldValue] = FieldValue(pv, pp, unit) if pv else None
    for ref in decl.aliases:
        av, ap = merger.cell(ref, key)
        aunit = None
        if decl.unit:
            av, aunit = parse_unit_value(av, decl.unit, ref.unit)
            if not av and aunit and aunit.startswith("unexpected unit"):
                notes.append(f"{key}.{name}: alias {ap.ref}: {aunit}"); aunit = None
            if av and aunit is None and decl.unit.parse == "in-value":
                notes.append(f"{key}.{name}: alias {ap.ref} = {av!r} carries no unit; not adopted (FR-21)")
                av = ""
        if not av:
            continue
        if chosen is None:
            chosen = FieldValue(av, Provenance("alias_cell", ap.ref), aunit)
            notes.append(f"{key}.{name}: alias {ap.ref} supplied the value (primary empty)")
            continue
        # both populated: compare (FR-20 as ruled by D-7)
        same_unit = (chosen.unit is None or aunit is None or chosen.unit == aunit)
        if same_unit and _within_tolerance(chosen.value, av, decl.alias_tolerance):
            continue
        if not same_unit:
            continue  # different units are not comparable without converting; converting invents a measurement (FR-132)
        raise HaltError(
            f"D-7 CONFLICT {key}.{name}: primary {chosen.prov.ref} = {chosen.value!r} vs alias {ap.ref} = {av!r} "
            f"(tolerance {decl.alias_tolerance or 'exact'}). Rule it with an override; neither value ships un-ruled."
        )
    return chosen, notes
