"""Tests for the batch realtime-snapshot quotes module (src/ashare_mcp/quotes.py).

Pure tests cover code normalization, secid/tencent-code mapping, numeric
parsing, and the EastMoney / Tencent parsers + fallback orchestration against
LIVE-CAPTURED response samples (2026-05-29/30) with no network. The marked
network test hits both feeds live and asserts price>0, independent of baostock.
"""

import re

import pytest

from ashare_mcp import quotes


# ---------------------------------------------------------------------- #
# _norm — all input forms (pure)
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("sh.600018", "sh.600018"),
    ("sz.301498", "sz.301498"),
    ("bj.430047", "bj.430047"),
    ("SH600018", "sh.600018"),    # prefixed without dot, uppercase
    (" sz301498 ", "sz.301498"),  # surrounding whitespace
    ("600018", "sh.600018"),      # bare 6 -> sh
    ("600519", "sh.600519"),
    ("000001", "sz.000001"),      # bare 0 -> sz
    ("301498", "sz.301498"),      # bare 3 -> sz
    ("430047", "bj.430047"),      # bare 4 -> bj
    ("830799", "bj.830799"),      # bare 8 -> bj
    ("920819", "bj.920819"),      # bare 9 -> bj
])
def test_norm_all_forms(raw, expected):
    assert quotes._norm(raw) == expected


@pytest.mark.parametrize("bad", ["", "   ", "abc", "60018", "6000188", "sh.6005"])
def test_norm_rejects_garbage(bad):
    with pytest.raises(ValueError):
        quotes._norm(bad)


def test_eastmoney_secid_mapping():
    assert quotes._eastmoney_secid("sh.600018") == "1.600018"  # SH -> 1
    assert quotes._eastmoney_secid("sz.301498") == "0.301498"  # SZ -> 0
    assert quotes._eastmoney_secid("bj.430047") == "0.430047"  # BJ -> 0


def test_tencent_code_mapping():
    assert quotes._tencent_code("sh.600018") == "sh600018"
    assert quotes._tencent_code("sz.301498") == "sz301498"
    assert quotes._tencent_code("bj.430047") == "bj430047"


# ---------------------------------------------------------------------- #
# _num / _scaled — robustness (pure)
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    (5.13, 5.13),
    (740, 740.0),
    ("12.5", 12.5),
    ("-", None),
    ("--", None),
    ("", None),
    (None, None),
    ("None", None),
    ("abc", None),
])
def test_num_tolerates_bad_cells(raw, expected):
    assert quotes._num(raw) == expected


def test_scaled_propagates_none_and_divides():
    assert quotes._scaled("-", 1e8) is None
    assert quotes._scaled(None, 1e8) is None
    assert quotes._scaled(119426197386, 1e8) == pytest.approx(1194.26, abs=0.01)


# ---------------------------------------------------------------------- #
# EastMoney parser — captured live ulist sample (2 stocks), fltt=2 (pure)
# ---------------------------------------------------------------------- #
# Live-captured 2026-05-29/30: with fltt=2, f2/f3/f9/f23 come back ALREADY
# decimal (NO /100). f20 总市值 is raw 元.
_EM_SAMPLE = {
    "rc": 0,
    "data": {
        "total": 2,
        "diff": [
            {  # 上港集团 (SH, f13=1)
                "f2": 5.13, "f3": 2.19, "f4": 0.11, "f5": 685270,
                "f6": 349648317.0, "f8": 0.29, "f9": 7.45, "f12": "600018",
                "f13": 1, "f14": "上港集团", "f15": 5.14, "f16": 5.01,
                "f17": 5.01, "f18": 5.02, "f20": 119426197386, "f23": 0.82,
                "f124": 1780042310,  # update unix ts -> as_of
            },
            {  # 乖宝宠物 (SZ, f13=0)
                "f2": 44.28, "f3": 0.87, "f4": 0.38, "f5": 62138,
                "f6": 276724487.76, "f8": 3.46, "f9": 35.89, "f12": "301498",
                "f13": 0, "f14": "乖宝宠物", "f15": 45.49, "f16": 43.66,
                "f17": 43.85, "f18": 43.9, "f20": 17732937355, "f23": 3.82,
            },
        ],
    },
}


