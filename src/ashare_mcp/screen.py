"""Value-hunt market screen (value-hunt Phase 1) over EastMoney's clist API.

A one-batch cross-section pull of the whole A-share market, then a pure-Python
hard-filter / anomaly-isolation / cyclical-aware classifier and a per-industry
composite ranker. Independent of the baostock provider (EastMoney HTTP, stdlib
urllib), mirroring ``announcements.py``.

EastMoney field codes (VERIFIED via live probe 2026-05-29):
  f12 code, f14 name, f2 price(*100), f9 PE-TTM(*100), f23 PB(*100),
  f20 总市值(元), f37 ROE(%), f41 营收同比(%), f46 净利同比(%), f112 EPS,
  f113 每股净资产(BVPS), f133 股息率(%), f100 一级行业, f221 报告期(YYYYMMDD).

SCALING (verified): f2/f9/f23 are integer-scaled by 100 (price 1326.00 -> 132600,
PE 15.21 -> 1521, PB 6.12 -> 612). f20 is raw 元 (-> /1e8 for 亿). f37/f41/f46/
f112/f113/f133 are already plain numbers.

ROE CALIBRATION (verified 2026-05-29): f37 is the LATEST CUMULATIVE (YTD) ROE for
the most recent report period — NOT a single quarter. Proven by EPS(f112)/BVPS(
f113) reproducing f37: 茅台 21.79/216.32 = 10.07% ≈ f37 10.57; 工行 0.2439/11.06 =
2.21% ≈ f37 2.21. Because it is *cumulative* over the period, an annualization
factor depends on how many months the period spans (Q1 YTD = 3mo -> x4, H1 = 6mo
-> x2, Q3 = 9mo -> x4/3, annual = 12mo -> x1).

ANNUALIZATION: each row carries its own report period in f221 (a YYYYMMDD report
date, e.g. 20260331 for a Q1 report). run_screen derives a per-row period-aware
factor via ``_annual_factor`` and multiplies the raw f37 by it BEFORE classify, so
classify compares an annualized ROE against the plain ANNUAL thresholds in
DEFAULTS directly. The raw per-period f37 is preserved under ``roe_q`` and the
annualized estimate under ``roe``. When f221 is absent/unreliable (==0) the factor
falls back to one inferred from today's calendar (see ``_annual_factor`` doc).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, datetime

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "Referer": "https://quote.eastmoney.com/"}

_CLIST_API = "https://push2delay.eastmoney.com/api/qt/clist/get"
# m:0+t:6 深主板, m:0+t:80 创业板, m:1+t:2 沪主板, m:1+t:23 科创板
_MARKET_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
_FIELDS = "f12,f14,f2,f9,f23,f20,f37,f41,f46,f112,f113,f133,f100,f221"


def _num(v) -> float | None:
    """Parse an EastMoney numeric cell to float, tolerating missing/'-'/None.

    EastMoney returns the string ``"-"`` (or omits the key) for unavailable
    metrics; both map to None so callers never crash on a missing field.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s in ("", "-", "--", "None"):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _scaled(v, factor: float) -> float | None:
    """_num(v) / factor, propagating None."""
    n = _num(v)
    return None if n is None else n / factor


# Months-of-period -> annualization factor (12 / months). f37 is a CUMULATIVE
# YTD ROE, so a Q1 (3-month) figure annualizes x4, H1 (6mo) x2, Q3 (9mo) x4/3,
# annual (12mo) x1.
_MONTHS_FACTOR = {3: 4.0, 6: 2.0, 9: 4.0 / 3.0, 12: 1.0}


