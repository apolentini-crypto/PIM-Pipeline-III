"""The PIM window writes the same YAML the build reads — and nothing else (D-6)."""
import shutil

import yaml

from pim.ui.server import inspect, list_files, load_pack, render_pack, source_status, suggest_name, validate_state, write_pack
from tests.conftest import FIXTURE_PACK, REPO


def test_suggest_name():
    assert suggest_name("en_US#SHORT DESCRIPTION P") == "short_description_p"
    assert suggest_name("Tip Width, mm") == "tip_width_mm"
    assert suggest_name("8-1-2026 List Price") == "8_1_2026_list_price"


def test_list_and_inspect_fixture_sources():
    ls = list_files(str(FIXTURE_PACK / "sources"))
    assert [f["path"] for f in ls["files"]] == ["prices.csv", "products.csv"]
    i = inspect(str(FIXTURE_PACK / "sources"), "products.csv", "csv", None, 1)
    assert i["headers"] == ["Part Number", "Title", "Length", "Head Type", "EAN"] and i["total_rows"] == 5
    bad = inspect(str(FIXTURE_PACK / "sources"), "nope.csv", "csv", None, 1)
    assert "not found" in bad["error"]


def test_pack_round_trips_through_the_window(tmp_path, monkeypatch):
    """load → render reproduces fields.yaml / sources.yaml / joins.yaml exactly (as data)."""
    monkeypatch.setattr("pim.ui.server.BRANDS", tmp_path)
    shutil.copytree(FIXTURE_PACK, tmp_path / "fixture-brand")
    st = load_pack("fixture-brand")
    r = render_pack(st)
    from pim.config.models import PACK_FILES
    for fn in ("fields.yaml", "sources.yaml", "joins.yaml"):
        model = PACK_FILES[fn][0]
        a = model.model_validate(yaml.safe_load((tmp_path / "fixture-brand" / fn).read_text(encoding="utf-8")))
        b = model.model_validate(yaml.safe_load(r[fn]))
        assert a.model_dump() == b.model_dump(), fn   # same meaning after defaults; spelling may differ
    assert validate_state(st)["ok"]


def test_write_pack_refuses_overwrite_then_writes(tmp_path, monkeypatch):
    monkeypatch.setattr("pim.ui.server.BRANDS", tmp_path)
    shutil.copytree(FIXTURE_PACK, tmp_path / "fixture-brand")
    st = load_pack("fixture-brand")
    st["brand"]["slug"] = "fixture-brand"
    r = write_pack(st, overwrite=False)
    assert "exists" in r and "fields.yaml" in r["exists"]
    r = write_pack(st, overwrite=True)
    assert r["errors"] == [] and "fields.yaml" in r["written"]
    assert write_pack({"brand": {"slug": "Bad Slug"}}, True)["error"].startswith("slug must be")


def test_source_status_reports_change(tmp_path, monkeypatch):
    """FR-11: new → build → unchanged → edit a file → changed."""
    from pim.build import build
    monkeypatch.setattr("pim.ui.server.BRANDS", tmp_path)
    monkeypatch.setenv("PIM_VAR_DIR", str(tmp_path / "var"))
    shutil.copytree(FIXTURE_PACK, tmp_path / "fixture-brand")
    assert source_status("fixture-brand")["summary"]["new"] == 2
    build(tmp_path / "fixture-brand", tmp_path / "var")
    assert source_status("fixture-brand")["summary"] == {"unchanged": 2, "changed": 0, "new": 0, "missing": 0}
    p = tmp_path / "fixture-brand" / "sources" / "prices.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("110.00", "115.00"), encoding="utf-8")
    st = source_status("fixture-brand")
    assert st["summary"]["changed"] == 1 and [s["id"] for s in st["sources"] if s["state"] == "changed"] == ["S2"]


def test_sheet_import_refuses_blank_or_missing_path_politely(tmp_path):
    """Walk snag 2026-10-20: a blank path reached pathlib and surfaced as a raw ValueError."""
    from pim.ui.server import _check_sheet_path
    assert "no file given" in _check_sheet_path("")["error"]
    assert "no file given" in _check_sheet_path("   ")["error"]
    assert "file not found" in _check_sheet_path(str(tmp_path / "nope.csv"))["error"]
    assert "folder" in _check_sheet_path(str(tmp_path))["error"]
    x = tmp_path / "sheet.xlsx"; x.write_bytes(b"")
    assert ".csv" in _check_sheet_path(str(x))["error"]
    c = tmp_path / "sheet.csv"; c.write_text("mpn\n", encoding="utf-8")
    assert _check_sheet_path(str(c)) is None
