"""Batch realtime-snapshot quotes via EastMoney / Tencent HTTP APIs.

This is independent of the baostock provider — baostock's ``get_history_k_data``
is per-code, EOD-only, and routinely unreachable (port 10030 / error 10002007)
from non-CN networks. This module provides a BATCH current-price snapshot for a
whole watchlist in ONE HTTP call, so it works even when baostock is down.

Two backends, both reachable from non-CN networks (stdlib urllib, no new deps,
mirroring ``announcements.py`` / ``screen.py``):

  * PRIMARY  — EastMoney push2delay ``ulist.np`` (the same reachable host
               ``screen.py`` already uses), one call for all secids.
  * FALLBACK — Tencent ``qt.gtimg.cn`` (proven reachable from US), GBK-encoded,
               one call for all codes.

Fallback is a PER-CODE merge, not all-or-nothing: any code EastMoney did not
price (never returned, or returned halted with price=None) is filled from
Tencent. ``source`` is ``eastmoney`` / ``tencent`` / ``eastmoney+tencent`` per
which backend(s) actually carried data.

SCALING (LIVE-PROBED 2026-05-29/30): unlike ``screen.py``'s clist call, this
ulist call passes ``fltt=2`` and EastMoney then returns f2/f3/f9/f23/... as
ALREADY-DECIMAL floats (price 5.13, PE 7.45, PB 0.82, pct_chg 2.19) — NOT the
integer ×100 form clist uses. So NO /100 here. f20 总市值 is raw 元 (-> /1e8 for
亿). ``"-"``/missing -> None.

TENCENT FIELD INDICES (LIVE-VERIFIED 2026-05-29/30 against EastMoney for 上港集团
/ 贵州茅台 / 乖宝宠物 — split the inner string by ``~``):
  [1] name, [3] price, [4] prev_close, [5] open, [6] volume(手), [30] time,
  [31] change, [32] pct_chg(%), [33] high, [34] low, [37] amount(万元),
  [38] turnover(%), [45] 总市值(亿), [46] PB, [52] PE(TTM, matches EM f9 exactly).
Tencent amount is 万元 so it is ×1e4'd to match EastMoney's 元. Tencent index
[39] is a DIFFERENT (动态) PE and is deliberately NOT used; [52] is the TTM PE
that reconciles with EastMoney. PB[46] reconciles to ~2 decimals (minor period/
rounding drift vs EM f23) and is mapped as best-effort.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
# EastMoney quote host wants the quote referer (mirrors screen.py).
_HEADERS = {"User-Agent": _UA, "Referer": "https://quote.eastmoney.com/"}
# Tencent gu.qq.com referer.
_TENCENT_HEADERS = {"User-Agent": _UA, "Referer": "https://gu.qq.com/"}

_EM_API = "https://push2delay.eastmoney.com/api/qt/ulist.np/get"
# f124 is the per-row update unix timestamp (seconds) — surfaced as `as_of`.
_EM_FIELDS = "f12,f13,f14,f2,f3,f4,f15,f16,f17,f18,f5,f6,f8,f9,f23,f20,f124"
_TENCENT_API = "http://qt.gtimg.cn/q="

_PREFIXED = re.compile(r"^(sh|sz|bj)\.?(\d{6})$")
_BARE = re.compile(r"^(\d{6})$")


# ---------------------------------------------------------------------- #
# Numeric parsing (mirrors screen.py)
# ---------------------------------------------------------------------- #
def _num(v) -> float | None:
    """Parse a feed numeric cell to float, tolerating missing/'-'/''/None.

    Both EastMoney and Tencent emit ``"-"`` / ``""`` (or omit the key) for an
    unavailable metric (halted stock, missing PE/PB); all map to None so callers
    never crash on a missing field.
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


def _pos(v) -> float | None:
    """Parse a PRICE-like cell, mapping a non-positive value (0 / negative) to
    None. A halted/suspended stock often reports a 0.0 price (and 0.0 OHLC) on
    both feeds; surfacing that as 0.0 is dangerous — it could falsely trip a
    stop-loss / add-zone trigger downstream. Map any price <= 0 to None so a
    halted name is unambiguously 'no price', never a fake 0.
    """
    n = _num(v)
    return None if (n is None or n <= 0.0) else n