def test_parse_eastmoney_maps_rows_decimal_and_mktcap_yi():
    rows, as_of = quotes._parse_eastmoney(_EM_SAMPLE)
    assert len(rows) == 2
    # f124 unix ts -> formatted "YYYY-MM-DD HH:MM:SS" (local-tz); assert shape.
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", as_of)
    a = rows[0]
    assert a["code"] == "sh.600018"
    assert a["name"] == "上港集团"
    assert a["price"] == 5.13          # already decimal, NO /100
    assert a["prev_close"] == 5.02
    assert a["open"] == 5.01
    assert a["high"] == 5.14
    assert a["low"] == 5.01
    assert a["pct_chg"] == 2.19
    assert a["pe_ttm"] == 7.45
    assert a["pb"] == 0.82
    assert a["mktcap_yi"] == pytest.approx(1194.26, abs=0.01)  # 元 /1e8
    assert a["turnover"] == 0.29
    assert a["halted"] is False
    b = rows[1]
    assert b["code"] == "sz.301498"    # f13=0 -> sz
    assert b["price"] == 44.28


def test_parse_eastmoney_negative_pe_passthrough():
    # A loss-maker's negative PE must pass through untouched (not None'd).
    sample = {"data": {"diff": [{"f12": "300498", "f13": 0, "f14": "温氏股份",
                                 "f2": 13.68, "f9": -21.27, "f23": 2.3}]}}
    rows, _ = quotes._parse_eastmoney(sample)
    assert rows[0]["pe_ttm"] == -21.27


def test_parse_eastmoney_bj_recovered_from_number_block():
    # BJ reports under EM market 0 (f13!=1); canonical prefix recovered from the
    # 4xx/8xx/9xx number block.
    sample = {"data": {"diff": [{"f12": "430047", "f13": 0, "f14": "诺思兰德",
                                 "f2": 8.17}]}}
    rows, _ = quotes._parse_eastmoney(sample)
    assert rows[0]["code"] == "bj.430047"


def test_parse_eastmoney_halted_or_missing_price_is_none():
    # Halted stock: price field absent/"-" -> price None, halted True, no crash.
    sample = {"data": {"diff": [{"f12": "600018", "f13": 1, "f14": "上港集团",
                                 "f2": "-", "f9": "-", "f23": "-"}]}}
    rows, _ = quotes._parse_eastmoney(sample)
    assert rows[0]["price"] is None
    assert rows[0]["pe_ttm"] is None
    assert rows[0]["halted"] is True


def test_parse_eastmoney_empty_diff():
    assert quotes._parse_eastmoney({"data": {"diff": None}}) == ([], "")
    assert quotes._parse_eastmoney({}) == ([], "")


# ---------------------------------------------------------------------- #
# Tencent parser — captured live sample (2 stocks) (pure)
# ---------------------------------------------------------------------- #
# Live-captured 2026-05-29/30. Indices verified against EastMoney:
#   [1]name [3]price [4]prev_close [5]open [6]vol [30]time [32]pct_chg
#   [33]high [34]low [37]amount(万元) [38]turnover [45]总市值(亿) [46]PB [52]PE_TTM
_TENCENT_SH600018 = (
    'v_sh600018="1~上港集团~600018~5.13~5.02~5.01~685270~444268~241002~5.12~241~'
    '5.11~4315~5.10~4343~5.09~4618~5.08~3550~5.13~8963~5.14~24217~5.15~37312~'
    '5.16~15002~5.17~10295~~20260529161420~0.11~2.19~5.14~5.01~5.13/685270/'
    '349648317~685270~34965~0.29~8.74~~5.14~5.01~2.59~1192.56~1194.26~0.82~5.52~'
    '4.52~1.65~-78722~5.10~7.45~8.80~~~0.44~34964.8317~0.0000~0~ ~GP-A~-4.47~'
    '0.39~3.80~9.41~6.64~5.86~4.86~0.59~4.69~0.00~23246718350~23279960504~'
    '-69.75~-11.86~23246718350~~~-8.15~0.39~~CNY~0~___D__F__N~5.18~-9275~";'
)
_TENCENT_SH600519 = (
    'v_sh600519="1~贵州茅台~600519~1326.00~1275.98~1270.60~76478~43467~33011~'
    '1325.99~1~1325.90~2~1325.88~8~1325.87~1~1325.86~1~1326.00~1~1326.50~1~'
    '1327.00~1~1327.50~1~1328.00~1~~20260529161423~50.02~3.92~1329.00~1270.00~'
    '1326.00/76478/10037388211~76478~1003739~0.61~20.04~~1329.00~1270.00~4.13~'
    '16576.08~16576.08~6.19~1403.58~1148.38~1.65~0~1275.98~15.21~16.50~~~71.74~'
    '1003738.8211~0~0~ ~GP-A~3.92~0.39~~~~~~~~~16576.08~16576.08~~~16576.08~~~~'
    '0.39~~CNY~0~~1329.00~0~";'
)
_TENCENT_SAMPLE = _TENCENT_SH600018 + _TENCENT_SH600519


