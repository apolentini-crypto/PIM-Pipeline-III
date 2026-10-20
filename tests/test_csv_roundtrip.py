"""FR-137..139 / AC-29..32: the CSV bulk-edit round trip."""
import csv
import shutil
from pathlib import Path

import pytest

from pim.build import build
from pim.store.csv_io import export_csv, import_csv, write_overrides
from pim.store.db import latest_build_id, open_db, read_build
from tests.conftest import FIXTURE_PACK

FIELDS = ["name", "list_price", "head_type", "ean"]


@pytest.fixture
def built(tmp_path):
    pack = tmp_path / "pack"; shutil.copytree(FIXTURE_PACK, pack)
    var = tmp_path / "var"
    build(pack, var)
    con = open_db(var / "fixture-brand" / "pim.db")
    rows = read_build(con, latest_build_id(con)); con.close()
    return pack, var, rows


def _rewrite(path: Path, fn):
    with path.open(encoding="utf-8-sig", newline="") as fh:
        recs = list(csv.DictReader(fh))
    recs = fn(recs); header = list(recs[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header, quoting=csv.QUOTE_ALL, lineterminator="\r\n"); w.writeheader(); w.writerows(recs)


def test_ac29_unmodified_reimport_is_empty(built, tmp_path):
    pack, var, rows = built
    p = export_csv(rows, FIELDS, tmp_path / "e.csv")
    raw = p.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw and b'"sku","name"' in raw   # BOM, CRLF, quoted
    rep = import_csv(p, rows, set(FIELDS) | {"mpn", "length_mm"})
    assert rep["counts"]["changes"] == 0 and rep["counts"]["damage"] == 0


def test_ac30_bulk_edit_is_reversible(built, tmp_path):
    pack, var, rows = built
    p = export_csv(rows, FIELDS, tmp_path / "e.csv")
    def edit(recs):
        for r in recs:
            r["name"] = r["name"] + " X"; r["head_type"] = "Flat"; r["list_price"] = "1.00"
        return recs
    _rewrite(p, edit)
    rep = import_csv(p, rows, set(FIELDS) | {"mpn", "length_mm"})
    assert rep["counts"]["changes"] == 12 and rep["counts"]["by_field"] == {"name": 4, "head_type": 4, "list_price": 4}
    ov = write_overrides(pack, rep["changes"], "test", "AC-30")
    r2 = build(pack, var)
    assert r2.rows["RX-100"].fields["name"].value == "Ergo Cutter 100 X" and len(r2.applied_overrides) == 12
    ov.unlink()                                                  # un-change: remove the override file
    r3 = build(pack, var)
    assert r3.rows["RX-100"].fields["name"].value == "Ergo Cutter 100" and r3.applied_overrides == []


def test_ac31_spreadsheet_damage_is_refused(built, tmp_path):
    pack, var, rows = built
    p = export_csv(rows, FIELDS, tmp_path / "e.csv")
    def damage(recs):
        for r in recs:
            r["ean"] = r["ean"] + ".0" if not r["ean"].startswith("0") else r["ean"].lstrip("0")   # float-ified / lost zeros
        recs[0]["name"] = "LindstrÃ¶m cutter"                                                    # mojibake
        return recs
    _rewrite(p, damage)
    rep = import_csv(p, rows, set(FIELDS) | {"mpn"})
    assert rep["counts"]["damage"] == 5 and rep["counts"]["changes"] == 0
    kinds = {k for d in rep["damage"] for k in d["suspected"]}
    assert {"float-ified integer", "lost leading zeros", "mojibake"} <= kinds


def test_ac32_unknown_column_is_refused(built, tmp_path):
    pack, var, rows = built
    p = export_csv(rows, FIELDS, tmp_path / "e.csv")
    _rewrite(p, lambda recs: [{**r, "colour": "red"} for r in recs])
    rep = import_csv(p, rows, set(FIELDS) | {"mpn"})
    assert rep["unknown_columns"] == ["colour"]


def test_unknown_sku_reported_not_added(built, tmp_path):
    pack, var, rows = built
    p = export_csv(rows, FIELDS, tmp_path / "e.csv")
    _rewrite(p, lambda recs: recs + [{"sku": "GHOST", "name": "x", "list_price": "", "head_type": "", "ean": ""}])
    rep = import_csv(p, rows, set(FIELDS) | {"mpn"})
    assert rep["unknown_skus"] == ["GHOST"] and rep["counts"]["changes"] == 0
