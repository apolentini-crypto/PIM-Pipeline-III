"""M1 — ingest, merge, aliases (D-7), units, overrides, store, export, determinism (AC-3), diff (FR-42)."""
import json
import shutil
from pathlib import Path

import pytest
import yaml

from pim.build import build
from pim.ingest.readers import cell_text
from pim.normalize.core import HaltError, encoding_issues, parse_unit_value
from pim.config.models import UnitSpec
from pim.store.export import diff_exports, read_export
from tests.conftest import FIXTURE_PACK


@pytest.fixture
def pack(tmp_path):
    dst = tmp_path / "pack"
    shutil.copytree(FIXTURE_PACK, dst)
    return dst


def _build(pack, tmp_path, **kw):
    return build(pack, tmp_path / "var", **kw)


# ----------------------------------------------------------------- FR-8 text first
@pytest.mark.parametrize("v,want", [
    (7314150103003.0, "7314150103003"), (108.0, "108"), (0.07, "0.07"), (1.5, "1.5"), (True, "TRUE"), (None, ""),
    ("#NAME?", ""), ("  keep  ", "  keep  "), (42, "42"), (float("nan"), ""),
])
def test_cell_text(v, want):
    assert cell_text(v) == want


# ----------------------------------------------------------------- FR-21/22 units
def test_unit_parse():
    u = UnitSpec(parse="in-value", expect=["mm", "in"])
    assert parse_unit_value("133.5 mm", u) == ("133.5", "mm")
    assert parse_unit_value("4,72 in", u) == ("4.72", "in")
    assert parse_unit_value("0,2 - 1,0 mm", u) == ("0.2–1.0", "mm")
    assert parse_unit_value("6", u) == ("6", None)                 # bare number: unit unknown
    v, issue = parse_unit_value("0,010 in", UnitSpec(parse="in-value", expect=["mm"]))
    assert v == "" and issue.startswith("unexpected unit")
    assert parse_unit_value("50", UnitSpec(parse="declared", unit="g")) == ("50", "g")


def test_encoding_issues():
    assert encoding_issues("45º Tapered") == ["U+00BA masculine ordinal used as degree sign"]
    assert encoding_issues("45° Tapered") == []
    assert "mojibake" in encoding_issues("LindstrÃ¶m")[0]
    assert encoding_issues("Ergo™ Micro-Bevel® 0.2–1 mm N·m") == []   # legitimate non-ASCII survives (profile §4.3)


# ----------------------------------------------------------------- build on the fixture
def test_fixture_builds_with_provenance(pack, tmp_path):
    r = _build(pack, tmp_path)
    assert len(r.rows) == 4
    row = r.rows["RX-100"]
    assert row.fields["name"].value == "Ergo Cutter 100"
    assert row.fields["name"].prov.kind == "source_cell" and "Title" in row.fields["name"].prov.ref
    assert row.fields["length_mm"].value == "133.5" and row.fields["length_mm"].unit == "mm"
    # alias fires only when primary is empty, with alias provenance (FR-18/19)
    assert r.rows["RX-101"].fields["length_mm"].prov.kind == "alias_cell"
    # association table maps the price book's compact code to the roster key (FR-16)
    assert r.rows["TL 15A-GW"].fields["list_price"].value == "135.00"
    assert r.rows["TL 15A-GW"].fields["list_price"].prov.kind == "association"
    # EAN with a leading zero survives as text (FR-8)
    assert r.rows["HS-200"].fields["ean"].value == "0012345678905"


def test_rebuild_is_byte_identical(pack, tmp_path):
    """AC-3 / NFR-1."""
    a = _build(pack, tmp_path)
    b = _build(pack, tmp_path)
    assert a.build_id == b.build_id and a.rows_sha256 == b.rows_sha256
    assert a.export_path.read_bytes() == b.export_path.read_bytes()


def test_d7_alias_conflict_halts(pack, tmp_path):
    """D-7 / FR-20: primary and alias both populated and disagreeing beyond tolerance HALTS naming both."""
    p = pack / "sources" / "prices.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("RX-100,100.50,133.5 mm", "RX-100,100.50,150 mm"))
    with pytest.raises(HaltError) as ei:
        _build(pack, tmp_path)
    msg = str(ei.value)
    assert "D-7 CONFLICT" in msg and "RX-100.length_mm" in msg and "'133.5'" in msg and "'150'" in msg and "Total length" in msg


def test_different_units_are_not_compared(pack, tmp_path):
    """'6 in' vs '152.4 mm' is not a conflict: converting would invent a measurement (FR-132)."""
    p = pack / "sources" / "prices.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("RX-100,100.50,133.5 mm", "RX-100,100.50,5.25 in"))
    r = _build(pack, tmp_path)
    assert r.rows["RX-100"].fields["length_mm"].value == "133.5"


def test_unitless_measurement_not_adopted(pack, tmp_path):
    p = pack / "sources" / "products.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("RX-101,Ergo Cutter 101,,", "RX-101,Ergo Cutter 101,120,"))
    r = _build(pack, tmp_path)
    # bare '120' in the primary is reported and skipped; the alias '120 mm' supplies the value
    assert r.rows["RX-101"].fields["length_mm"].prov.kind == "alias_cell"
    assert any("carries no unit" in n for n in r.notes)


