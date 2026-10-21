"""Stage 2b — A1 §3: carry states, packs, kits, SKUs, pricing rules, decision sheet."""
import csv
import shutil
from pathlib import Path

import pytest

from pim.build import build
from pim.decide.core import CARRY_STATES, Decision, diff_decisions, load_decisions, write_decisions
from pim.normalize.core import HaltError
from tests.conftest import FIXTURE_PACK


@pytest.fixture
def pack(tmp_path):
    dst = tmp_path / "pack"; shutil.copytree(FIXTURE_PACK, dst); return dst


def _decide(pack, decisions: dict[str, str] | None = None, derivs: list[str] = (), extra_dec: dict = None):
    (pack / "decisions").mkdir(exist_ok=True)
    with (pack / "decisions" / "decisions.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n"); w.writerow(["mpn", "carry_state", "hold_reason", "fulfillment", "initial_qty", "price", "who", "when", "why"])
        for mpn, st in (decisions or {}).items():
            e = (extra_dec or {}).get(mpn, {})
            w.writerow([mpn, st, e.get("hold", ""), e.get("fulfillment", ""), e.get("qty", ""), e.get("price", ""), "t", "2026-10-20", "fixture"])
    with (pack / "derivatives.csv").open("w", encoding="utf-8", newline="") as fh:
        fh.write("kind,parent_mpn,pack_qty,mpn,components,name,who,when,why\n" + "".join(d + "\n" for d in derivs))


def test_undecided_produces_no_catalog_rows(pack, tmp_path):
    r = build(pack, tmp_path / "var")
    assert r.catalog == {} and r.decide_counts["undecided"] == 4


def test_carry_builds_sku_price_and_margin(pack, tmp_path):
    _decide(pack, {"RX-100": "carry", "TL 15A-GW": "carry", "RX-101": "skip"})
    r = build(pack, tmp_path / "var")
    assert set(r.catalog) == {"99.RX-100", "99.TL15A-GW"}            # D-8 grammar; skip and undecided absent
    c = r.catalog["99.RX-100"]
    assert c.fields["price"].value == "100.5" and c.price_basis == "rule:default:msrp-passthrough" and round(c.margin_pct, 1) == 40.3
    t = r.catalog["99.TL15A-GW"]
    assert t.fields["price"].value == "121.5" and t.price_basis.startswith("rule:category:discount-off-msrp")   # 135 × 0.9, category rule beats default
    assert c.fields["ct_sku"].prov.kind == "derived"


def test_decision_price_beats_rules_and_fulfillment_is_checked(pack, tmp_path):
    _decide(pack, {"RX-100": "carry"}, extra_dec={"RX-100": {"price": "89.99", "fulfillment": "stock", "qty": "12"}})
    c = build(pack, tmp_path / "var").catalog["99.RX-100"]
    assert c.fields["price"].value == "89.99" and c.price_basis == "decision:RX-100" and c.fields["initial_qty"].value == "12"
    _decide(pack, {"RX-100": "carry"}, extra_dec={"RX-100": {"fulfillment": "drone"}})
    with pytest.raises(HaltError) as ei:
        build(pack, tmp_path / "var")
    assert "fulfillment 'drone'" in str(ei.value)


def test_unpriced_row_is_held_when_declared(pack, tmp_path):
    _decide(pack, {"HS-200": "carry"})
    r = build(pack, tmp_path / "var")
    c = r.catalog["99.HS-200"]
    assert c.fields["price"].value == "110"          # msrp passthrough works even with no cost
    p = pack / "sources" / "prices.csv"; p.write_text(p.read_text(encoding="utf-8").replace("HS-200,110.00", "HS-200,"), encoding="utf-8")
    r = build(pack, tmp_path / "var")
    c = r.catalog["99.HS-200"]
    assert c.unpriced and c.held == "unpriced" and r.assertions["G-PRICE"]["measured"] == 1


def test_pack_derivative_multiplies_each_never_divides(pack, tmp_path):
    _decide(pack, {"RX-100": "carry+derivatives"}, ["pack,RX-100,5,,,,t,2026-10-20,fixture"])
    r = build(pack, tmp_path / "var")
    p = r.catalog["99.RX-100.P5"]
    assert p.kind == "pack" and p.parent_mpn == "RX-100" and p.pack_qty == 5
    assert p.fields["cost"].value == "300" and p.fields["cost"].prov.ref == "pack:5×RX-100.cost"
    assert p.fields["weight_g"].value == "350" and p.fields["weight_g"].unit == "g"
    assert p.fields["name"].value == "Ergo Cutter 100 — 5-pack"
    assert p.fields["price"].value == "419.95" and "markup-on-cost" in p.price_basis      # 300 × 1.4 = 420 → .95 rounding
    assert p.fields["head_type"].prov.kind == "inherited"
    assert "length_mm" in p.fields and "unit_length_mm" not in p.fields                     # dims never computed (FR-147)
    assert "99.RX-100" in r.catalog                                                          # carry+derivatives keeps the single


