import pytest

from ashare_mcp.codes import normalize_code


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("sh.600519", "sh.600519"),
        ("SH600519", "sh.600519"),
        (" sz.000001 ", "sz.000001"),
        ("bj.430047", "bj.430047"),
        ("600519", "sh.600519"),   # SSE A-share
        ("688981", "sh.688981"),   # STAR market
        ("510300", "sh.510300"),   # SSE ETF
        ("000001", "sz.000001"),   # bare -> stock reading (Ping An Bank)
        ("002049", "sz.002049"),
        ("300750", "sz.300750"),
        ("159915", "sz.159915"),   # SZSE ETF
        ("830799", "bj.830799"),   # BSE
        ("920819", "bj.920819"),   # BSE 920 block
    ],
)
def test_normalize_code(raw, expected):
    assert normalize_code(raw) == expected


@pytest.mark.parametrize("bad", ["", "   ", "abc", "60051", "6005199", "sh.6005"])
def test_normalize_code_rejects_garbage(bad):
    with pytest.raises(ValueError):
        normalize_code(bad)