def _annual_factor(report_period=None, today: date | None = None) -> float:
    """Factor to annualize a cumulative-YTD f37 ROE for a single report period.

    Preferred: pass ``report_period`` (the per-row f221) as a YYYYMMDD string/int
    (the period end-date, e.g. ``"20260630"`` -> H1 -> 2.0) or as an int
    month-of-period in {3,6,9,12}. The period's month determines the span:
    Q1->4.0, H1->2.0, Q3->4/3, annual->1.0.

    Fallback (no usable report_period): infer the period from ``today`` using the
    A-share mandatory-disclosure calendar (年报&一季报 by Apr 30; 半年报 by Aug 31;
    三季报 by Oct 31):
      May 1 – Aug 31 -> Q1 reflected -> 4.0
      Sep 1 – Oct 31 -> H1 reflected -> 2.0
      Nov 1 – Dec 31 -> Q3 reflected -> 4/3
      Jan 1 – Apr 30 -> transition (most names still prior-year Q3 until they file
                        the annual report) -> 1.0.
    The Jan–Apr branch deliberately assumes the *annual* report (factor 1.0) even
    though many names are still on Q3: deflating a still-Q3 name's ROE risks a
    FALSE NEGATIVE (it drops out of the screen), which is the safe failure mode
    for a conservative value screen — far better than inflating a value trap by
    a Q3 x4/3 and letting it in. Per-row f221 avoids this guess entirely when
    available, which is why it is preferred over the calendar fallback.
    """
    months = None
    if report_period is not None:
        n = _num(report_period)
        if n is not None and n > 0:
            n = int(n)
            if n in _MONTHS_FACTOR:          # already a month-of-period (3/6/9/12)
                months = n
            elif n >= 10000:                  # YYYYMMDD -> take the month
                months = (n // 100) % 100
    if months in _MONTHS_FACTOR:
        return _MONTHS_FACTOR[months]
    if months is not None:
        # Non-quarter-end month (unexpected); annualize by elapsed months, clamped.
        m = months if 1 <= months <= 12 else 12
        return 12.0 / m

    d = today or datetime.now().date()
    md = (d.month, d.day)
    if (5, 1) <= md <= (8, 31):
        return 4.0
    if (9, 1) <= md <= (10, 31):
        return 2.0
    if (11, 1) <= md <= (12, 31):
        return 4.0 / 3.0
    # Jan 1 – Apr 30 transition window: assume annual already filed (see docstring).
    return 1.0


def _map_row(d: dict) -> dict | None:
    """Map one EastMoney clist record into a screen row dict, or None if it has
    no usable code (defensive against malformed rows)."""
    code = d.get("f12")
    if not code or not isinstance(code, str):
        return None
    return {
        "code": code,
        "name": (d.get("f14") or "").strip(),
        "price": _scaled(d.get("f2"), 100.0),
        "pe": _scaled(d.get("f9"), 100.0),
        "pb": _scaled(d.get("f23"), 100.0),
        "mktcap_yi": _scaled(d.get("f20"), 1e8),
        "roe": _num(d.get("f37")),
        "rev_yoy": _num(d.get("f41")),
        "np_yoy": _num(d.get("f46")),
        # eps (f112) and bvps (f113) are surfaced for downstream human /
        # deep-analysis inspection only — they feed no filter and no score.
        "eps": _num(d.get("f112")),
        "bvps": _num(d.get("f113")),
        "div_yield": _num(d.get("f133")),
        "sector": (d.get("f100") or "").strip(),
        # f221 报告期 (YYYYMMDD report date, e.g. 20260331); 0/absent if unknown.
        # Drives the per-row period-aware ROE annualization in run_screen.
        "report_period": _num(d.get("f221")),
    }


def _get_json(url: str, timeout: float = 20.0) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw)


def fetch_universe(page_size: int = 100, max_pages: int = 100) -> list[dict]:
    """Pull the whole A-share cross-section in one batch, paginating pn 1.. .

    Returns a list of row dicts with keys: code, name, price, pe, pb,
    mktcap_yi, roe, rev_yoy, np_yoy, eps, bvps, div_yield, sector. Values are
    floats or None (never raises on a missing/"-"/None field).
    """
    rows: list[dict] = []
    page = 1
    while page <= max_pages:
        qs = urllib.parse.urlencode({
            "pn": page,
            "pz": page_size,
            "po": 1,
            "fid": "f3",
            "fs": _MARKET_FS,
            "fields": _FIELDS,
        }, safe="+:,")
        data = (_get_json(f"{_CLIST_API}?{qs}") or {}).get("data") or {}
        diff = data.get("diff")
        if not diff:
            break
        # diff is a dict keyed "0","1",... (or occasionally a list)
        items = diff.values() if isinstance(diff, dict) else diff
        added = 0
        for it in items:
            if not isinstance(it, dict):
                continue
            row = _map_row(it)
            if row is not None:
                rows.append(row)
                added += 1
        if added == 0:
            break
        total = data.get("total")
        if isinstance(total, int) and len(rows) >= total:
            break
        page += 1
    return rows


