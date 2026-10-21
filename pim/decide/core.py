"""Stage 2b — DECIDE (CT-PIM-SRS-001-A1 §3): canonical rows (one per vendor MPN) → catalog rows
(one per CT SKU the store may sell).

Inputs, all data in the brand pack:
  decisions/decisions.csv   mpn, carry_state, hold_reason, fulfillment, initial_qty, price, who, when, why
  derivatives.csv           kind(pack|kit), parent_mpn, pack_qty, mpn, components, name, who, when, why
  pricing.yaml              field bindings, purchase unit, rules, margin floor, unpriced meaning
  brand.yaml                brand_id (SKU prefix), mpn normalisation
  store/store.yaml          the SKU grammar (D-8)

Carry states (FR-140): undecided · carry · skip · derivatives-only · carry+derivatives.
Derivative decisions (FR-173a): same table, keyed `<parent>.P<qty>` (pack) or the kit MPN; carry | skip only.
Decision sheet (FR-171a/b/c): one row per CT SKU; every editable cell validated on import.
Price resolution (FR-155): decision price → most specific rule → msrp-passthrough → UNPRICED.
Pack arithmetic (FR-146, ruling 2026-10-20): purchase_unit=each ⇒ a pack of N costs N × cost-per-each.
Dimensions are never computed (FR-147). Everything carries provenance.
"""
from __future__ import annotations

import csv
import datetime as _dt
import math
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Optional

from pim.config.models import Brand, Pricing, PricingRule
from pim.normalize.core import CanonicalRow, FieldValue, HaltError, Provenance
from pim.util.sku import SkuError, SkuGrammar, build_sku, normalise_mpn

CARRY_STATES = ("undecided", "carry", "skip", "derivatives-only", "carry+derivatives")
DECISION_COLUMNS = ["mpn", "carry_state", "hold_reason", "fulfillment", "initial_qty", "price", "who", "when", "why"]
DERIVATIVE_STATES = ("carry", "skip")   # FR-173a: a derivative is either produced or suppressed
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
    dkeys = {dv.key for dv in derivatives}
    stale = [d.mpn for d in decisions.values() if d.mpn not in rows and d.mpn not in dkeys]
    for m in stale:
        notes.append(f"decision for {m!r} refers to an MPN no longer in the roster — kept, not applied (FR-142)")
    for k in sorted(dkeys):
        dd = decisions.get(k)
        if dd and dd.carry_state not in DERIVATIVE_STATES:
            raise HaltError(f"decisions.csv: {k} is a pack/kit — its carry_state must be one of {DERIVATIVE_STATES}, not {dd.carry_state!r} (FR-173a)")
    counts["derivatives_skipped"] = sum(1 for k in dkeys if k in decisions and decisions[k].carry_state == "skip")

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
        dd = decisions.get(dv.key)                      # the derivative's own decision (FR-173a)
        if dd and dd.carry_state == "skip":
            continue
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
            own_hold = (dd.hold_reason or None) if dd else None
            row = CatalogRow(sku, dv.parent_mpn, "pack", dv.parent_mpn, dv.pack_qty, _inherit(parent, dv.parent_mpn, skip), own_hold or held.get(dv.parent_mpn) or (pd.hold_reason or None if pd else None))
            n = Decimal(dv.pack_qty)
            for fname, label in ((pf.cost, "cost"), (pf.list_price, "list"), (pf.weight, "weight")):
                if fname and fname in parent.fields:
                    v = _num(parent.fields[fname].value)
                    if v is not None:
                        row.fields[fname] = FieldValue(_fmt(v * n), Provenance("derived", f"pack:{dv.pack_qty}×{dv.parent_mpn}.{fname}"), parent.fields[fname].unit)
            base_name = parent.fields.get(pf.name)
            row.fields[pf.name] = FieldValue(dv.name or ((base_name.value if base_name else dv.parent_mpn) + pricing.pack_name_suffix.format(qty=dv.pack_qty)), Provenance("derived" if not dv.name else "decision", f"pack-name:{dv.key}"))
            row.fields["pack_qty"] = FieldValue(str(dv.pack_qty), Provenance("decision", dv.key))
            add(row, dd, parent.fields[pf.category].value if pf.category and pf.category in parent.fields else "")
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
            row = CatalogRow(sku, dv.mpn, "kit", None, None, _inherit(first, first.key, skip), (dd.hold_reason or None) if dd else None)
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
            add(row, dd, first.fields[pf.category].value if pf.category and pf.category in first.fields else "")

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


