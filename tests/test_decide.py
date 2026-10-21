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
    assert c.fields["price"].value == "100.50" and c.price_basis == "rule:default:msrp-passthrough" and round(c.margin_pct, 1) == 40.3
    t = r.catalog["99.TL15A-GW"]
    assert t.fields["price"].value == "121.50" and t.price_basis.startswith("rule:category:discount-off-msrp")   # 135 × 0.9, category rule beats default
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
    assert c.fields["price"].value == "110.00"        # msrp passthrough works even with no cost
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
    assert k.fields["price"].value == "296.50"    # msrp passthrough on summed list 100.5 + 2×98


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


def _read_sheet(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return rows


def test_sheet_has_one_row_per_ct_sku_and_is_read_back_from_disk(pack, tmp_path):
    """FR-171a — checked on the WRITTEN file, not the in-memory rows."""
    from pim.build import export_decision_sheet
    _decide(pack, {"RX-100": "carry+derivatives", "RX-101": "carry"},
            ["pack,RX-100,5,,,,t,2026-10-20,fixture", "kit,,,CUT-SET,RX-100:1;RX-101:2,Cutter Set 3 pc,t,2026-10-20,fixture"])
    r = export_decision_sheet(pack, tmp_path / "var", ["ean"])
    rows = _read_sheet(r["path"])
    keys = [x["mpn"] for x in rows]
    assert keys == ["HS-200", "RX-100", "RX-100.P5", "RX-101", "TL 15A-GW", "CUT-SET"]   # undecided HS-200 present; pack under parent; kit last
    by = {x["mpn"]: x for x in rows}
    assert by["HS-200"]["carry_state"] == "undecided" and by["HS-200"]["— sku"] == "99.HS-200" and by["HS-200"]["— basis"] == "not built"
    pk = by["RX-100.P5"]
    assert pk["— kind"] == "pack P5" and pk["— sku"] == "99.RX-100.P5" and pk["— parent"] == "RX-100" and pk["carry_state"] == "carry"
    assert pk["— cost"] == "300.00" and pk["— list"] == "502.50" and pk["— price now"] == "419.95" and pk["— name"] == "Ergo Cutter 100 — 5-pack"
    kit = by["CUT-SET"]
    assert kit["— kind"] == "kit" and kit["— components"] == "RX-100:1;RX-101:2" and kit["— cost"] == "176.00" and kit["— sku"] == "99.CUT-SET"
    assert by["RX-100"]["— ean"] == "7314150100001" and pk["— ean"] == ""
    assert r["kinds"] == {"original": 4, "pack": 1, "kit": 1} and r["rows"] == 6
    # file is Excel-friendly: BOM + CRLF + fully quoted
    raw = Path(r["path"]).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw and b'"mpn","\xe2\x80\x94 sku"' in raw


def test_sheet_import_validates_every_cell_and_refuses(pack, tmp_path):
    """FR-171b — bad cells are named by row/column; nothing is written while any stands."""
    from pim.build import export_decision_sheet, import_decision_sheet
    _decide(pack, {"RX-100": "carry+derivatives"}, ["pack,RX-100,5,,,,t,2026-10-20,fixture"])
    r = export_decision_sheet(pack, tmp_path / "var", [])
    rows = _read_sheet(r["path"]); by = {x["mpn"]: x for x in rows}
    by["RX-100"]["price"] = "1.00E+2"; by["RX-101"]["initial_qty"] = "2.5"; by["RX-101"]["fulfillment"] = "warehouse"
    by["HS-200"]["when"] = "13/45/2026"; by["RX-100.P5"]["carry_state"] = "derivatives-only"; by["RX-100.P5"]["new_pack_qty"] = "10"
    rows.append({**{k: "" for k in rows[0]}, "mpn": "5-Oct", "carry_state": "carry"})
    rows.append({**{k: "" for k in rows[0]}, "mpn": "GHOST", "carry_state": "carry"})
    sheet = tmp_path / "edited.csv"
    with sheet.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    d = import_decision_sheet(pack, tmp_path / "var", sheet, apply=True)
    errs = {(c["mpn"], c["field"]): c["error"] for c in d["changes"] if "error" in c}
    assert "scientific" in errs[("RX-100", "price")]
    assert "whole number" in errs[("RX-101", "initial_qty")]
    assert "fulfillment_vocabulary" in errs[("RX-101", "fulfillment")]
    assert "date" in errs[("HS-200", "when")]
    assert "carried or skipped" in errs[("RX-100.P5", "carry_state")]
    assert "parent product" in errs[("RX-100.P5", "new_pack_qty")]
    assert "Excel turned" in errs[("5-Oct", "mpn")]
    assert d["unknown"] == ["GHOST"] and d["refused"] == "fix the errors first" and "written" not in d
    assert load_decisions(pack)["RX-100"].price == ""                                   # untouched


def test_sheet_import_normalises_and_applies_derivative_decisions_and_new_packs(pack, tmp_path):
    """FR-171b/c + FR-173a — money to 2 decimals, Excel dates to ISO, a pack skipped/held/priced on its own row, a new pack from new_pack_qty."""
    from pim.build import export_decision_sheet, import_decision_sheet
    from pim.decide.core import load_derivatives
    _decide(pack, {"RX-100": "carry+derivatives", "RX-101": "carry"},
            ["pack,RX-100,5,,,,t,2026-10-20,fixture", "kit,,,CUT-SET,RX-100:1;RX-101:2,Cutter Set 3 pc,t,2026-10-20,fixture"])
    r = export_decision_sheet(pack, tmp_path / "var", [])
    rows = _read_sheet(r["path"]); by = {x["mpn"]: x for x in rows}
    by["RX-101"]["price"] = "$1,234.5"; by["RX-101"]["when"] = "10/20/26"; by["RX-101"]["initial_qty"] = "3.0"
    by["CUT-SET"]["carry_state"] = "skip"
    by["RX-100.P5"]["hold_reason"] = "waiting on pack label"; by["RX-100.P5"]["price"] = "400"
    by["RX-100"]["new_pack_qty"] = "10; 25"
    sheet = tmp_path / "edited.csv"
    with sheet.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    d = import_decision_sheet(pack, tmp_path / "var", sheet, apply=False, who="Tony")
    assert d["errors"] == 0 and d["counts"]["new_packs"] == 2 and "written" not in d       # dry run writes nothing
    d = import_decision_sheet(pack, tmp_path / "var", sheet, apply=True, who="Tony", why="range review")
    assert d["written"].endswith("decisions.csv") and d["written_derivatives"].endswith("derivatives.csv")
    dec = load_decisions(pack)
    assert dec["RX-101"].price == "1234.50" and dec["RX-101"].when == "2026-10-20" and dec["RX-101"].initial_qty == "3"
    assert dec["CUT-SET"].carry_state == "skip" and dec["RX-100.P5"].hold_reason == "waiting on pack label" and dec["RX-100.P5"].price == "400.00"
    assert {x.key for x in load_derivatives(pack)} == {"RX-100.P5", "CUT-SET", "RX-100.P10", "RX-100.P25"}
    assert [x for x in load_derivatives(pack) if x.key == "RX-100.P10"][0].why == "range review"
    # and the build honours all of it
    res = build(pack, tmp_path / "var")
    assert "99.CUT-SET" not in res.catalog and res.decide_counts["derivatives_skipped"] == 1
    p5 = res.catalog["99.RX-100.P5"]
    assert p5.held == "waiting on pack label" and p5.fields["price"].value == "400.00" and p5.price_basis == "decision:RX-100.P5"
    assert res.catalog["99.RX-100.P10"].fields["cost"].value == "600" and res.catalog["99.RX-100.P25"].kind == "pack"
    assert res.catalog["99.RX-101"].fields["price"].value == "1234.50"
    # re-export now shows the new rows and the stored decisions, read back from disk again
    r2 = export_decision_sheet(pack, tmp_path / "var", [])
    by2 = {x["mpn"]: x for x in _read_sheet(r2["path"])}
    assert [k for k in by2 if k.startswith("RX-100")] == ["RX-100", "RX-100.P5", "RX-100.P10", "RX-100.P25"]
    assert by2["CUT-SET"]["carry_state"] == "skip" and by2["CUT-SET"]["— basis"] == "not built" and by2["RX-100.P5"]["— price now"] == "400.00"


def test_bad_derivative_state_in_decisions_file_halts(pack, tmp_path):
    _decide(pack, {"RX-100": "carry+derivatives", "RX-100.P5": "carry+derivatives"}, ["pack,RX-100,5,,,,t,2026-10-20,fixture"])
    with pytest.raises(HaltError) as ei:
        build(pack, tmp_path / "var")
    assert "FR-173a" in str(ei.value)


def test_decision_sheet_diff_and_write(pack, tmp_path):
    cur = {"RX-100": Decision("RX-100", "carry")}
    sheet = [{"mpn": "RX-100", "carry_state": "carry+derivatives", "price": "77"}, {"mpn": "RX-101", "carry_state": "skip"},
             {"mpn": "GHOST", "carry_state": "carry"}, {"mpn": "HS-200", "carry_state": "wrong"}]
    d = diff_decisions(cur, sheet, {"RX-100", "RX-101", "HS-200"})
    assert d["counts"] == {"changes": 4, "by_field": {"carry_state": 3, "price": 1}, "unknown": 1, "errors": 1, "new_packs": 0}
    assert d["new_decisions"]["RX-101"].carry_state == "skip" and d["new_decisions"]["RX-100"].price == "77.00"
    p = write_decisions(pack, {k: v for k, v in d["new_decisions"].items() if k != "HS-200"})
    assert load_decisions(pack)["RX-101"].carry_state == "skip"
    assert set(CARRY_STATES) == {"undecided", "carry", "skip", "derivatives-only", "carry+derivatives"}


def test_catalog_diff_sees_a_decision_change_the_product_diff_cannot():
    """Walk snag 2026-10-20: skipping a product or hand-setting a price changed nothing in rows.jsonl,
    so 'What changed' reported 0. The catalog diff must show it (FR-42 applied to CT SKUs)."""
    from pim.store.export import diff_catalogs, diff_exports
    before = {"99.A": {"sku": "99.A", "kind": "original", "held": False, "price_basis": "rule:default:msrp-passthrough", "unpriced": False,
                       "parent_mpn": None, "pack_qty": None, "fields": {"price": {"v": "100.00"}, "name": {"v": "A"}}},
              "99.B": {"sku": "99.B", "kind": "original", "held": False, "price_basis": "rule:default:msrp-passthrough", "unpriced": False,
                       "parent_mpn": None, "pack_qty": None, "fields": {"price": {"v": "50.00"}, "name": {"v": "B"}}}}
    after = {"99.A": {**before["99.A"], "price_basis": "decision:A", "fields": {"price": {"v": "99.00"}, "name": {"v": "A"}}}}
    d = diff_catalogs(before, after)
    assert d["removed"] == ["99.B"]
    assert d["changed"]["99.A"]["price"] == {"before": "100.00", "after": "99.00"}
    assert d["changed"]["99.A"]["_price_basis"]["after"] == "decision:A"
    assert d["counts"] == {"added": 0, "removed": 1, "changed_rows": 1, "changed_cells": 2, "unchanged_rows": 0}
    # the product-level diff of the same canonical rows is silent — that is the whole point
    rows = {"A": {"sku": "A", "fields": {"name": {"v": "A"}}, "held": False}, "B": {"sku": "B", "fields": {"name": {"v": "B"}}, "held": False}}
    assert diff_exports(rows, rows)["counts"]["changed_rows"] == 0
