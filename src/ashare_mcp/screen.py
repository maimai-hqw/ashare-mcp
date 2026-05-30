"""Value-hunt market screen (value-hunt Phase 1) over EastMoney's clist API.

A one-batch cross-section pull of the whole A-share market, then a pure-Python
hard-filter / anomaly-isolation / cyclical-aware classifier and a per-industry
composite ranker. Independent of the baostock provider (EastMoney HTTP, stdlib
urllib), mirroring ``announcements.py``.

EastMoney field codes (VERIFIED via live probe 2026-05-29):
  f12 code, f14 name, f2 price(*100), f9 PE-TTM(*100), f23 PB(*100),
  f20 总市值(元), f37 ROE(%), f41 营收同比(%), f46 净利同比(%), f112 EPS,
  f113 每股净资产(BVPS), f133 股息率(%), f100 一级行业.

SCALING (verified): f2/f9/f23 are integer-scaled by 100 (price 1326.00 -> 132600,
PE 15.21 -> 1521, PB 6.12 -> 612). f20 is raw 元 (-> /1e8 for 亿). f37/f41/f46/
f112/f113/f133 are already plain numbers.

ROE CALIBRATION (verified 2026-05-29): f37 is the LATEST SINGLE-QUARTER ROE, not
annual/TTM. Big banks printed f37 ~2.2-3.4 (工行 2.21, 招行 3.37, 农行 2.65) whose
*annual* ROE is ~10-14%; 贵州茅台 printed 10.57 vs ~30%+ annual. So f37 ≈ annual/4.
=> ROE_IS_QUARTERLY = True, and every ROE threshold below (expressed as an annual
figure for readability) is divided by 4 (``_roe_floor``) before comparing to f37.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "Referer": "https://quote.eastmoney.com/"}

_CLIST_API = "https://push2delay.eastmoney.com/api/qt/clist/get"
# m:0+t:6 深主板, m:0+t:80 创业板, m:1+t:2 沪主板, m:1+t:23 科创板
_MARKET_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
_FIELDS = "f12,f14,f2,f9,f23,f20,f37,f41,f46,f112,f113,f133,f100"

# f37 is a quarterly ROE (see module docstring). Annual ROE thresholds in
# DEFAULTS are divided by 4 before comparing to f37.
ROE_IS_QUARTERLY = True


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
        "eps": _num(d.get("f112")),
        "bvps": _num(d.get("f113")),
        "div_yield": _num(d.get("f133")),
        "sector": (d.get("f100") or "").strip(),
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
# Because f37 is a quarterly ROE (ROE_IS_QUARTERLY), run_screen annualizes a
# row's roe (x4) BEFORE calling classify, so classify can compare against these
# annual numbers directly. This keeps classify a pure function of (row, params)
# with no hidden quarter/year coupling and makes the unit vectors read naturally.
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

# 强周期一级行业(子串匹配 EastMoney f100 一级行业名)
CYCLICAL_SECTORS = (
    "钢铁", "煤炭", "有色", "化工", "建材", "石油石化", "航运", "航运港口",
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
    by_sector: dict[str, list[dict]] = {}
    for r in rows:
        by_sector.setdefault(r.get("sector") or "", []).append(r)

    kept: list[dict] = []
    for sector_rows in by_sector.values():
        _score_sector(sector_rows)
        sector_rows.sort(key=lambda r: r["score"], reverse=True)
        kept.extend(sector_rows[: p["per_industry_cap"]])

    kept.sort(key=lambda r: r["score"], reverse=True)
    return kept[: p["total_cap"]]