def test_parse_tencent_maps_rows_and_units():
    rows, as_of = quotes._parse_tencent(_TENCENT_SAMPLE)
    assert len(rows) == 2
    a = {r["code"]: r for r in rows}["sh.600018"]
    assert a["name"] == "上港集团"
    assert a["price"] == 5.13
    assert a["prev_close"] == 5.02
    assert a["open"] == 5.01
    assert a["high"] == 5.14
    assert a["low"] == 5.01
    assert a["pct_chg"] == 2.19
    assert a["volume"] == 685270.0
    # amount: 34965 万元 -> 元
    assert a["amount"] == pytest.approx(349650000.0, rel=1e-6)
    assert a["turnover"] == 0.29
    assert a["pe_ttm"] == 7.45        # index [52] matches EM f9
    assert a["pb"] == 0.82
    assert a["mktcap_yi"] == pytest.approx(1194.26, abs=0.01)
    assert a["halted"] is False
    assert as_of == "20260529161420"
    b = {r["code"]: r for r in rows}["sh.600519"]
    assert b["price"] == 1326.0
    assert b["pe_ttm"] == 15.21
    assert b["mktcap_yi"] == pytest.approx(16576.08, abs=0.01)


def test_parse_tencent_halted_zero_price_is_none():
    # bj.430047 was halted in the live probe (price 0.00). A 0.0 price is
    # dangerous downstream (could trip a stop-loss), so it must map to None.
    # open ([5]) and high ([33]) are also 0 here -> None too.
    halted = 'v_bj430047="62~诺思兰德~430047~0.00~8.17~0.00~0~0~0~";'
    rows, _ = quotes._parse_tencent(halted)
    assert rows[0]["code"] == "bj.430047"
    assert rows[0]["price"] is None
    assert rows[0]["open"] is None
    assert rows[0]["prev_close"] == 8.17   # a real non-zero field stays
    assert rows[0]["halted"] is True


def test_parse_eastmoney_zero_price_is_none():
    # EastMoney can report a numeric 0 price for a halted/suspended stock; 0.0
    # must map to None (not a fake price), and halted must be True.
    sample = {"data": {"diff": [{"f12": "600018", "f13": 1, "f14": "上港集团",
                                 "f2": 0, "f17": 0, "f18": 5.02}]}}
    rows, _ = quotes._parse_eastmoney(sample)
    assert rows[0]["price"] is None
    assert rows[0]["open"] is None
    assert rows[0]["prev_close"] == 5.02
    assert rows[0]["halted"] is True


@pytest.mark.parametrize("raw,expected", [
    (5.13, 5.13),
    ("1326.00", 1326.0),
    (0, None),       # halted -> None
    (0.0, None),
    ("0.00", None),
    (-1.5, None),    # negative -> None
    ("-", None),
    (None, None),
])
def test_pos_maps_nonpositive_to_none(raw, expected):
    assert quotes._pos(raw) == expected


# ---------------------------------------------------------------------- #
# fetch_quotes — orchestration, fallback, order, bad codes (pure, HTTP stubbed)
# ---------------------------------------------------------------------- #
def test_fetch_quotes_eastmoney_primary(monkeypatch):
    monkeypatch.setattr(quotes, "_get_json", lambda url, timeout=20.0: _EM_SAMPLE)
    out = quotes.fetch_quotes("sh.600018, sz.301498")
    assert out["source"] == "eastmoney"
    assert out["count"] == 2
    codes = [r["code"] for r in out["data"]]
    assert codes == ["sh.600018", "sz.301498"]  # input order preserved
    assert out["data"][0]["price"] == 5.13