def test_derivatives_only_drops_the_single(pack, tmp_path):
    _decide(pack, {"RX-100": "derivatives-only"}, ["pack,RX-100,10,,,,t,2026-10-20,fixture"])
    r = build(pack, tmp_path / "var")
    assert set(r.catalog) == {"99.RX-100.P10"}


def test_pack_with_wrong_parent_state_fails_gate(pack, tmp_path):
    _decide(pack, {"RX-100": "carry"}, ["pack,RX-100,5,,,,t,2026-10-20,fixture"])
    with pytest.raises(HaltError) as ei:
        build(pack, tmp_path / "var")
    assert "G-DERIV" in str(ei.value) and "RX-100 is 'carry'" in str(ei.value)


def test_kit_sums_components_and_has_its_own_sku(pack, tmp_path):
    _decide(pack, {"RX-100": "carry", "RX-101": "carry"}, ["kit,,,CUT-SET,RX-100:1;RX-101:2,Cutter Set 3 pc,t,2026-10-20,fixture"])
    r = build(pack, tmp_path / "var")
    k = r.catalog["99.CUT-SET"]
    assert k.kind == "kit" and k.fields["cost"].value == "176" and k.fields["weight_g"].value == "206"   # 60 + 2×58 ; 70 + 2×68
    assert k.fields["name"].value == "Cutter Set 3 pc" and k.fields["kit_components"].value == "RX-100:1;RX-101:2"
    assert k.fields["mpn"].value == "CUT-SET" and "ean" not in k.fields
    assert k.fields["price"].value == "296.5"     # msrp passthrough on summed list 100.5 + 2×98


def test_kit_with_unknown_component_fails_gate(pack, tmp_path):
    _decide(pack, {}, ["kit,,,BAD,RX-100:1;NOPE:1,x,t,2026-10-20,fixture"])
    with pytest.raises(HaltError) as ei:
        build(pack, tmp_path / "var")
    assert "G-DERIV" in str(ei.value) and "NOPE" in str(ei.value)


def test_bad_carry_state_halts(pack, tmp_path):
    _decide(pack, {"RX-100": "maybe"})
    with pytest.raises(HaltError) as ei:
        build(pack, tmp_path / "var")
    assert "carry_state 'maybe'" in str(ei.value)


def test_missing_brand_id_halts_decide(pack, tmp_path):
    _decide(pack, {"RX-100": "carry"})
    b = pack / "brand.yaml"; b.write_text(b.read_text(encoding="utf-8").replace("brand_id: 99", "brand_id: null"), encoding="utf-8")
    with pytest.raises(HaltError) as ei:
        build(pack, tmp_path / "var")
    assert "brand_id is not set" in str(ei.value)


def test_decision_for_vanished_mpn_is_kept_and_reported(pack, tmp_path):
    _decide(pack, {"GHOST": "carry"})
    r = build(pack, tmp_path / "var")
    assert any("'GHOST'" in n and "no longer in the roster" in n for n in r.notes)
    assert "GHOST" in load_decisions(pack)


def test_decision_sheet_diff_and_write(pack, tmp_path):
    cur = {"RX-100": Decision("RX-100", "carry")}
    sheet = [{"mpn": "RX-100", "carry_state": "carry+derivatives", "price": "77"}, {"mpn": "RX-101", "carry_state": "skip"},
             {"mpn": "GHOST", "carry_state": "carry"}, {"mpn": "HS-200", "carry_state": "wrong"}]
    d = diff_decisions(cur, sheet, {"RX-100", "RX-101", "HS-200"})
    assert d["counts"] == {"changes": 4, "by_field": {"carry_state": 3, "price": 1}, "unknown": 1, "errors": 1}
    assert d["new_decisions"]["RX-101"].carry_state == "skip" and d["new_decisions"]["RX-100"].price == "77"
    p = write_decisions(pack, {k: v for k, v in d["new_decisions"].items() if k != "HS-200"})
    assert load_decisions(pack)["RX-101"].carry_state == "skip"
    assert set(CARRY_STATES) == {"undecided", "carry", "skip", "derivatives-only", "carry+derivatives"}
