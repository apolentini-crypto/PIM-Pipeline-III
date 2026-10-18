from pathlib import Path
import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
FIXTURE_PACK = REPO / "tests" / "fixtures" / "brands" / "fixture-brand"


@pytest.fixture(scope="session")
def store():
    return yaml.safe_load((REPO / "store" / "store.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def good_ctx(tmp_path, store):
    """The GOOD context every check must pass on."""
    return {
        "pack_dir": str(FIXTURE_PACK),
        "tmp": str(tmp_path),
        "store": store,
        "skus": ["2.53131A", "2.53131A.M", "2.53131A.1", "2.53131A-U.1", "2.53131A.P3",
                 "59.RX8130", "25.0960-2545", "23.K2-HKIT-U", "36.3C6XPCS", "59.TL15A-GW"],
    }
