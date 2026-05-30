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


# ---------------------------------------------------------------------- #
# _num — robustness (pure)
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    (15.21, 15.21),
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
    assert screen._num(raw) == expected


def test_map_row_handles_missing_fields_as_none():
    # Only a code present; every other metric absent or "-" -> None, no crash.
    row = screen._map_row({"f12": "600000", "f9": "-", "f23": None})
    assert row["code"] == "600000"
    assert row["pe"] is None and row["pb"] is None and row["roe"] is None
    assert row["name"] == "" and row["sector"] == ""


def test_map_row_scales_price_pe_pb_and_mktcap():
    row = screen._map_row({
        "f12": "600519", "f14": "贵州茅台", "f2": 132600, "f9": 1521,
        "f23": 612, "f20": 1657608202926, "f37": 10.57, "f133": 3.92,
        "f100": "白酒",
    })
    assert row["price"] == 1326.0
    assert row["pe"] == 15.21
    assert row["pb"] == 6.12
    assert round(row["mktcap_yi"], 0) == 16576.0
    assert row["roe"] == 10.57  # raw quarterly f37 stored verbatim


# ---------------------------------------------------------------------- #
# Task 2 — classify (pure). ROE values here are in ANNUAL frame, the same
# frame as the DEFAULTS thresholds; run_screen annualizes the quarterly f37
# before classify sees it (see ROE_IS_QUARTERLY handling).
# ---------------------------------------------------------------------- #
def _row(**kw):
    base = dict(code="000000", name="测试", price=10.0, pe=10.0, pb=1.5,
                mktcap_yi=100.0, roe=12.0, rev_yoy=5.0, np_yoy=8.0,
                eps=1.0, bvps=5.0, div_yield=2.0, sector="计算机")
    base.update(kw)
    return base


P = screen.DEFAULTS


def test_classify_noncyclical_quality_is_main():
    # PE 12, PB 1.5, ROE 15 -> comfortably in the main universe.
    assert screen.classify(_row(pe=12.0, pb=1.5, roe=15.0), P) == "main"


def test_classify_rejects_st_name():
    assert screen.classify(_row(name="ST康美", pe=10, pb=1.0, roe=12), P) == "reject"
    assert screen.classify(_row(name="退市某某", pe=10, pb=1.0, roe=12), P) == "reject"


def test_classify_rejects_missing_pe_or_pb():
    assert screen.classify(_row(pe=None), P) == "reject"
    assert screen.classify(_row(pb=None), P) == "reject"


def test_classify_rejects_below_price_or_mktcap_floor():
    assert screen.classify(_row(price=1.5), P) == "reject"
    assert screen.classify(_row(mktcap_yi=10.0), P) == "reject"


def test_classify_value_trap_utility_rejects():
    # 深圳能源-style value trap: pe18 within band, pb1.08 under cap, but ROE 4.3
    # (annual) is below the 5 hard-floor with no rescue -> reject.
    row = _row(name="深圳能源", pe=18.0, pb=1.08, roe=4.3, div_yield=2.0,
               sector="电力")
    assert screen.classify(row, P) == "reject"


def test_classify_low_roe_rescued_by_dividend_is_main():
    # 5 <= roe < 7 but div>=3.5 and pe<=12 -> rescued into main.
    row = _row(pe=11.0, pb=1.2, roe=6.0, div_yield=4.0, sector="食品饮料")
    assert screen.classify(row, P) == "main"


def test_classify_cyclical_ok_is_main():
    # 钢铁: no ROE floor; pb<=1.2, div>=3.5, 4<=pe<=15.
    row = _row(name="某钢铁", sector="钢铁", pe=8.0, pb=1.0, roe=3.0,
               div_yield=4.5)
    assert screen.classify(row, P) == "main"


def test_classify_cyclical_violation_rejects():
    # 煤炭 but pb too high / div too low -> reject (no ROE rescue for cyclicals).
    assert screen.classify(_row(sector="煤炭", pe=8, pb=1.5, roe=15,
                                div_yield=4.0), P) == "reject"
    assert screen.classify(_row(sector="有色", pe=8, pb=1.0, roe=15,
                                div_yield=2.0), P) == "reject"


def test_classify_anomaly_ultra_low_pe():
    # 0<pe<pe_min isolates as anomaly rather than reject.
    assert screen.classify(_row(pe=1.1, pb=0.9, roe=12), P) == "anomaly"


def test_classify_anomaly_distressed_pb():
    assert screen.classify(_row(pe=10, pb=0.3, roe=8), P) == "anomaly"


def test_classify_anomaly_turnaround_and_huge_yield():
    assert screen.classify(_row(pe=8, pb=1.0, np_yoy=400, roe=10), P) == "anomaly"
    assert screen.classify(_row(pe=10, pb=1.0, div_yield=12.0, roe=10), P) == "anomaly"


