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


def test_save_pack_binds_pricing_fields_and_keeps_operator_edits(tmp_path, monkeypatch):
    """A Pace-shaped setup: the sheet must show title / category / MSRP without a hand edit,
    and a second Save pack must not wipe a rule the operator wrote into pricing.yaml."""
    from pim.ui.server import guess_pricing_fields
    fields = {"sku": {}, "title": {}, "category": {}, "msrp_price": {"type": "number"}, "weight": {}, "dealer_cost": {"type": "number"}}
    assert guess_pricing_fields(fields) == {"name": "title", "category": "category", "list_price": "msrp_price", "cost": "dealer_cost"}

    monkeypatch.setattr("pim.ui.server.BRANDS", tmp_path)
    shutil.copytree(FIXTURE_PACK, tmp_path / "fixture-brand")
    st = load_pack("fixture-brand")
    pricing = tmp_path / "fixture-brand" / "pricing.yaml"
    doc = yaml.safe_load(pricing.read_text(encoding="utf-8"))
    doc["rules"] = [{"scope": "default", "basis": "discount-off-msrp", "factor": 0.2, "basis_note": "operator"}]
    doc["margin_floor_pct"] = 15
    pricing.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    r = write_pack(st, overwrite=True)
    assert not r["errors"], r["errors"]
    after = yaml.safe_load(pricing.read_text(encoding="utf-8"))
    assert after["rules"][0]["basis"] == "discount-off-msrp" and after["margin_floor_pct"] == 15
    assert after["fields"] == doc["fields"]          # bindings already there are untouched


def test_open_local_only_opens_files_under_var(tmp_path, monkeypatch):
    from pim.ui.server import open_local
    monkeypatch.setattr("pim.ui.server._var", lambda: tmp_path / "var")
    assert "export a sheet first" in open_local("")["error"]
    outside = tmp_path / "elsewhere.csv"; outside.write_text("x")
    assert "only files under" in open_local(str(outside))["error"]
    assert "not found" in open_local(str(tmp_path / "var" / "nope.csv"))["error"]


def test_pack_fields_lists_kept_columns_and_bindings(tmp_path, monkeypatch):
    from pim.ui.server import pack_fields
    monkeypatch.setattr("pim.ui.server.BRANDS", tmp_path)
    shutil.copytree(FIXTURE_PACK, tmp_path / "fixture-brand")
    r = pack_fields("fixture-brand")
    names = {f["name"]: f for f in r["fields"]}
    fy = yaml.safe_load((FIXTURE_PACK / "fields.yaml").read_text(encoding="utf-8"))["fields"]
    assert set(names) == set(fy)
    py = yaml.safe_load((FIXTURE_PACK / "pricing.yaml").read_text(encoding="utf-8"))["fields"]
    for role, fname in py.items():
        assert names[fname]["bound_as"] == role
    assert "no pack" in pack_fields("nope")["error"]


# ---- 2026-11-18: reopen sheets already on disk; never overwrite an edited sheet; self-restart
def test_open_brand_finds_sheets_already_on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr("pim.ui.server.BRANDS", tmp_path / "brands")
    monkeypatch.setenv("PIM_VAR_DIR", str(tmp_path / "var"))
    shutil.copytree(FIXTURE_PACK, tmp_path / "brands" / "fixture-brand")
    assert load_pack("fixture-brand")["sheets"] == {"decisions": None, "fields": None}
    ed = tmp_path / "var" / "fixture-brand" / "edits"; ed.mkdir(parents=True)
    (ed / "fixture-brand-decisions.csv").write_text("mpn\n", encoding="utf-8")
    (ed / "fixture-brand-abc123.csv").write_text("sku\n", encoding="utf-8")
    s = load_pack("fixture-brand")["sheets"]
    assert s["decisions"]["path"].endswith("fixture-brand-decisions.csv") and s["decisions"]["modified"]
    assert s["fields"]["path"].endswith("fixture-brand-abc123.csv")