# ---------------------------------------------------------------------- #
# Code normalization (pure)
# ---------------------------------------------------------------------- #
def _norm(code: str) -> str:
    """Canonicalize one A-share code to ``sh.600018`` form.

    Accepts ``sh.600018`` / ``sz.301498`` / ``bj.430047`` / ``sh600018`` /
    bare ``600018``. For a bare 6-digit code the market is inferred from the
    leading digit(s): ``6``->sh, ``0``/``3``->sz, ``4``/``8``/``9``->bj.
    Raises ``ValueError`` on un-parseable input.
    """
    if not code or not str(code).strip():
        raise ValueError("证券代码不能为空")
    c = re.sub(r"\s+", "", str(code)).lower()

    m = _PREFIXED.match(c)
    if m:
        return f"{m.group(1)}.{m.group(2)}"

    b = _BARE.match(c)
    if not b:
        raise ValueError(
            f"无法识别的证券代码: {code!r}。请使用 sh.600018 / sz.301498 / bj.430047 / 纯6位 形式"
        )
    num = b.group(1)
    return f"{_infer_market(num)}.{num}"


def _infer_market(num: str) -> str:
    """Infer sh/sz/bj from a bare 6-digit code's leading digit(s)."""
    head = num[0]
    if head == "6":
        return "sh"
    if head in ("0", "3"):
        return "sz"
    if head in ("4", "8", "9"):
        return "bj"
    raise ValueError(
        f"无法推断交易所前缀: {num!r}。请显式指定 sh./sz./bj. 前缀"
    )


def _eastmoney_secid(code: str) -> str:
    """``sh.600018`` -> ``1.600018`` (EastMoney secid). SH market=1; SZ and BJ
    market=0 (verified live: bj.430047 resolves under market 0 on this ulist API,
    matching the common EM convention of 0 for the Beijing/Shenzhen number space).
    """
    market, num = code.split(".", 1)
    em_market = "1" if market == "sh" else "0"
    return f"{em_market}.{num}"


def _tencent_code(code: str) -> str:
    """``sh.600018`` -> ``sh600018`` (Tencent qt.gtimg.cn code)."""
    market, num = code.split(".", 1)
    return f"{market}{num}"


# ---------------------------------------------------------------------- #
# HTTP
# ---------------------------------------------------------------------- #
def _get_json(url: str, timeout: float = 20.0) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw)