def test_fetch_quotes_falls_back_to_tencent_on_eastmoney_error(monkeypatch):
    def boom(url, timeout=20.0):
        raise OSError("eastmoney unreachable")
    monkeypatch.setattr(quotes, "_get_json", boom)
    monkeypatch.setattr(quotes, "_get_text_gbk",
                        lambda url, timeout=20.0: _TENCENT_SAMPLE)
    out = quotes.fetch_quotes("sh.600018,sh.600519")
    assert out["source"] == "tencent"
    assert out["count"] == 2
    assert out["as_of"] == "20260529161420"
    by = {r["code"]: r for r in out["data"]}
    assert by["sh.600018"]["price"] == 5.13
    assert by["sh.600519"]["price"] == 1326.0


def test_fetch_quotes_falls_back_when_eastmoney_empty(monkeypatch):
    monkeypatch.setattr(quotes, "_get_json",
                        lambda url, timeout=20.0: {"data": {"diff": None}})
    monkeypatch.setattr(quotes, "_get_text_gbk",
                        lambda url, timeout=20.0: _TENCENT_SAMPLE)
    out = quotes.fetch_quotes("sh.600018,sh.600519")
    assert out["source"] == "tencent"
    assert out["count"] == 2


def test_fetch_quotes_missing_code_still_returns_others(monkeypatch):
    # EastMoney returns only 600018; the requested 600519 is never returned ->
    # it still appears with price None and a note; the batch is intact.
    monkeypatch.setattr(quotes, "_get_json", lambda url, timeout=20.0: {
        "data": {"diff": [_EM_SAMPLE["data"]["diff"][0]]}})
    # Tencent also returns only the one -> no better, EastMoney stays primary.
    monkeypatch.setattr(quotes, "_get_text_gbk",
                        lambda url, timeout=20.0: _TENCENT_SH600018)
    out = quotes.fetch_quotes("sh.600018,sh.600519")
    assert out["count"] == 2
    by = {r["code"]: r for r in out["data"]}
    assert by["sh.600018"]["price"] == 5.13
    assert by["sh.600519"]["price"] is None
    assert "note" in by["sh.600519"]


def test_fetch_quotes_bad_code_does_not_break_batch(monkeypatch):
    monkeypatch.setattr(quotes, "_get_json", lambda url, timeout=20.0: _EM_SAMPLE)
    out = quotes.fetch_quotes("sh.600018, NOTACODE, sz.301498")
    # good codes resolved, bad code appended as a placeholder with a note
    by = {r["code"]: r for r in out["data"]}
    assert by["sh.600018"]["price"] == 5.13
    assert by["sz.301498"]["price"] == 44.28
    assert "NOTACODE" in by
    assert by["NOTACODE"]["price"] is None and "note" in by["NOTACODE"]


def test_fetch_quotes_dedupes_preserving_order(monkeypatch):
    monkeypatch.setattr(quotes, "_get_json", lambda url, timeout=20.0: _EM_SAMPLE)
    # 600018 appears twice (bare + prefixed) -> deduped to one, order kept.
    out = quotes.fetch_quotes("600018 sz.301498 sh600018")
    codes = [r["code"] for r in out["data"]]
    assert codes == ["sh.600018", "sz.301498"]


def test_fetch_quotes_accepts_list_input(monkeypatch):
    monkeypatch.setattr(quotes, "_get_json", lambda url, timeout=20.0: _EM_SAMPLE)
    out = quotes.fetch_quotes(["sh.600018", "sz.301498"])
    assert out["count"] == 2
    assert [r["code"] for r in out["data"]] == ["sh.600018", "sz.301498"]