# ----------------------------------------------------------------- the decision sheet (FR-171, 171a/b/c)
SHEET_HEADER = ["mpn", "— sku", "— kind", "carry_state", "hold_reason", "fulfillment", "initial_qty", "price", "new_pack_qty", "who", "when", "why",
                "— parent", "— components", "— unpriced", "— price now", "— basis", "— cost", "— list", "— margin% at list", "— category", "— name"]


def _safe_sku(brand: Optional[Brand], grammar: Optional[SkuGrammar], mpn: str, pack_qty: int = 0) -> str:
    if brand is None or grammar is None or brand.brand_id is None:
        return ""
    try:
        return build_sku(brand.brand_id, normalise_mpn(mpn, brand.mpn_normalisation.model_dump()), grammar, pack_qty=pack_qty or None)
    except SkuError:
        return ""


def _ctx_money(v) -> str:
    """Context cost/list on the sheet: a Decimal or a vendor text; shown as money when numeric, else as-is."""
    if v is None or v == "":
        return ""
    d = v if isinstance(v, Decimal) else _num(v)
    return _money(d) if d is not None else str(v)


def _margin(cost: Optional[Decimal], lp: Optional[Decimal]) -> str:
    return f"{float((lp - cost) / lp * 100):.1f}" if cost is not None and lp else ""


