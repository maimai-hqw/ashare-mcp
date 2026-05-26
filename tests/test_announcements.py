"""Unit tests for announcement helpers (pure functions, no network).

Live API behaviour is covered by manual/integration checks; these guard the
code-normalization and filename-sanitization logic that must never regress.
"""

import pytest

from ashare_mcp import announcements as A


@pytest.mark.parametrize("raw,expected", [
    ("sh.600519", "600519"),
    ("sz.002049", "002049"),
    ("600079", "600079"),
    ("SZ300498", "300498"),
    ("  002049  ", "002049"),
])
def test_digits_extracts_six_digit_code(raw, expected):
    assert A._digits(raw) == expected


def test_digits_rejects_garbage():
    with pytest.raises(ValueError):
        A._digits("not-a-code")


def test_columns_label_joins_names():
    item = {"columns": [{"column_name": "重大资产重组"}, {"column_name": "关联交易"}]}
    assert A._columns_label(item) == "重大资产重组 / 关联交易"
    assert A._columns_label({}) == ""


def test_safe_filename_strips_punctuation_keeps_cjk():
    out = A._safe("紫光国微:关于召开2026年第二次临时股东会的通知")
    assert "/" not in out and ":" not in out and "：" not in out
    assert "紫光国微" in out
    assert len(out) <= 40


def test_safe_filename_never_empty():
    assert A._safe("///") == "announcement"
    assert A._safe("") == "announcement"