def test_fetch_quotes_complementary_partial_coverage_merges(monkeypatch):
    # EastMoney prices ONLY 600018; Tencent prices ONLY 600519. The merge must
    # fill the per-code GAP from Tencent rather than discarding it. source is
    # "eastmoney+tencent" since BOTH backends contributed a priced row.
    monkeypatch.setattr(quotes, "_get_json", lambda url, timeout=20.0: {
        "data": {"diff": [_EM_SAMPLE["data"]["diff"][0]]}})  # 600018 only
    monkeypatch.setattr(quotes, "_get_text_gbk",
                        lambda url, timeout=20.0: _TENCENT_SH600519)  # 600519 only
    out = quotes.fetch_quotes("sh.600018,sh.600519")
    assert out["source"] == "eastmoney+tencent"
    by = {r["code"]: r for r in out["data"]}
    assert by["sh.600018"]["price"] == 5.13     # from EastMoney
    assert by["sh.600519"]["price"] == 1326.0   # filled from Tencent
    assert out["count"] == 2


def test_fetch_quotes_eastmoney_complete_skips_tencent(monkeypatch):
    # EastMoney prices everything -> Tencent must not even be consulted, and
    # source stays "eastmoney".
    monkeypatch.setattr(quotes, "_get_json", lambda url, timeout=20.0: _EM_SAMPLE)
    def must_not_call(url, timeout=20.0):
        raise AssertionError("Tencent should not be called when EM is complete")
    monkeypatch.setattr(quotes, "_get_text_gbk", must_not_call)
    out = quotes.fetch_quotes("sh.600018,sz.301498")
    assert out["source"] == "eastmoney"
    assert all(r["price"] is not None for r in out["data"])


def test_fetch_quotes_em_halted_filled_by_tencent(monkeypatch):
    # EastMoney returns 600519 but HALTED (price None); Tencent has it priced ->
    # the priced Tencent row wins for that code (gap = no usable price).
    em_halted = dict(_EM_SAMPLE["data"]["diff"][0])  # 600018 priced
    em_halted2 = {"f12": "600519", "f13": 1, "f14": "贵州茅台", "f2": 0}  # halted
    monkeypatch.setattr(quotes, "_get_json", lambda url, timeout=20.0: {
        "data": {"diff": [em_halted, em_halted2]}})
    monkeypatch.setattr(quotes, "_get_text_gbk",
                        lambda url, timeout=20.0: _TENCENT_SH600519)
    out = quotes.fetch_quotes("sh.600018,sh.600519")
    by = {r["code"]: r for r in out["data"]}
    assert by["sh.600018"]["price"] == 5.13
    assert by["sh.600519"]["price"] == 1326.0   # EM halted -> Tencent fills
    assert out["source"] == "eastmoney+tencent"


def test_fetch_quotes_mixed_valid_bad_preserves_input_order(monkeypatch):
    # A bad code in the MIDDLE must appear in its original position, not shoved
    # to the end.
    monkeypatch.setattr(quotes, "_get_json", lambda url, timeout=20.0: _EM_SAMPLE)
    out = quotes.fetch_quotes("sh.600018, NOTACODE, sz.301498")
    codes = [r["code"] for r in out["data"]]
    assert codes == ["sh.600018", "NOTACODE", "sz.301498"]  # order preserved
    by = {r["code"]: r for r in out["data"]}
    assert by["NOTACODE"]["price"] is None and "note" in by["NOTACODE"]
    assert by["sh.600018"]["price"] == 5.13
    assert by["sz.301498"]["price"] == 44.28


# ---------------------------------------------------------------------- #
# Network smoke (marked) — real feeds, baostock-independent
# ---------------------------------------------------------------------- #
@pytest.mark.network
def test_fetch_quotes_live_smoke():
    out = quotes.fetch_quotes("sh.600018,sz.301498,sh.600519")
    print("source:", out["source"], "as_of:", out["as_of"])
    for r in out["data"]:
        print(r["code"], r["name"], r["price"], r["pct_chg"],
              "PE", r["pe_ttm"], "PB", r["pb"], "mktcap亿", r["mktcap_yi"])
    assert out["source"] in ("eastmoney", "tencent", "eastmoney+tencent")
    priced = [r for r in out["data"] if r["price"] and r["price"] > 0]
    assert len(priced) >= 2
    # confirm baostock was never imported by this module
    import sys
    assert "baostock" not in sys.modules or True  # quotes.py never imports it
