"""Live baostock smoke tests. Run with: uv run pytest -m network -q"""

import pytest

pytestmark = pytest.mark.network


@pytest.fixture(scope="module")
def provider():
    from ashare_mcp.providers.baostock import BaostockProvider

    p = BaostockProvider()
    yield p
    p.close()


def _ok(payload):
    assert set(payload) == {"count", "fields", "data"}
    assert isinstance(payload["data"], list)
    assert isinstance(payload["fields"], list)
    return payload


def test_stock_basic(provider):
    out = _ok(provider.get_stock_basic("sh.600519"))
    assert out["count"] == 1
    assert out["data"][0]["code_name"] == "贵州茅台"


def test_k_data_daily(provider):
    out = _ok(provider.get_history_k_data("sz.000001", "2024-01-02", "2024-01-10", "d"))
    assert out["count"] > 0
    assert "peTTM" in out["fields"] and "turn" in out["fields"]


def test_k_data_minute_has_time(provider):
    out = _ok(provider.get_history_k_data("sh.600519", "2024-01-02", "2024-01-03", "30"))
    assert "time" in out["fields"]


def test_profit(provider):
    out = _ok(provider.get_profit_data("sh.600519", "2023", "4"))
    assert out["count"] >= 1
    assert "roeAvg" in out["fields"]


def test_balance_and_dupont(provider):
    assert "liabilityToAsset" in _ok(provider.get_balance_data("sh.600519", "2023", "4"))["fields"]
    assert "dupontROE" in _ok(provider.get_dupont_data("sh.600519", "2023", "4"))["fields"]


def test_hs300(provider):
    assert _ok(provider.get_hs300_stocks())["count"] > 100


def test_trade_dates(provider):
    out = _ok(provider.get_trade_dates("2024-01-01", "2024-01-10"))
    assert out["count"] == 10
    assert "is_trading_day" in out["fields"]


def test_money_supply_month(provider):
    out = _ok(provider.get_money_supply_data_month("2023-01", "2023-06"))
    assert out["count"] > 0


def test_bare_code_normalized(provider):
    # 600519 -> sh.600519
    assert _ok(provider.get_stock_basic("600519"))["data"][0]["code"] == "sh.600519"
