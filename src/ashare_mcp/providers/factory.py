"""Select the active data provider.

Reads ``ASHARE_SOURCE`` (default ``baostock``). This is the single place that
knows about concrete backends — adding eastmoney later means adding one branch
here plus the new provider class, with no change to the tool layer.
"""

from __future__ import annotations

import os

from .base import DataProvider


def get_provider(name: str = "") -> DataProvider:
    source = (name or os.environ.get("ASHARE_SOURCE", "baostock")).strip().lower()
    if source == "baostock":
        from .baostock import BaostockProvider

        return BaostockProvider()
    raise ValueError(
        f"未知数据源 ASHARE_SOURCE={source!r}（v1 仅支持 baostock）"
    )
