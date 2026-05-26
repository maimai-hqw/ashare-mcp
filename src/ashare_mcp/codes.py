"""A-share security code normalization to baostock's ``xx.NNNNNN`` form.

baostock expects codes like ``sh.600519`` / ``sz.000001`` / ``bj.430047``.
Users (and LLMs) often pass a bare 6-digit code; this module infers the
exchange prefix where it can and raises a clear error where it genuinely
cannot. Ambiguous index codes (e.g. ``000001`` is both the SSE Composite
Index ``sh.000001`` and Ping An Bank ``sz.000001``) should be passed WITH an
explicit ``sh.``/``sz.`` prefix — bare numbers resolve to the stock reading.
"""

from __future__ import annotations

import re

_PREFIXED = re.compile(r"^(sh|sz|bj)\.(\d{6})$")
_BARE = re.compile(r"^\d{6}$")


def normalize_code(code: str) -> str:
    """Return a baostock-form code (``sh.600519``) from loose input.

    Accepts ``sh.600519``, ``SH600519``, ``600519`` and surrounding
    whitespace. Raises ``ValueError`` for empty or unrecognizable input.
    """
    if not code or not code.strip():
        raise ValueError("证券代码不能为空")

    c = re.sub(r"\s+", "", code).lower()

    # already prefixed (with or without the dot)
    m = _PREFIXED.match(c) or re.match(r"^(sh|sz|bj)(\d{6})$", c)
    if m:
        return f"{m.group(1)}.{m.group(2)}"

    if not _BARE.match(c):
        raise ValueError(
            f"无法识别的证券代码: {code!r}。请使用 sh.600519 / sz.000001 / bj.430047 形式"
        )

    return f"{_infer_exchange(c)}.{c}"


def _infer_exchange(num: str) -> str:
    """Best-effort exchange inference for a bare 6-digit code."""
    # Shanghai: A股 60x, 科创板 688/689, 基金/ETF 5xx, B股 900
    if num[0] == "6" or num[:3] in ("688", "689") or num[0] == "5" or num[:3] == "900":
        return "sh"
    # Beijing: 北交所 43x/83x/87x/88x, 920
    if num[:2] in ("43", "83", "87", "88") or num[:3] == "920":
        return "bj"
    # Shenzhen: 00x/30x stocks, 15x/16x funds, 12x bonds, 39x indices
    if num[0] in ("0", "1", "2", "3"):
        return "sz"
    raise ValueError(
        f"无法推断交易所前缀: {num!r}。请显式指定 sh./sz./bj. 前缀"
    )