# ====================================================================== #
# Task 2 — classify
# ====================================================================== #
# All thresholds are expressed in ANNUAL terms (roe_min=7 means 7% annual ROE).
# f37 is a cumulative-YTD ROE, so run_screen annualizes a row's roe by a
# period-aware factor (_annual_factor) BEFORE calling classify — classify then
# compares the annualized ROE against these plain annual numbers directly. This
# keeps classify a pure function of (row, params) with no hidden period coupling.
DEFAULTS: dict = {
    # hard filter
    "min_price": 3.0,           # 剔除仙股
    "min_mktcap_yi": 50.0,      # 总市值下限(亿)
    # non-cyclical valuation band
    "pe_min": 4.0,
    "pe_max": 25.0,
    "pb_max": 2.5,              # PB cap when roe < highroe
    "pb_max_highroe": 3.0,      # PB cap when roe >= highroe
    "highroe": 12.0,            # 高ROE门槛(年化)
    # ROE floors (年化)
    "roe_min": 7.0,             # 主仓 ROE 下限
    "roe_min_lo": 5.0,          # 低ROE救援区下限
    "div_for_lo_roe": 3.5,      # 低ROE救援所需股息率
    "pe_for_lo_roe": 12.0,      # 低ROE救援所需 PE 上限
    # anomaly isolation
    "anom_pb": 0.4,             # 破净异常阈值
    "anom_np_yoy": 300.0,       # 业绩暴增阈值(%)
    "anom_np_pe": 10.0,         # 业绩暴增需配合的低 PE
    "anom_div": 10.0,           # 超高股息异常阈值(%)
    # cyclical sectors
    "cyc_pb_max": 1.2,
    "cyc_div_min": 3.5,
    "cyc_pe_min": 4.0,
    "cyc_pe_max": 15.0,
    # ranking caps
    "per_industry_cap": 8,
    "total_cap": 120,
}

# 强周期一级行业(子串匹配 EastMoney f100 一级行业名)。
# 注:"航运" 子串已覆盖东财长名 "航运港口",故不单列后者(避免冗余匹配项)。
CYCLICAL_SECTORS = (
    "钢铁", "煤炭", "有色", "化工", "建材", "石油石化", "航运",
)

# 剔除名(ST/退市风险)子串
_BLACKLIST_NAME = ("ST", "退")


def _is_cyclical(sector: str) -> bool:
    s = sector or ""
    return any(k in s for k in CYCLICAL_SECTORS)


def classify(row: dict, params: dict) -> str:
    """Bucket one row into 'main' | 'anomaly' | 'reject' (pure, no network).

    ``row['roe']`` is expected in ANNUAL terms (run_screen annualizes the
    quarterly f37 before calling this). Order: hard filter -> anomaly isolation
    -> cyclical rules -> non-cyclical rules.
    """
    p = params
    name = row.get("name") or ""
    pe = row.get("pe")
    pb = row.get("pb")
    price = row.get("price")
    mktcap = row.get("mktcap_yi")
    roe = row.get("roe")
    div = row.get("div_yield")
    np_yoy = row.get("np_yoy")
    sector = row.get("sector") or ""

    # --- hard filter ---------------------------------------------------
    if any(b in name for b in _BLACKLIST_NAME):
        return "reject"
    if pe is None or pb is None:
        return "reject"
    if price is None or price < p["min_price"]:
        return "reject"
    if mktcap is None or mktcap < p["min_mktcap_yi"]:
        return "reject"

    # --- anomaly isolation (pull odd shapes out before normal scoring) -
    if (0 < pe < p["pe_min"]):
        return "anomaly"
    if pb < p["anom_pb"]:
        return "anomaly"
    if (np_yoy is not None and np_yoy > p["anom_np_yoy"] and pe < p["anom_np_pe"]):
        return "anomaly"
    if (div is not None and div > p["anom_div"]):
        return "anomaly"

    # --- cyclical sectors: no ROE floor, but strict pb/div/pe gates -----
    if _is_cyclical(sector):
        if (pb <= p["cyc_pb_max"]
                and div is not None and div >= p["cyc_div_min"]
                and p["cyc_pe_min"] <= pe <= p["cyc_pe_max"]):
            return "main"
        return "reject"

    # --- non-cyclical: valuation band + ROE-aware pb cap + ROE floor ----
    if not (p["pe_min"] <= pe <= p["pe_max"]):
        return "reject"
    if roe is None:
        return "reject"
    pb_cap = p["pb_max_highroe"] if roe >= p["highroe"] else p["pb_max"]
    if pb > pb_cap:
        return "reject"
    if roe >= p["roe_min"]:
        return "main"
    if (p["roe_min_lo"] <= roe < p["roe_min"]
            and div is not None and div >= p["div_for_lo_roe"]
            and pe <= p["pe_for_lo_roe"]):
        return "main"
    return "reject"


# ====================================================================== #
# Task 3 — rank_candidates
# ====================================================================== #
def _pctrank(value, values: list[float]) -> float:
    """Percentile rank of ``value`` within ``values`` in [0, 1] (bigger value ->
    bigger rank). ``None`` (missing metric) -> 0.5 neutral so it neither helps
    nor hurts. Empty/degenerate population -> 0.5."""
    if value is None:
        return 0.5
    pool = [v for v in values if v is not None]
    if not pool:
        return 0.5
    lo = min(pool)
    hi = max(pool)
    if hi == lo:
        return 0.5
    # rank-based percentile: count strictly below / (n-1) -> min maps to 0,
    # max maps to 1, ties share the same rank.
    n_below = sum(1 for v in pool if v < value)
    return n_below / (len(pool) - 1)


