"""Stage 2b — DECIDE (CT-PIM-SRS-001-A1 §3): canonical rows (one per vendor MPN) → catalog rows
(one per CT SKU the store may sell).

Inputs, all data in the brand pack:
  decisions/decisions.csv   mpn, carry_state, hold_reason, fulfillment, initial_qty, price, who, when, why
  derivatives.csv           kind(pack|kit), parent_mpn, pack_qty, mpn, components, name, who, when, why
  pricing.yaml              field bindings, purchase unit, rules, margin floor, unpriced meaning
  brand.yaml                brand_id (SKU prefix), mpn normalisation
  store/store.yaml          the SKU grammar (D-8)

Carry states (FR-140): undecided · carry · skip · derivatives-only · carry+derivatives.
Price resolution (FR-155): decision price → most specific rule → msrp-passthrough → UNPRICED.
Pack arithmetic (FR-146, ruling 2026-10-20): purchase_unit=each ⇒ a pack of N costs N × cost-per-each.
Dimensions are never computed (FR-147). Everything carries provenance.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Optional

from pim.config.models import Brand, Pricing, PricingRule
from pim.normalize.core import CanonicalRow, FieldValue, HaltError, Provenance
from pim.util.sku import SkuError, SkuGrammar, build_sku, normalise_mpn

CARRY_STATES = ("undecided", "carry", "skip", "derivatives-only", "carry+derivatives")
DECISION_COLUMNS = ["mpn", "carry_state", "hold_reason", "fulfillment", "initial_qty", "price", "who", "when", "why"]
DERIVATIVE_COLUMNS = ["kind", "parent_mpn", "pack_qty", "mpn", "components", "name", "who", "when", "why"]


@dataclass
class Decision:
    mpn: str
    carry_state: str = "undecided"
    hold_reason: str = ""
    fulfillment: str = ""
    initial_qty: str = ""
    price: str = ""
    who: str = ""
    when: str = ""
    why: str = ""


@dataclass
class Derivative:
    kind: str                 # pack | kit
    parent_mpn: str = ""      # pack
    pack_qty: int = 0         # pack
    mpn: str = ""             # kit: operator-assigned MPN
    components: list[tuple[str, int]] = field(default_factory=list)   # kit
    name: str = ""
    who: str = ""
    when: str = ""
    why: str = ""

    @property
    def key(self) -> str:
        return f"{self.parent_mpn}.P{self.pack_qty}" if self.kind == "pack" else self.mpn


@dataclass
class CatalogRow:
    sku: str
    mpn: str                  # the vendor MPN (pack) or operator MPN (kit)
    kind: str                 # original | pack | kit
    parent_mpn: Optional[str]
    pack_qty: Optional[int]
    fields: dict[str, FieldValue] = field(default_factory=dict)
    held: Optional[str] = None
    price_basis: str = ""     # provenance of the resolved price
    unpriced: bool = False
    margin_pct: Optional[float] = None
    notes: list[str] = field(default_factory=list)


# ----------------------------------------------------------------- readers
def _read_csv(path: Path, columns: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        unknown = [c for c in (rd.fieldnames or []) if c not in columns]
        if unknown:
            raise HaltError(f"{path.name}: unknown column(s) {unknown}; allowed: {columns}")
        return [{c: (r.get(c) or "").strip() for c in columns} for r in rd]


def load_decisions(pack_dir: Path) -> dict[str, Decision]:
    out: dict[str, Decision] = {}
    for i, r in enumerate(_read_csv(pack_dir / "decisions" / "decisions.csv", DECISION_COLUMNS), start=2):
        if not r["mpn"]:
            continue
        if r["mpn"] in out:
            raise HaltError(f"decisions.csv row {i}: duplicate decision for {r['mpn']!r}")
        st = r["carry_state"] or "undecided"
        if st not in CARRY_STATES:
            raise HaltError(f"decisions.csv row {i}: carry_state {st!r} for {r['mpn']} is not one of {CARRY_STATES}")
        out[r["mpn"]] = Decision(**r, **{}) if False else Decision(r["mpn"], st, r["hold_reason"], r["fulfillment"], r["initial_qty"], r["price"], r["who"], r["when"], r["why"])
    return out


def load_derivatives(pack_dir: Path) -> list[Derivative]:
    out: list[Derivative] = []
    legacy = pack_dir / "derivatives.csv"
    rows = _read_csv(legacy, DERIVATIVE_COLUMNS) if legacy.exists() and "kind" in (legacy.read_text(encoding="utf-8-sig").splitlines() or [""])[0] else []
    for i, r in enumerate(rows, start=2):
        kind = r["kind"] or ("pack" if r["pack_qty"] else "kit")
        if kind == "pack":
            if not r["parent_mpn"] or not r["pack_qty"].isdigit() or int(r["pack_qty"]) < 1:
                raise HaltError(f"derivatives.csv row {i}: a pack needs parent_mpn and a positive pack_qty")
            out.append(Derivative("pack", r["parent_mpn"], int(r["pack_qty"]), "", [], r["name"], r["who"], r["when"], r["why"]))
        elif kind == "kit":
            if not r["mpn"] or not r["components"]:
                raise HaltError(f"derivatives.csv row {i}: a kit needs its own mpn and components like 'MSEF:1;MSF:2'")
            comps = []
            for part in r["components"].split(";"):
                part = part.strip()
                if not part:
                    continue
                m, _, q = part.partition(":")
                q = q.strip() or "1"
                if not q.isdigit() or int(q) < 1:
                    raise HaltError(f"derivatives.csv row {i}: component {part!r} needs a positive quantity")
                comps.append((m.strip(), int(q)))
            out.append(Derivative("kit", "", 0, r["mpn"], comps, r["name"], r["who"], r["when"], r["why"]))
        else:
            raise HaltError(f"derivatives.csv row {i}: kind {kind!r} must be pack or kit")
    keys = [d.key for d in out]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        raise HaltError(f"derivatives.csv: duplicate derivative(s) {dup}")
    return out


# ----------------------------------------------------------------- money
def _num(v: Optional[str]) -> Optional[Decimal]:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).replace(",", ""))
    except Exception:
        return None


def _round(x: Decimal, rounding: str) -> Decimal:
    if rounding == "none":
        return x
    if rounding == "nearest-cent":
        return x.quantize(Decimal("0.01"), ROUND_HALF_UP)
    if rounding == "whole-dollar":
        return x.quantize(Decimal("1"), ROUND_HALF_UP)
    if rounding in (".95", ".99"):
        # nearest price ending in .95/.99: 420 -> 419.95, 420.60 -> 420.95
        cents = Decimal(rounding)
        base = x.to_integral_value(ROUND_HALF_UP)
        lo, hi = base - 1 + cents, base + cents
        return hi if abs(hi - x) <= abs(x - lo) else lo
    return x


def _fmt(x: Decimal) -> str:
    s = f"{x.normalize():f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _money(x: Decimal) -> str:
    """Prices always carry two decimals ('99.00', '419.95') — the store's own format, and it
    keeps a hand-set 99 and a rule-made 99.00 from looking like a change."""
    return f"{x.quantize(Decimal('0.01'), ROUND_HALF_UP):f}"


def resolve_price(row: CatalogRow, decision: Optional[Decision], pricing: Pricing, cost: Optional[Decimal], list_price: Optional[Decimal], category: str) -> None:
    """FR-154..157. Sets row.fields['price'] with provenance, row.price_basis, row.unpriced, row.margin_pct."""
    def set_price(val: Decimal, basis: str):
        row.fields["price"] = FieldValue(_money(val), Provenance("derived", basis))
        row.price_basis = basis
        if cost is not None and val:
            row.margin_pct = float((val - cost) / val * 100)
    if decision and decision.price:
        p = _num(decision.price)
        if p is None:
            raise HaltError(f"{row.sku}: decision price {decision.price!r} is not a number")
        set_price(p, f"decision:{decision.mpn}")
        return
    # most specific rule first
    order = {"row": 0, "derivative": 1, "category": 2, "brand": 3, "default": 4}
    cands: list[PricingRule] = []
    for r in pricing.rules:
        if r.scope == "row" and r.scope_value == row.mpn and row.kind == "original":
            cands.append(r)
        elif r.scope == "derivative" and r.scope_value == (f"{row.parent_mpn}.P{row.pack_qty}" if row.kind == "pack" else row.mpn) and row.kind != "original":
            cands.append(r)
        elif r.scope == "category" and category and r.scope_value == category:
            cands.append(r)
        elif r.scope in ("brand", "default"):
            cands.append(r)
    cands.sort(key=lambda r: order[r.scope])
    for r in cands:
        if r.basis == "markup-on-cost" and cost is not None:
            set_price(_round(cost * (1 + Decimal(str(r.factor))), r.rounding), f"rule:{r.scope}:markup-on-cost×{r.factor}"); return
        if r.basis == "discount-off-msrp" and list_price is not None:
            set_price(_round(list_price * (1 - Decimal(str(r.factor))), r.rounding), f"rule:{r.scope}:discount-off-msrp×{r.factor}"); return
        if r.basis == "fixed":
            set_price(_round(Decimal(str(r.factor)), r.rounding), f"rule:{r.scope}:fixed"); return
        if r.basis == "msrp-passthrough" and list_price is not None:
            set_price(_round(list_price, r.rounding), f"rule:{r.scope}:msrp-passthrough"); return
    row.unpriced = True
    row.price_basis = f"unpriced ({pricing.unpriced_means})"


# ----------------------------------------------------------------- the stage
@dataclass
class DecideResult:
    catalog: dict[str, CatalogRow]
    decisions: dict[str, Decision]
    derivatives: list[Derivative]
    counts: dict[str, int]
    assertions: dict[str, dict]
    notes: list[str]


def _inherit(src: CanonicalRow | CatalogRow, parent_mpn: str, skip: set[str]) -> dict[str, FieldValue]:
    out = {}
    for f, fv in src.fields.items():
        if f in skip:
            continue
        out[f] = FieldValue(fv.value, Provenance("inherited", f"{parent_mpn}.{f}"), fv.unit)
    return out


def decide(rows: dict[str, CanonicalRow], pack_dir: Path, brand: Brand, pricing: Pricing, grammar: SkuGrammar,
           held: dict[str, str]) -> DecideResult:
    decisions = load_decisions(pack_dir)
    derivatives = load_derivatives(pack_dir)
    notes: list[str] = []
    pf = pricing.fields
    counts = {s: 0 for s in CARRY_STATES}
    for mpn in rows:
        counts[decisions[mpn].carry_state if mpn in decisions else "undecided"] += 1
    stale = [d.mpn for d in decisions.values() if d.mpn not in rows]
    for m in stale:
        notes.append(f"decision for {m!r} refers to an MPN no longer in the roster — kept, not applied (FR-142)")

    needs_sku = any(d.carry_state not in ("undecided", "skip") for d in decisions.values()) or bool(derivatives)
    if brand.brand_id is None and needs_sku:
        raise HaltError("brand.yaml: brand_id is not set — CT SKUs cannot be built (FR-150). Create the brand in BigCommerce and record its id.")
    if brand.brand_id is None:
        return DecideResult({}, decisions, derivatives, counts, {"G-DECIDED": {"measured": counts["undecided"], "expected": "0 before publish", "ok": True}}, notes)

    catalog: dict[str, CatalogRow] = {}
    unpriced: list[str] = []
    below_floor: list[str] = []
    deriv_errors: list[str] = []

    def add(row: CatalogRow, decision: Optional[Decision], category: str):
        if row.sku in catalog:
            raise HaltError(f"G-SKU-UNIQUE: SKU {row.sku} produced twice ({catalog[row.sku].mpn} and {row.mpn})")
        cost = _num(row.fields[pf.cost].value) if pf.cost and pf.cost in row.fields else None
        lp = _num(row.fields[pf.list_price].value) if pf.list_price and pf.list_price in row.fields else None
        resolve_price(row, decision, pricing, cost, lp, category)
        if row.unpriced:
            unpriced.append(row.sku)
            if pricing.unpriced_means == "hold" and not row.held:
                row.held = "unpriced"
        if row.margin_pct is not None and pricing.margin_floor_pct is not None and row.margin_pct < pricing.margin_floor_pct:
            below_floor.append(f"{row.sku} margin {row.margin_pct:.1f}% < floor {pricing.margin_floor_pct}%")
        if decision:
            if decision.fulfillment:
                if decision.fulfillment not in pricing.fulfillment_vocabulary:
                    raise HaltError(f"{row.sku}: fulfillment {decision.fulfillment!r} not in declared vocabulary {pricing.fulfillment_vocabulary}")
                row.fields["fulfillment"] = FieldValue(decision.fulfillment, Provenance("decision", decision.mpn))
            if decision.initial_qty:
                row.fields["initial_qty"] = FieldValue(decision.initial_qty, Provenance("decision", decision.mpn))
        row.fields["ct_sku"] = FieldValue(row.sku, Provenance("derived", "sku-rule"))
        row.fields["carry_kind"] = FieldValue(row.kind, Provenance("derived", "decide"))
        catalog[row.sku] = row

    # originals
    for mpn, crow in rows.items():
        d = decisions.get(mpn)
        state = d.carry_state if d else "undecided"
        if state not in ("carry", "carry+derivatives"):
            continue
        try:
            sku = build_sku(brand.brand_id, normalise_mpn(mpn, brand.mpn_normalisation.model_dump()), grammar)
        except SkuError as e:
            raise HaltError(f"G-SKU-GRAMMAR: {mpn}: {e}")
        row = CatalogRow(sku, mpn, "original", None, None, dict(crow.fields), held.get(mpn) or (d.hold_reason or None if d else None))
        add(row, d, crow.fields[pf.category].value if pf.category and pf.category in crow.fields else "")

    # derivatives
    for dv in derivatives:
        if dv.kind == "pack":
            parent = rows.get(dv.parent_mpn)
            pd = decisions.get(dv.parent_mpn)
            pstate = pd.carry_state if pd else "undecided"
            if parent is None:
                deriv_errors.append(f"pack {dv.key}: parent {dv.parent_mpn!r} is not in the roster"); continue
            if pstate not in ("derivatives-only", "carry+derivatives"):
                deriv_errors.append(f"pack {dv.key}: parent {dv.parent_mpn} is '{pstate}', needs derivatives-only or carry+derivatives (FR-148)"); continue
            sku = build_sku(brand.brand_id, normalise_mpn(dv.parent_mpn, brand.mpn_normalisation.model_dump()), grammar, pack_qty=dv.pack_qty)
            skip = {pf.cost, pf.list_price, pf.weight, "unit_length_mm", "unit_width_mm", "unit_height_mm"} - {None}
            row = CatalogRow(sku, dv.parent_mpn, "pack", dv.parent_mpn, dv.pack_qty, _inherit(parent, dv.parent_mpn, skip), held.get(dv.parent_mpn) or (pd.hold_reason or None if pd else None))
            n = Decimal(dv.pack_qty)
            for fname, label in ((pf.cost, "cost"), (pf.list_price, "list"), (pf.weight, "weight")):
                if fname and fname in parent.fields:
                    v = _num(parent.fields[fname].value)
                    if v is not None:
                        row.fields[fname] = FieldValue(_fmt(v * n), Provenance("derived", f"pack:{dv.pack_qty}×{dv.parent_mpn}.{fname}"), parent.fields[fname].unit)
            base_name = parent.fields.get(pf.name)
            row.fields[pf.name] = FieldValue(dv.name or ((base_name.value if base_name else dv.parent_mpn) + pricing.pack_name_suffix.format(qty=dv.pack_qty)), Provenance("derived" if not dv.name else "decision", f"pack-name:{dv.key}"))
            row.fields["pack_qty"] = FieldValue(str(dv.pack_qty), Provenance("decision", dv.key))
            add(row, None, parent.fields[pf.category].value if pf.category and pf.category in parent.fields else "")
        else:  # kit
            missing = [m for m, _ in dv.components if m not in rows]
            if missing:
                deriv_errors.append(f"kit {dv.mpn}: component(s) {missing} not in the roster"); continue
            first = rows[dv.components[0][0]]
            try:
                sku = build_sku(brand.brand_id, normalise_mpn(dv.mpn, brand.mpn_normalisation.model_dump()), grammar)
            except SkuError as e:
                deriv_errors.append(f"kit {dv.mpn}: {e}"); continue
            skip = {pf.cost, pf.list_price, pf.weight, "mpn", "ean", "ean_box", "unit_length_mm", "unit_width_mm", "unit_height_mm"} - {None}
            row = CatalogRow(sku, dv.mpn, "kit", None, None, _inherit(first, first.key, skip))
            for fname in (pf.cost, pf.list_price, pf.weight):
                if not fname:
                    continue
                total = Decimal(0); ok = True; unit = None
                for m, q in dv.components:
                    v = _num(rows[m].fields[fname].value) if fname in rows[m].fields else None
                    if v is None:
                        ok = False; break
                    total += v * q; unit = rows[m].fields[fname].unit
                if ok:
                    row.fields[fname] = FieldValue(_fmt(total), Provenance("derived", f"kit:sum({';'.join(f'{m}×{q}' for m, q in dv.components)}).{fname}"), unit)
                else:
                    notes.append(f"kit {dv.mpn}: {fname} omitted — a component has no value (FR-35)")
            row.fields[pf.name] = FieldValue(dv.name or f"{dv.mpn} kit", Provenance("decision" if dv.name else "derived", f"kit-name:{dv.mpn}"))
            row.fields["mpn"] = FieldValue(dv.mpn, Provenance("decision", f"kit:{dv.mpn}"))
            row.fields["kit_components"] = FieldValue(";".join(f"{m}:{q}" for m, q in dv.components), Provenance("decision", f"kit:{dv.mpn}"))
            add(row, None, first.fields[pf.category].value if pf.category and pf.category in first.fields else "")

    # plausibility (INV-14): per-each weight far from its category's median
    if pf.weight:
        import statistics
        by_cat: dict[str, list[tuple[str, float]]] = {}
        for mpn, crow in rows.items():
            w = _num(crow.fields[pf.weight].value) if pf.weight in crow.fields else None
            gf = pf.group or pf.category
            cat = crow.fields[gf].value if gf and gf in crow.fields else ""
            if w is not None and w > 0:
                by_cat.setdefault(cat, []).append((mpn, float(w)))
        for cat, items in by_cat.items():
            if len(items) < 4:
                continue
            med = statistics.median(w for _, w in items)
            for mpn, w in items:
                if med > 0 and (w / med >= 20 or med / w >= 20):
                    notes.append(f"PLAUSIBILITY {mpn}.{pf.weight} = {w:g} vs category '{cat}' median {med:g} (×{max(w/med, med/w):.0f}) — check the vendor cell (INV-14)")

    assertions = {
        "G-DECIDED": {"measured": counts["undecided"], "expected": "0 before publish", "ok": True, "details": [f"{counts['undecided']} undecided of {len(rows)}"]},
        "G-SKU-UNIQUE": {"measured": len(catalog), "expected": len(catalog), "ok": True},
        # counts, not verdicts: a string `expected` marks a gate that is informational at build
        # time and only becomes a hard stop at publish (A1 §3.9)
        "G-PRICE": {"measured": len(unpriced), "expected": "0 before publish", "ok": True, "details": unpriced[:50]},
        "G-DERIV": {"measured": len(deriv_errors), "expected": 0, "ok": not deriv_errors, "details": deriv_errors},
        "MARGIN-FLOOR": {"measured": len(below_floor), "expected": "report only", "ok": True, "details": below_floor[:50]},
    }
    return DecideResult(catalog, decisions, derivatives, counts, assertions, notes)


# ----------------------------------------------------------------- the decision sheet (FR-171)
def decision_sheet_rows(rows: dict[str, CanonicalRow], decisions: dict[str, Decision], derivatives: list[Derivative], pricing: Pricing, extra_fields: list[str]) -> tuple[list[str], list[list[str]]]:
    pf = pricing.fields
    header = ["mpn", "carry_state", "hold_reason", "fulfillment", "initial_qty", "price", "who", "when", "why",
              "— derivatives", "— cost", "— list", "— margin% at list", "— category", "— name", *["— " + f for f in extra_fields]]
    out = []
    for mpn in sorted(rows):
        r = rows[mpn]; d = decisions.get(mpn)
        g = lambda k: r.fields[k].value if k and k in r.fields else ""
        cost, lp = _num(g(pf.cost)), _num(g(pf.list_price))
        margin = f"{float((lp - cost) / lp * 100):.1f}" if cost is not None and lp else ""
        dv = "; ".join((f"P{x.pack_qty}" if x.kind == "pack" else f"kit {x.mpn}") for x in derivatives if (x.kind == "pack" and x.parent_mpn == mpn) or (x.kind == "kit" and any(m == mpn for m, _ in x.components)))
        out.append([mpn, d.carry_state if d else "undecided", d.hold_reason if d else "", d.fulfillment if d else "", d.initial_qty if d else "", d.price if d else "",
                    d.who if d else "", d.when if d else "", d.why if d else "", dv, g(pf.cost), g(pf.list_price), margin, g(pf.category), g(pf.name), *[g(f) for f in extra_fields]])
    return header, out


def write_decisions(pack_dir: Path, decisions: dict[str, Decision]) -> Path:
    d = pack_dir / "decisions"; d.mkdir(exist_ok=True)
    p = d / "decisions.csv"
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(DECISION_COLUMNS)
        for mpn in sorted(decisions):
            x = decisions[mpn]
            w.writerow([x.mpn, x.carry_state, x.hold_reason, x.fulfillment, x.initial_qty, x.price, x.who, x.when, x.why])
    return p


def diff_decisions(current: dict[str, Decision], sheet_rows: list[dict[str, str]], roster: set[str]) -> dict:
    """Change set of a decision sheet against current decisions. Only the decision columns count."""
    changes, unknown = [], []
    new: dict[str, Decision] = {k: Decision(**v.__dict__) for k, v in current.items()}
    for r in sheet_rows:
        mpn = (r.get("mpn") or "").strip()
        if not mpn:
            continue
        if mpn not in roster:
            unknown.append(mpn); continue
        cur = current.get(mpn, Decision(mpn))
        upd = Decision(mpn, (r.get("carry_state") or "undecided").strip(), (r.get("hold_reason") or "").strip(), (r.get("fulfillment") or "").strip(),
                       (r.get("initial_qty") or "").strip(), (r.get("price") or "").strip(), (r.get("who") or "").strip(), (r.get("when") or "").strip(), (r.get("why") or "").strip())
        if upd.carry_state not in CARRY_STATES:
            changes.append({"mpn": mpn, "field": "carry_state", "before": cur.carry_state, "after": upd.carry_state, "error": f"not one of {CARRY_STATES}"}); continue
        for f in ("carry_state", "hold_reason", "fulfillment", "initial_qty", "price"):
            if getattr(cur, f) != getattr(upd, f):
                changes.append({"mpn": mpn, "field": f, "before": getattr(cur, f), "after": getattr(upd, f)})
        if any(getattr(cur, f) != getattr(upd, f) for f in ("carry_state", "hold_reason", "fulfillment", "initial_qty", "price")):
            new[mpn] = upd
    by_field: dict[str, int] = {}
    for c in changes:
        by_field[c["field"]] = by_field.get(c["field"], 0) + 1
    return {"changes": changes, "unknown_mpns": unknown, "new_decisions": new, "errors": [c for c in changes if "error" in c],
            "counts": {"changes": len(changes), "by_field": by_field, "unknown": len(unknown), "errors": sum(1 for c in changes if "error" in c)}}
