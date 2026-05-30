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