def _inv(x):
    """1/x for positive x; None for None/non-positive (cheaper -> larger)."""
    if x is None or x <= 0:
        return None
    return 1.0 / x


def _score_sector(rows: list[dict]) -> None:
    """Compute and attach a composite ``score`` (0..100) to each row, ranked
    within this sector group. Higher is cheaper/better."""
    inv_pe = [_inv(r.get("pe")) for r in rows]
    inv_pb = [_inv(r.get("pb")) for r in rows]
    roe = [r.get("roe") for r in rows]
    div = [min(r.get("div_yield"), 8.0) if r.get("div_yield") is not None else None
           for r in rows]
    rev = [r.get("rev_yoy") for r in rows]
    for i, r in enumerate(rows):
        cheap = (_pctrank(inv_pe[i], inv_pe) + _pctrank(inv_pb[i], inv_pb)) / 2.0
        r["score"] = 100.0 * (
            0.50 * cheap
            + 0.25 * _pctrank(roe[i], roe)
            + 0.15 * _pctrank(div[i], div)
            + 0.10 * _pctrank(rev[i], rev)
        )


def rank_candidates(rows: list[dict], params: dict) -> list[dict]:
    """Score, per-industry-cap, then globally truncate the main candidates.

    Groups rows by ``sector``; within each sector computes a composite cheapness/
    quality/yield/growth score; keeps the top ``per_industry_cap`` per sector;
    then globally sorts by score desc and truncates to ``total_cap``.
    """
    p = params
    # Coerce caps to int: run_screen does not coerce overrides, and a float cap
    # passed via a direct Python call would raise on list slicing.
    per_industry_cap = int(p["per_industry_cap"])
    total_cap = int(p["total_cap"])
    by_sector: dict[str, list[dict]] = {}
    for r in rows:
        by_sector.setdefault(r.get("sector") or "", []).append(r)

    kept: list[dict] = []
    for sector_rows in by_sector.values():
        _score_sector(sector_rows)
        sector_rows.sort(key=lambda r: r["score"], reverse=True)
        kept.extend(sector_rows[:per_industry_cap])

    kept.sort(key=lambda r: r["score"], reverse=True)
    return kept[:total_cap]


# ====================================================================== #
# Task 4 — run_screen (orchestration)
# ====================================================================== #
def _annualize_roe(row: dict, today: date | None = None) -> dict:
    """Return a shallow copy of ``row`` with ``roe`` converted from the raw
    cumulative-YTD f37 to an annual-equivalent, so it can be compared against the
    annual thresholds in DEFAULTS.

    The factor is period-aware (``_annual_factor``): preferred from the row's own
    ``report_period`` (f221); when that is absent/0 it falls back to a factor
    inferred from ``today`` (default: now). The raw per-period figure is preserved
    under ``roe_q`` for transparency; the annualized estimate is ``roe``.
    """
    out = dict(row)
    q = row.get("roe")
    out["roe_q"] = q
    if q is not None:
        factor = _annual_factor(report_period=row.get("report_period"), today=today)
        out["roe"] = q * factor
    return out


def run_screen(**overrides) -> dict:
    """Run the full value-hunt screen over the live A-share cross-section.

    Pulls the universe, hard-filters / isolates anomalies / ranks the main
    candidates. ``overrides`` are merged over DEFAULTS (None values dropped).
    Returns {candidates, anomaly_pool, params, main_count, anomaly_count}.
    """
    params = dict(DEFAULTS)
    params.update({k: v for k, v in overrides.items() if v is not None})

    rows = [_annualize_roe(r) for r in fetch_universe()]

    main_rows: list[dict] = []
    anomaly_pool: list[dict] = []
    for r in rows:
        bucket = classify(r, params)
        if bucket == "main":
            main_rows.append(r)
        elif bucket == "anomaly":
            anomaly_pool.append(r)

    candidates = rank_candidates(main_rows, params)
    # Each candidate / anomaly dict carries:
    #   RAW (from EastMoney): code, name, price, pe, pb, mktcap_yi, rev_yoy,
    #     np_yoy, eps, bvps, div_yield, sector, report_period, roe_q (原始单期/YTD f37).
    #   DERIVED (computed here): roe (年化估计 = roe_q × _annual_factor),
    #     score (0..100 composite, candidates only).
    return {
        "candidates": candidates,
        "anomaly_pool": anomaly_pool,
        "params": params,
        "main_count": len(main_rows),
        "anomaly_count": len(anomaly_pool),
    }