def test_duplicate_key_in_source_halts(pack, tmp_path):
    p = pack / "sources" / "products.csv"
    p.write_text(p.read_text(encoding="utf-8") + "RX-100,Dup,,Oval,1\n")
    with pytest.raises(HaltError) as ei:
        _build(pack, tmp_path)
    assert "duplicate key" in str(ei.value) and "RX-100" in str(ei.value)


def test_required_field_missing_halts_naming_sku(pack, tmp_path):
    p = pack / "sources" / "products.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("HS-200,Long Cutter 200", "HS-200,"))
    with pytest.raises(HaltError) as ei:
        _build(pack, tmp_path)
    assert "G-REQUIRED" in str(ei.value) and "HS-200.name" in str(ei.value)


def test_expectation_mismatch_halts(pack, tmp_path):
    (pack / "expectations.yaml").write_text("roster_count: 5\n", encoding="utf-8")
    with pytest.raises(HaltError) as ei:
        _build(pack, tmp_path)
    assert "G-ROSTER" in str(ei.value) and "measured 4 expected 5" in str(ei.value)


def test_text_fix_is_declared_and_noted(pack, tmp_path):
    p = pack / "sources" / "products.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("Tapered", "45º Tapered"), encoding="utf-8")
    with pytest.raises(HaltError) as ei:            # without the declaration the gate halts
        _build(pack, tmp_path)
    assert "G-ENCODING" in str(ei.value)
    b = pack / "brand.yaml"
    b.write_text(b.read_text(encoding="utf-8") + 'text_fixes: { "º": "°" }\n', encoding="utf-8")
    r = _build(pack, tmp_path)
    assert r.rows["RX-101"].fields["head_type"].value == "45° Tapered"
    assert any("text fix" in n for n in r.notes)


# ----------------------------------------------------------------- overrides (FR-25/26)
def _write_override(pack, sku, field, before, after, name="t.yaml"):
    (pack / "overrides").mkdir(exist_ok=True)
    (pack / "overrides" / name).write_text(yaml.safe_dump({"overrides": [
        {"sku": sku, "field": field, "before": before, "after": after, "basis": {"who": "test", "when": "2026-10-19", "why": "fixture"}}]}))


def test_override_applies_and_is_reversible(pack, tmp_path):
    _write_override(pack, "RX-100", "name", "Ergo Cutter 100", "Ergo Cutter 100 (Oval)")
    r = _build(pack, tmp_path)
    fv = r.rows["RX-100"].fields["name"]
    assert fv.value == "Ergo Cutter 100 (Oval)" and fv.prov.kind == "override" and r.applied_overrides == ["t.yaml#1"]
    (pack / "overrides" / "t.yaml").unlink()          # FR-26: deleting restores the source value
    assert _build(pack, tmp_path).rows["RX-100"].fields["name"].value == "Ergo Cutter 100"


def test_stale_override_halts(pack, tmp_path):
    _write_override(pack, "RX-100", "name", "Some Old Title", "New Title")
    with pytest.raises(HaltError) as ei:
        _build(pack, tmp_path)
    assert "STALE override" in str(ei.value) and "RX-100.name" in str(ei.value)


def test_override_on_unknown_sku_or_field_halts(pack, tmp_path):
    _write_override(pack, "NOPE", "name", None, "x")
    with pytest.raises(HaltError):
        _build(pack, tmp_path)
    _write_override(pack, "RX-100", "nofield", None, "x")
    with pytest.raises(HaltError):
        _build(pack, tmp_path)


# ----------------------------------------------------------------- diff (FR-42)
def test_diff_two_builds(pack, tmp_path):
    a = _build(pack, tmp_path)
    p = pack / "sources" / "prices.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("HS-200,110.00", "HS-200,115.00") + "NEW-1,5.00,\n")
    b = _build(pack, tmp_path)
    d = diff_exports(read_export(a.export_path), read_export(b.export_path))
    assert d["counts"] == {"added": 0, "removed": 0, "changed_rows": 1, "changed_cells": 1, "unchanged_rows": 3}
    assert d["changed"]["HS-200"]["list_price"] == {"before": "110.00", "after": "115.00"}


def test_csv_encoding_is_declared(pack, tmp_path):
    """A Windows-saved (cp1252) CSV halts with a message naming the fix; declaring the encoding reads it."""
    p = pack / "sources" / "products.csv"
    p.write_bytes(p.read_text(encoding="utf-8").replace("Tapered", "45° Tapered").encode("cp1252"))
    with pytest.raises(HaltError) as ei:
        _build(pack, tmp_path)
    assert "encoding: cp1252" in str(ei.value)
    s = pack / "sources.yaml"
    s.write_text(s.read_text(encoding="utf-8").replace("format: csv, key_column: \"Part Number\"", "format: csv, encoding: cp1252, key_column: \"Part Number\""), encoding="utf-8")
    assert _build(pack, tmp_path).rows["RX-101"].fields["head_type"].value == "45° Tapered"
