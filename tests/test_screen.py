"""Tests for the value-hunt market screen (src/ashare_mcp/screen.py).

Network tests (marked) hit EastMoney's clist API live; pure tests cover the
classify / rank / run_screen logic and the _num parser with no network.
"""

import pytest

from ashare_mcp import screen


# ---------------------------------------------------------------------- #
# Task 1 — fetch_universe (network)
# ---------------------------------------------------------------------- #
@pytest.mark.network
def test_fetch_universe_returns_whole_cross_section():
    rows = screen.fetch_universe()
    assert isinstance(rows, list)
    assert len(rows) > 3000  # whole A-share market is ~5000+ names
    core = {"code", "name", "price", "pe", "pb", "mktcap_yi", "roe",
            "rev_yoy", "np_yoy", "eps", "bvps", "div_yield", "sector"}
    sample = rows[0]
    assert core.issubset(sample.keys())
    # codes are bare 6-digit strings
    assert all(isinstance(r["code"], str) and len(r["code"]) == 6 for r in rows[:50])
    # at least the big banks should be present and cheap (PE scaled /100)
    by_code = {r["code"]: r for r in rows}
    icbc = by_code.get("601398")
    assert icbc is not None
    assert icbc["pe"] is not None and 0 < icbc["pe"] < 20