def decision_sheet_rows(rows: dict[str, CanonicalRow], decisions: dict[str, Decision], derivatives: list[Derivative], pricing: Pricing,
                        extra_fields: list[str], catalog: Optional[dict[str, CatalogRow]] = None, brand: Optional[Brand] = None,
                        grammar: Optional[SkuGrammar] = None) -> tuple[list[str], list[list[str]]]:
    """One row per CT SKU (FR-171a): each roster MPN (whatever its state), its packs directly under it,
    kits at the end. Columns without the '— ' prefix are editable; the rest are context, ignored on import."""
    pf = pricing.fields
    catalog = catalog or {}
    header = [*SHEET_HEADER, *["— " + f for f in extra_fields]]
    out: list[list[str]] = []

    def built(sku: str) -> tuple[str, str, str]:
        c = catalog.get(sku)
        if not c:
            return "", "", "not built"
        return ("yes" if c.unpriced else ""), (c.fields["price"].value if "price" in c.fields else ""), c.price_basis

    def dec_cols(d: Optional[Decision], default_state: str) -> list[str]:
        return [d.carry_state if d else default_state, d.hold_reason if d else "", d.fulfillment if d else "", d.initial_qty if d else "",
                d.price if d else "", "", d.who if d else "", d.when if d else "", d.why if d else ""]

    packs_by_parent: dict[str, list[Derivative]] = {}
    for dv in derivatives:
        if dv.kind == "pack":
            packs_by_parent.setdefault(dv.parent_mpn, []).append(dv)

    for mpn in sorted(rows):
        r = rows[mpn]; d = decisions.get(mpn)
        g = lambda k: r.fields[k].value if k and k in r.fields else ""
        cost, lp = _num(g(pf.cost)), _num(g(pf.list_price))
        sku = _safe_sku(brand, grammar, mpn)
        unpriced, price_now, basis = built(sku) if sku else ("", "", "")
        if not sku and brand is not None and brand.brand_id is None:
            basis = "no brand id"
        out.append([mpn, sku, "original", *dec_cols(d, "undecided"), "", "", unpriced, price_now, basis,
                    _ctx_money(g(pf.cost)), _ctx_money(g(pf.list_price)), _margin(cost, lp), g(pf.category), g(pf.name), *[g(f) for f in extra_fields]])
        for dv in sorted(packs_by_parent.get(mpn, []), key=lambda x: x.pack_qty):
            dd = decisions.get(dv.key)
            n = Decimal(dv.pack_qty)
            pc, pl = (cost * n if cost is not None else None), (lp * n if lp is not None else None)
            psku = _safe_sku(brand, grammar, mpn, dv.pack_qty)
            unpriced, price_now, basis = built(psku) if psku else ("", "", "")
            base_name = g(pf.name) or mpn
            name = dv.name or base_name + pricing.pack_name_suffix.format(qty=dv.pack_qty)
            out.append([dv.key, psku, f"pack P{dv.pack_qty}", *dec_cols(dd, "carry"), mpn, "", unpriced, price_now, basis,
                        _ctx_money(pc), _ctx_money(pl), _margin(pc, pl), g(pf.category), name, *["" for _ in extra_fields]])

    for dv in sorted((x for x in derivatives if x.kind == "kit"), key=lambda x: x.mpn):
        dd = decisions.get(dv.key)
        comps = ";".join(f"{m}:{q}" for m, q in dv.components)
        tc = td = Decimal(0); okc = okl = True; cat = ""
        for m, q in dv.components:
            cr = rows.get(m)
            if cr is None:
                okc = okl = False; break
            if not cat and pf.category and pf.category in cr.fields:
                cat = cr.fields[pf.category].value
            c = _num(cr.fields[pf.cost].value) if pf.cost and pf.cost in cr.fields else None
            l = _num(cr.fields[pf.list_price].value) if pf.list_price and pf.list_price in cr.fields else None
            if c is None: okc = False
            else: tc += c * q
            if l is None: okl = False
            else: td += l * q
        ksku = _safe_sku(brand, grammar, dv.mpn)
        unpriced, price_now, basis = built(ksku) if ksku else ("", "", "")
        out.append([dv.key, ksku, "kit", *dec_cols(dd, "carry"), "", comps, unpriced, price_now, basis,
                    _ctx_money(tc) if okc else "", _ctx_money(td) if okl else "", _margin(tc if okc else None, td if okl else None), cat, dv.name or f"{dv.mpn} kit", *["" for _ in extra_fields]])
    return header, out