def test_export_keeps_the_previous_sheet(tmp_path):
    from pathlib import Path
    from pim.ui.server import _keep_previous
    p = tmp_path / "x-decisions.csv"
    assert _keep_previous(p) is None                      # nothing there yet: nothing kept
    p.write_text("edited in excel\n", encoding="utf-8")
    p.with_suffix(".types.json").write_text("{}", encoding="utf-8")
    kept = Path(_keep_previous(p))
    assert kept.parent.name == "previous" and kept.read_text(encoding="utf-8") == "edited in excel\n"
    assert list(kept.parent.glob("*.types.json"))       # the field sheet's type file travels with it


def test_code_change_is_detected(monkeypatch):
    import pim.ui.server as s
    assert not s._code_stamp() > s.CODE_STAMP            # unchanged since import
    monkeypatch.setattr(s, "CODE_STAMP", 0.0)
    assert s._code_stamp() > s.CODE_STAMP                # any newer file counts as a change


# ---- one window only (2026-11-18): a second launch never starts a second server -------------------
def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_window(port):
    import threading
    from pim.ui import server as S
    srv = S._make_server(port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _no_second_server(monkeypatch):
    from pim.ui import server as S
    def refuse(port):
        raise AssertionError("a second PIM server was started")
    monkeypatch.setattr(S, "_make_server", refuse)


def test_second_launch_opens_the_running_window_and_starts_nothing(monkeypatch):
    from pim.ui import server as S
    port = _free_port(); first = _run_window(port)
    opened = []; monkeypatch.setattr(S.webbrowser, "open", lambda u: opened.append(u))
    _no_second_server(monkeypatch)
    try:
        assert S.serve(port=port, open_browser=True) == "already-running"
        assert opened == [f"http://127.0.0.1:{port}/"]          # the running window is shown instead
        assert S.probe(port)["kind"] == "pim"                     # and it is still running, untouched
        assert S._http(port, "/api/shutdown", post=True)[0] == 404   # nothing can stop it from outside any more
        assert S.probe(port)["kind"] == "pim"
    finally:
        first.shutdown(); first.server_close()


def test_running_window_on_older_code_is_asked_to_restart_itself(monkeypatch):
    from pim.ui import server as S
    port = _free_port(); first = _run_window(port)
    monkeypatch.setattr(S, "CODE_STAMP", -1.0)                    # the running window's code is older than the files
    monkeypatch.setattr(S, "_wait", lambda cond, seconds: True)   # PIM.bat would relaunch it; there is no PIM.bat here
    monkeypatch.setattr(S.webbrowser, "open", lambda u: None)
    _no_second_server(monkeypatch)
    try:
        assert S.serve(port=port, open_browser=True) == "already-running"
        assert S.RESTART.is_set()                                  # it was asked to restart (exit 75) — not killed
    finally:
        S.RESTART.clear(); first.server_close()


def test_port_held_by_another_program_is_left_alone(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from pim.ui import server as S
    class Other(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"some other program")
        def log_message(self, *a):
            pass
    port = _free_port(); other = HTTPServer(("127.0.0.1", port), Other)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    _no_second_server(monkeypatch)
    try:
        assert S.probe(port) == {"kind": "other"}
        assert S.serve(port=port, open_browser=False) == "port-busy"
    finally:
        other.shutdown(); other.server_close()


def test_two_launches_at_the_same_moment_end_with_one_window(monkeypatch):
    from pim.ui import server as S
    port = _free_port(); first = _run_window(port)
    real_probe = S.probe; calls = []
    def racing_probe(p):                      # the 2nd launch looked before the 1st was listening
        calls.append(p)
        return None if len(calls) == 1 else real_probe(p)
    monkeypatch.setattr(S, "probe", racing_probe)
    monkeypatch.setattr(S.webbrowser, "open", lambda u: None)
    try:
        assert S.serve(port=port, open_browser=False) == "already-running"   # its bind was refused; it found the 1st
        assert real_probe(port)["kind"] == "pim"
    finally:
        first.shutdown(); first.server_close()


def test_windows_bind_refuses_a_second_listener():
    import os
    from pim.ui import server as S
    # Python's HTTPServer sets SO_REUSEADDR, which on Windows lets two processes listen on one port
    assert S._OneWindowServer.allow_reuse_address is (os.name != "nt")