def _get_text_gbk(url: str, timeout: float = 20.0) -> str:
    req = urllib.request.Request(url, headers=_TENCENT_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("gbk", "replace")


# ---------------------------------------------------------------------- #
# EastMoney backend (primary)
# ---------------------------------------------------------------------- #
def _em_market_prefix(f13) -> str:
    """EastMoney f13 market flag -> 'sh' / 'sz' / 'bj'. f13==1 is Shanghai; 0 is
    the Shenzhen/Beijing number space — disambiguate Beijing by the BJ code
    blocks (4xx/8xx/9xx) so the canonical code's prefix is correct."""
    return "sh" if _num(f13) == 1.0 else "sz"


def _em_canonical(num: str, f13) -> str:
    """Build the canonical ``sh./sz./bj.NNNNNN`` code from EastMoney's f12 number
    + f13 market flag, recovering Beijing from the number block (EM reports BJ
    under market 0, same as SZ)."""
    if _num(f13) == 1.0:
        return f"sh.{num}"
    # market 0: SZ vs BJ — infer from the number block.
    if num[0] in ("4", "8", "9"):
        return f"bj.{num}"
    return f"sz.{num}"


def _parse_eastmoney(obj: dict) -> tuple[list[dict], str]:
    """Map an EastMoney ulist response into (rows, as_of). Each row is the
    normalized schema. Tolerant of missing fields / halted stocks."""
    data = (obj or {}).get("data") or {}
    diff = data.get("diff")
    if not diff:
        return [], ""
    items = diff.values() if isinstance(diff, dict) else diff
    rows: list[dict] = []
    as_of = ""
    for it in items:
        if not isinstance(it, dict):
            continue
        num = it.get("f12")
        if not num or not isinstance(num, str):
            continue
        ts = _num(it.get("f124"))  # update unix timestamp (seconds)
        if ts and not as_of:
            try:
                as_of = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except (OverflowError, OSError, ValueError):
                as_of = ""
        # fltt=2 -> already decimal; NO /100 (see module docstring). A halted
        # stock reports 0.0 prices -> _pos maps non-positive to None.
        price = _pos(it.get("f2"))
        rows.append({
            "code": _em_canonical(num, it.get("f13")),
            "name": (it.get("f14") or "").strip(),
            "price": price,
            "prev_close": _pos(it.get("f18")),
            "open": _pos(it.get("f17")),
            "high": _pos(it.get("f15")),
            "low": _pos(it.get("f16")),
            "pct_chg": _num(it.get("f3")),
            "volume": _num(it.get("f5")),
            "amount": _num(it.get("f6")),
            "pe_ttm": _num(it.get("f9")),
            "pb": _num(it.get("f23")),
            "mktcap_yi": _scaled(it.get("f20"), 1e8),
            "turnover": _num(it.get("f8")),
            "halted": price is None,
        })
    return rows, as_of


def _fetch_eastmoney(canon_codes: list[str]) -> tuple[list[dict], str]:
    """One batch call to EastMoney ulist for all codes. Returns (rows, as_of)."""
    secids = ",".join(_eastmoney_secid(c) for c in canon_codes)
    qs = urllib.parse.urlencode(
        {"fltt": 2, "secids": secids, "fields": _EM_FIELDS}, safe="+:,."
    )
    obj = _get_json(f"{_EM_API}?{qs}")
    return _parse_eastmoney(obj)


# ---------------------------------------------------------------------- #
# Tencent backend (fallback)
# ---------------------------------------------------------------------- #
def _parse_tencent(text: str) -> tuple[list[dict], str]:
    """Map a Tencent qt.gtimg.cn response into (rows, as_of). Indices are
    live-verified (see module docstring). Tolerant of halted/empty rows."""
    rows: list[dict] = []
    as_of = ""
    for line in text.split(";"):
        line = line.strip()
        if not line.startswith("v_") or "=" not in line:
            continue
        # v_sh600018="1~上港集团~600018~...";  -> grab inner quoted payload
        try:
            inner = line.split('"', 2)[1]
        except IndexError:
            continue
        parts = inner.split("~")
        if len(parts) < 7:
            continue

        def at(i: int):
            return parts[i] if i < len(parts) else None

        # Recover the canonical code from the v_<tencentcode> key.
        key = line.split("=", 1)[0][2:]  # drop "v_"
        m = re.match(r"^(sh|sz|bj)(\d{6})$", key)
        code = f"{m.group(1)}.{m.group(2)}" if m else key
        # Halted stock reports 0.00 prices -> _pos maps non-positive to None.
        price = _pos(at(3))
        ts = (at(30) or "").strip()
        if ts and not as_of:
            as_of = ts
        amount_wan = _num(at(37))  # Tencent 成交额 in 万元
        rows.append({
            "code": code,
            "name": (at(1) or "").strip(),
            "price": price,
            "prev_close": _pos(at(4)),
            "open": _pos(at(5)),
            "high": _pos(at(33)),
            "low": _pos(at(34)),
            "pct_chg": _num(at(32)),
            "volume": _num(at(6)),
            # 万元 -> 元 to match EastMoney's amount unit.
            "amount": None if amount_wan is None else amount_wan * 1e4,
            "pe_ttm": _num(at(52)),
            "pb": _num(at(46)),
            "mktcap_yi": _num(at(45)),
            "turnover": _num(at(38)),
            "halted": price is None,
        })
    return rows, as_of


def _fetch_tencent(canon_codes: list[str]) -> tuple[list[dict], str]:
    """One batch call to Tencent qt.gtimg.cn for all codes. Returns (rows, as_of)."""
    query = ",".join(_tencent_code(c) for c in canon_codes)
    text = _get_text_gbk(f"{_TENCENT_API}{query}")
    return _parse_tencent(text)


# ---------------------------------------------------------------------- #
# Orchestration
# ---------------------------------------------------------------------- #
def _empty_row(code: str, note: str) -> dict:
    """A placeholder row for a code the feed never returned (bad/unknown code)."""
    return {
        "code": code, "name": "", "price": None, "prev_close": None,
        "open": None, "high": None, "low": None, "pct_chg": None,
        "volume": None, "amount": None, "pe_ttm": None, "pb": None,
        "mktcap_yi": None, "turnover": None, "halted": None, "note": note,
    }


def _split_codes(codes) -> list[str]:
    """Accept a comma/space-separated string OR a list -> flat list of tokens."""
    if isinstance(codes, str):
        toks = re.split(r"[,\s]+", codes.strip())
    else:
        toks = []
        for c in codes:
            toks.extend(re.split(r"[,\s]+", str(c).strip()))
    return [t for t in toks if t]


def fetch_quotes(codes) -> dict:
    """Batch realtime-snapshot quotes for A-share codes (baostock-independent).

    ``codes``: a comma/space-separated string OR a list of codes in any of the
    forms ``sh.600018`` / ``sz.301498`` / ``bj.430047`` / ``600018`` / ``sh600018``.

    Tries EastMoney ulist (one batch call); if it raises / returns empty /
    leaves any requested code WITHOUT a price, fills the remaining gaps from
    Tencent (one batch call) — per-code merge, not all-or-nothing. Returns::

        {"count": N, "source": "eastmoney"|"tencent"|"eastmoney+tencent",
         "as_of": "<str>",
         "data": [{"code","name","price","prev_close","open","high","low",
                   "pct_chg","volume","amount","pe_ttm","pb","mktcap_yi",
                   "turnover","halted"}, ...]}

    Output order matches the ORIGINAL input token order (bad codes included, in
    place). Codes are deduped (first occurrence wins its position). Every value
    is a float or None; a halted/missing/unknown code still appears with
    price=None (and a ``note`` if no feed returned it / it was un-parseable).
    One bad code never breaks the batch.
    """
    # Build an ordered list of (token, canonical-or-None) preserving the original
    # input order and deduping canonical codes. Un-parseable tokens carry a None
    # canonical and become a bad-placeholder row IN PLACE (order preserved).
    ordered: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    canon: list[str] = []
    for tok in _split_codes(codes):
        try:
            c = _norm(tok)
        except ValueError:
            ordered.append((tok, None))  # bad code, in its original position
            continue
        if c in seen:
            continue  # duplicate canonical -> keep only the first occurrence
        seen.add(c)
        canon.append(c)
        ordered.append((tok, c))

    # Fetch EastMoney (primary), then merge Tencent into any per-code GAP (a code
    # EM never returned, or returned without a price). This fills complementary
    # partial coverage instead of replacing wholesale.
    em_by_code: dict[str, dict] = {}
    tx_by_code: dict[str, dict] = {}
    em_as_of = ""
    tx_as_of = ""
    if canon:
        try:
            em_rows, em_as_of = _fetch_eastmoney(canon)
        except Exception:
            em_rows = []
        for r in em_rows:
            em_by_code.setdefault(r["code"], r)
        # A code is "covered" only if EM gave it a usable (non-None) price.
        missing = [c for c in canon
                   if em_by_code.get(c) is None or em_by_code[c]["price"] is None]
        if missing:
            try:
                tx_rows, tx_as_of = _fetch_tencent(canon)
            except Exception:
                tx_rows = []
            for r in tx_rows:
                tx_by_code.setdefault(r["code"], r)

    # Per-code merge: prefer EM if it priced the code, else Tencent if it did,
    # else whatever EM/Tencent returned (price None) for a halted name, else a
    # never-returned placeholder. Track which backend(s) actually contributed.
    used_em = False
    used_tx = False
    merged: dict[str, dict] = {}
    for c in canon:
        em = em_by_code.get(c)
        tx = tx_by_code.get(c)
        if em is not None and em["price"] is not None:
            merged[c] = em
            used_em = True
        elif tx is not None and tx["price"] is not None:
            merged[c] = tx
            used_tx = True
        elif em is not None:
            merged[c] = em            # EM returned it (e.g. halted, price None)
            used_em = True
        elif tx is not None:
            merged[c] = tx            # Tencent returned it (halted, price None)
            used_tx = True
        else:
            merged[c] = _empty_row(c, "未返回行情(代码可能无效或停牌)")

    if used_em and used_tx:
        source = "eastmoney+tencent"
    elif used_tx:
        source = "tencent"
    else:
        source = "eastmoney"
    # Prefer the backend that actually carried the data for as_of.
    as_of = em_as_of if used_em else (tx_as_of or em_as_of)

    # Render in ORIGINAL input token order; bad codes appear in place.
    data: list[dict] = []
    for tok, c in ordered:
        if c is None:
            data.append(_empty_row(tok, "无法解析的代码"))
        else:
            data.append(merged[c])

    return {"count": len(data), "source": source, "as_of": as_of, "data": data}