def write_sheet(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    """Excel-friendly: BOM, CRLF, everything quoted (so Excel keeps '0045' and '5-10' as text when opened via Data→From Text)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL, lineterminator="\r\n"); w.writerow(header); w.writerows(rows)
    return path


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


def write_derivatives(pack_dir: Path, derivatives: list[Derivative]) -> Path:
    p = pack_dir / "derivatives.csv"
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(DERIVATIVE_COLUMNS)
        for dv in sorted(derivatives, key=lambda x: (x.kind, x.parent_mpn, x.pack_qty, x.mpn)):
            w.writerow([dv.kind, dv.parent_mpn, str(dv.pack_qty) if dv.kind == "pack" else "", dv.mpn,
                        ";".join(f"{m}:{q}" for m, q in dv.components), dv.name, dv.who, dv.when, dv.why])
    return p


# ---- cell validators (FR-171b). Each returns (normalised value, error or None).
_MONEY = re.compile(r"^\$?\s*(\d{1,3}(,\d{3})*|\d+)(\.\d{1,2})?$")
_SCI = re.compile(r"^\d+(\.\d+)?[eE][+-]?\d+$")
_DATE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DATE_US = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$")
_EXCEL_MONTH = re.compile(r"^(\d{1,2}-[A-Z][a-z]{2}|[A-Z][a-z]{2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}/\d{1,2})$")


def _v_price(v: str) -> tuple[str, Optional[str]]:
    if not v:
        return "", None
    if _SCI.match(v):
        return v, "looks like Excel scientific notation (e.g. 1.00E+2) — type the plain number"
    if not _MONEY.match(v):
        return v, "price must be a money amount like 99 or 99.95"
    return _money(Decimal(v.replace("$", "").replace(",", "").strip())), None


def _v_qty(v: str) -> tuple[str, Optional[str]]:
    if not v:
        return "", None
    if _SCI.match(v):
        return v, "looks like Excel scientific notation — type the plain number"
    if not re.fullmatch(r"\d+(\.0+)?", v):
        return v, "starting quantity must be a whole number (0 or more)"
    return str(int(float(v))), None


def _v_when(v: str) -> tuple[str, Optional[str]]:
    if not v:
        return "", None
    if _DATE_ISO.match(v):
        try:
            _dt.date.fromisoformat(v); return v, None
        except ValueError:
            return v, "not a real date"
    m = _DATE_US.match(v)
    if m:   # Excel re-saved it as m/d/yyyy
        mo, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        yy = yy + 2000 if yy < 100 else yy
        try:
            return _dt.date(yy, mo, dd).isoformat(), None
        except ValueError:
            return v, "not a real date"
    return v, "date must be yyyy-mm-dd"


def _v_packs(v: str) -> tuple[list[int], Optional[str]]:
    if not v:
        return [], None
    out = []
    for part in re.split(r"[;,\s]+", v.strip()):
        if not part:
            continue
        if not part.isdigit() or int(part) < 2:
            return [], f"new_pack_qty must be whole numbers of 2 or more, separated by ';' — got {part!r}"
        out.append(int(part))
    return sorted(set(out)), None


def _looks_excel_damaged_key(k: str) -> bool:
    return bool(_EXCEL_MONTH.match(k)) or bool(_SCI.match(k))


def diff_decisions(current: dict[str, Decision], sheet_rows: list[dict[str, str]], roster: set[str],
                   derivatives: list[Derivative] = (), fulfillment_vocabulary: list[str] = (), who: str = "", why: str = "") -> dict:
    """Change set of a decision sheet against current decisions, every editable cell validated (FR-171b).
    Returns changes (with 'error' on bad cells), unknown keys, the new decision table, and new packs (FR-171c)."""
    changes, unknown = [], []
    new: dict[str, Decision] = {k: Decision(**v.__dict__) for k, v in current.items()}
    derivs = list(derivatives)
    dkeys = {dv.key for dv in derivs}
    new_packs: list[Derivative] = []
    roster_nolz = {k.lstrip("0"): k for k in roster if k != k.lstrip("0")}
    vocab = list(fulfillment_vocabulary)

    def err(row_no: int, key: str, field: str, before: str, after: str, msg: str):
        changes.append({"row": row_no, "mpn": key, "field": field, "before": before, "after": after, "error": msg})

    for i, r in enumerate(sheet_rows, start=2):
        key = (r.get("mpn") or "").strip()
        if not key:
            continue
        is_deriv = key in dkeys
        if key not in roster and not is_deriv:
            hint = ""
            if _looks_excel_damaged_key(key):
                hint = " — looks like Excel turned the part number into a date/number; re-export and open the CSV via Data → From Text"
            elif key in roster_nolz:
                hint = f" — leading zeros were stripped; did you mean {roster_nolz[key]!r}?"
            if hint:
                err(i, key, "mpn", "", key, "not in the roster" + hint)
            else:
                unknown.append(key)
            continue
        cur = current.get(key, Decision(key, "carry" if is_deriv else "undecided"))
        g = lambda f: (r.get(f) or "").strip()
        st = g("carry_state") or ("carry" if is_deriv else "undecided")
        allowed = DERIVATIVE_STATES if is_deriv else CARRY_STATES
        bad = False
        if st not in allowed:
            err(i, key, "carry_state", cur.carry_state, st, f"not one of {allowed}" + (" (packs and kits are carried or skipped)" if is_deriv else "")); bad = True
        price, e = _v_price(g("price"))
        if e: err(i, key, "price", cur.price, g("price"), e); bad = True
        qty, e = _v_qty(g("initial_qty"))
        if e: err(i, key, "initial_qty", cur.initial_qty, g("initial_qty"), e); bad = True
        ful = g("fulfillment")
        if ful and vocab and ful not in vocab:
            err(i, key, "fulfillment", cur.fulfillment, ful, f"not one of {vocab} (pricing.yaml → fulfillment_vocabulary)"); bad = True
        when, e = _v_when(g("when"))
        if e: err(i, key, "when", cur.when, g("when"), e); bad = True
        packs, e = _v_packs(g("new_pack_qty"))
        if e: err(i, key, "new_pack_qty", "", g("new_pack_qty"), e); bad = True
        if packs and is_deriv:
            err(i, key, "new_pack_qty", "", g("new_pack_qty"), "a pack can only be declared on the parent product's row"); bad = True
        if bad:
            continue
        upd = Decision(key, st, g("hold_reason"), ful, qty, price, g("who"), when, g("why"))
        diff_fields = [f for f in ("carry_state", "hold_reason", "fulfillment", "initial_qty", "price") if getattr(cur, f) != getattr(upd, f)]
        for f in diff_fields:
            changes.append({"row": i, "mpn": key, "field": f, "before": getattr(cur, f), "after": getattr(upd, f)})
        if diff_fields:
            new[key] = upd
        for q in packs:
            pk = f"{key}.P{q}"
            if pk in dkeys:
                err(i, key, "new_pack_qty", "", str(q), f"pack {pk} already exists — edit its own row instead"); continue
            if upd.carry_state not in ("derivatives-only", "carry+derivatives"):
                err(i, key, "new_pack_qty", "", str(q), f"to add a pack, set this row's carry_state to derivatives-only or carry+derivatives (now {upd.carry_state!r}, FR-148)"); continue
            dkeys.add(pk)
            new_packs.append(Derivative("pack", key, q, "", [], "", who or upd.who, "", why or ""))   # the apply's who/why, not the parent row's old basis
            changes.append({"row": i, "mpn": key, "field": "new_pack_qty", "before": "", "after": f"P{q} → new row {pk}"})
    by_field: dict[str, int] = {}
    for c in changes:
        by_field[c["field"]] = by_field.get(c["field"], 0) + 1
    errors = [c for c in changes if "error" in c]
    return {"changes": changes, "unknown_mpns": unknown, "new_decisions": new, "new_packs": new_packs, "errors": errors,
            "counts": {"changes": len(changes), "by_field": by_field, "unknown": len(unknown), "errors": len(errors), "new_packs": len(new_packs)}}


def apply_sheet(pack_dir: Path, d: dict, derivatives: list[Derivative], who: str, why: str, sheet_name: str) -> dict[str, str]:
    """Write the outcome of diff_decisions: decisions.csv always, derivatives.csv when packs were added.
    Caller has already checked d['errors'] is empty and d['changes'] is not."""
    when = _dt.datetime.now().date().isoformat()
    for ch in d["changes"]:
        if ch["mpn"] in d["new_decisions"]:
            nd = d["new_decisions"][ch["mpn"]]
            nd.who = nd.who or (who or "operator"); nd.when = nd.when or when; nd.why = nd.why or (why or f"decision sheet {sheet_name}")
    written = {"decisions": str(write_decisions(pack_dir, d["new_decisions"]))}
    if d["new_packs"]:
        for dv in d["new_packs"]:
            dv.who = dv.who or (who or "operator"); dv.when = dv.when or when; dv.why = dv.why or (why or f"decision sheet {sheet_name}")
        written["derivatives"] = str(write_derivatives(pack_dir, [*derivatives, *d["new_packs"]]))
    return written
