"""D-8 grammar: {brand}.{mpn}[-{cond}][.{M|n|P<qty>}] — the one parser, no fuzzy matching."""
import pytest

from pim.util.sku import Sku, SkuError, SkuGrammar, build_sku, normalise_mpn, parse_sku


@pytest.fixture
def g(store):
    return SkuGrammar.from_store(store)


@pytest.mark.parametrize("text,brand,mpn,cond,kind,ending", [
    ("2.53131A",        "2",  "53131A",     None, None,     None),
    ("2.53131A.M",      "2",  "53131A",     None, "master", "M"),
    ("2.53131A.1",      "2",  "53131A",     None, "unit",   "1"),
    ("2.53131A-U.1",    "2",  "53131A",     "U",  "unit",   "1"),
    ("2.53131A.P3",     "2",  "53131A",     None, "pack",   "P3"),
    ("25.0960-2545",    "25", "0960-2545",  None, None,     None),   # dash INSIDE an mpn is fine
    ("23.K2-HKIT-U",    "23", "K2-HKIT",    "U",  None,     None),   # trailing -U is the condition
    ("59.TL15A-GW",     "59", "TL15A-GW",   None, None,     None),   # -GW is not a condition code
    ("2.34401-45011-U", "2",  "34401-45011","U",  None,     None),
])
def test_parse(g, text, brand, mpn, cond, kind, ending):
    k = parse_sku(text, g)
    assert (k.brand, k.mpn, k.condition, k.ending_kind, k.ending) == (brand, mpn, cond, kind, ending)
    assert k.base == f"{brand}.{mpn}"


def test_pack_qty_and_unit_seq(g):
    assert parse_sku("2.53131A.P10", g).pack_qty == 10
    assert parse_sku("2.53131A.7", g).unit_seq == 7
    assert parse_sku("2.53131A", g).pack_qty is None


@pytest.mark.parametrize("bad,rule", [
    ("59-8130",       "dash directly after the brand"),   # the live Lindström shape
    ("2.53131A.X",    "none of master/unit/pack"),
    ("2.53131A.1-U",  "none of master/unit/pack"),        # condition must precede the ending
    ("2.53131A.P0",   "none of master/unit/pack"),
    ("2.5313.1A",     "none of master/unit/pack"),        # dot inside an mpn reads as a bad ending
    ("53131A",        "no part separator"),
    ("2.53131A.M.1",  "too many parts"),
    ("x.53131A",      "brand"),
    (" 2.53131A",     "whitespace"),
    ("",              "empty"),
])
def test_reject(g, bad, rule):
    with pytest.raises(SkuError) as ei:
        parse_sku(bad, g)
    assert rule in str(ei.value)


def test_build_round_trips(g):
    assert build_sku(59, "RX8130", g) == "59.RX8130"
    assert build_sku(59, "RX8130", g, pack_qty=10) == "59.RX8130.P10"
    assert build_sku(2, "53131A", g, condition="U", unit_seq=1) == "2.53131A-U.1"
    assert build_sku(2, "53131A", g, master=True) == "2.53131A.M"
    with pytest.raises(SkuError):
        build_sku(2, "53131A", g, pack_qty=2, master=True)
    with pytest.raises(SkuError):
        build_sku(2, "53131A", g, condition="NEW")
    with pytest.raises(SkuError):
        build_sku(2, "5313.1A", g)  # mpn with a dot can never be emitted


def test_normalise_mpn():
    rule = {"upper": True, "strip_whitespace": True, "replace": {".": "-"}, "allowed": "A-Z0-9_-", "trim": "-_"}
    assert normalise_mpn("TL 15A-GW", rule) == "TL15A-GW"
    assert normalise_mpn(" rx 8130 ", rule) == "RX8130"
    assert normalise_mpn("SMD291AX10/5", rule) == "SMD291AX105"
    assert normalise_mpn("0960.2545", rule) == "0960-2545"
    with pytest.raises(SkuError):
        normalise_mpn("---", rule)