def test_classify_noncyclical_pb_cap_depends_on_roe():
    # roe<12 -> pb cap 2.5: pb 2.8 rejects.
    assert screen.classify(_row(pe=15, pb=2.8, roe=10), P) == "reject"
    # roe>=12 -> pb cap 3.0: pb 2.8 OK.
    assert screen.classify(_row(pe=15, pb=2.8, roe=14), P) == "main"


# ---------------------------------------------------------------------- #
# Task 3 — rank_candidates (pure)
# ---------------------------------------------------------------------- #
def test_percentile_helper_basics():
    vals = [1.0, 2.0, 3.0, 4.0]
    assert screen._pctrank(4.0, vals) == 1.0   # max -> 1
    assert screen._pctrank(1.0, vals) == 0.0   # min -> 0
    assert screen._pctrank(None, vals) == 0.5  # missing -> neutral


def test_rank_caps_sector_to_eight_and_sorts_desc():
    # 12 same-sector main rows, identical except PE -> cheaper should win.
    rows = []
    for i in range(12):
        rows.append(_row(code=f"{600000 + i}", sector="计算机",
                         pe=5.0 + i, pb=1.5, roe=12.0, div_yield=2.0,
                         rev_yoy=5.0))
    out = screen.rank_candidates(rows, P)
    assert len(out) <= P["per_industry_cap"] == 8
    scores = [c["score"] for c in out]
    assert scores == sorted(scores, reverse=True)
    # cheapest PE (lowest pe) should be the top-ranked survivor.
    assert out[0]["pe"] == 5.0


def test_rank_cheaper_scores_higher_all_else_equal():
    a = _row(code="000001", sector="银行", pe=6.0, pb=1.0, roe=12.0,
             div_yield=4.0, rev_yoy=5.0)
    b = _row(code="000002", sector="银行", pe=12.0, pb=1.0, roe=12.0,
             div_yield=4.0, rev_yoy=5.0)
    out = screen.rank_candidates([a, b], P)
    by_code = {c["code"]: c for c in out}
    assert by_code["000001"]["score"] > by_code["000002"]["score"]


def test_rank_truncates_total_cap():
    # Many sectors, many rows -> global truncation to total_cap.
    rows = []
    for s in range(40):
        for i in range(10):
            rows.append(_row(code=f"{500000 + s*100 + i}", sector=f"行业{s}",
                             pe=5.0 + i, pb=1.2, roe=12.0, div_yield=3.0,
                             rev_yoy=4.0))
    out = screen.rank_candidates(rows, P)
    # 40 sectors * min(10,8)=8 = 320 pre-truncation -> capped at total_cap.
    assert len(out) == P["total_cap"] == 120
    scores = [c["score"] for c in out]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------- #
# Task 4 — run_screen (pure, fetch_universe monkeypatched)
# ---------------------------------------------------------------------- #
def test_run_screen_splits_main_and_anomaly(monkeypatch):
    # roe here is RAW QUARTERLY f37 (run_screen annualizes x4 before classify).
    fake = [
        # main: annual roe 12, in band, big enough
        _row(code="600001", name="优质龙头", sector="计算机", pe=10.0,
             pb=1.2, roe=3.0, div_yield=2.0, price=10.0, mktcap_yi=100.0),
        # anomaly: ultra-low PE
        _row(code="600002", name="超低市盈", sector="机械", pe=1.1,
             pb=0.9, roe=3.0, div_yield=1.0, price=8.0, mktcap_yi=80.0),
        # reject: ST name
        _row(code="600003", name="ST困境", sector="计算机", pe=10.0,
             pb=1.0, roe=3.0, div_yield=2.0, price=6.0, mktcap_yi=60.0),
        # anomaly: 超高股息
        _row(code="600004", name="高股息", sector="银行", pe=8.0,
             pb=1.0, roe=3.0, div_yield=12.0, price=5.0, mktcap_yi=200.0),
    ]
    monkeypatch.setattr(screen, "fetch_universe", lambda *a, **k: list(fake))
    out = screen.run_screen()
    assert out["main_count"] == 1
    assert out["anomaly_count"] == 2
    assert len(out["candidates"]) == 1
    assert out["candidates"][0]["code"] == "600001"
    assert len(out["anomaly_pool"]) == 2
    anom_codes = {r["code"] for r in out["anomaly_pool"]}
    assert anom_codes == {"600002", "600004"}
    # params echo includes overridable defaults
    assert out["params"]["roe_min"] == screen.DEFAULTS["roe_min"]
    # every surviving candidate carries a score
    assert "score" in out["candidates"][0]


def test_run_screen_overrides_drop_none_and_merge(monkeypatch):
    monkeypatch.setattr(screen, "fetch_universe", lambda *a, **k: [])
    out = screen.run_screen(roe_min=9, pe_max=None, min_mktcap_yi=80)
    # explicit override applied
    assert out["params"]["roe_min"] == 9
    assert out["params"]["min_mktcap_yi"] == 80
    # None override dropped -> default retained
    assert out["params"]["pe_max"] == screen.DEFAULTS["pe_max"]
    assert out["main_count"] == 0 and out["anomaly_count"] == 0
    assert out["candidates"] == [] and out["anomaly_pool"] == []
