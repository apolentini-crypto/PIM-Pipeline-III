from pathlib import Path

from pim.config.loader import validate_pack
from tests.conftest import FIXTURE_PACK


def test_fixture_pack_is_valid():
    rep = validate_pack(FIXTURE_PACK)
    assert rep.ok, [str(e) for e in rep.errors]
    assert len(rep.models) == 9  # 11 declared, expectations.yaml + thresholds.yaml absent in the fixture


def test_missing_dir_is_an_error(tmp_path):
    rep = validate_pack(tmp_path / "nope")
    assert not rep.ok and "does not exist" in str(rep.errors[0])


def test_unknown_key_is_rejected(tmp_path):
    import shutil
    dst = tmp_path / "p"; shutil.copytree(FIXTURE_PACK, dst)
    (dst / "pricing.yaml").write_text("rules: []\nmargn_floor_pct: 5\n")
    rep = validate_pack(dst)
    assert any("margn_floor_pct" in str(e) and "pricing.yaml" in str(e) for e in rep.errors)


def test_ownerless_managed_field_fails(tmp_path):
    """FR-55 / AC-6: a managed field with no owner is a build failure naming the field."""
    import shutil
    dst = tmp_path / "p"; shutil.copytree(FIXTURE_PACK, dst)
    (dst / "managed.yaml").write_text("managed: all-mapped\nunmanaged: []\nowners: { name: catalog }\n")
    rep = validate_pack(dst)
    msgs = [str(e) for e in rep.errors]
    assert any("no owner" in m and "list_price" in m and "mpn" in m for m in msgs), msgs


def test_pricing_rule_needs_factor(tmp_path):
    import shutil
    dst = tmp_path / "p"; shutil.copytree(FIXTURE_PACK, dst)
    (dst / "pricing.yaml").write_text("rules:\n  - { scope: brand, basis: markup-on-cost }\n")
    rep = validate_pack(dst)
    assert any("factor is required" in str(e) for e in rep.errors)
