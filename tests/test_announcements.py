"""Unit tests for announcement helpers (pure functions, no network).

Live API behaviour is covered by manual/integration checks; these guard the
code-normalization and filename-sanitization logic that must never regress.
"""

import os

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


def test_default_dir_honors_env(monkeypatch):
    monkeypatch.setenv("ASHARE_DOWNLOAD_DIR", "/tmp/some/proj/公告下载")
    assert A._default_dir() == "/tmp/some/proj/公告下载"


def test_default_dir_falls_back_when_env_unset(monkeypatch):
    monkeypatch.delenv("ASHARE_DOWNLOAD_DIR", raising=False)
    assert A._default_dir().endswith("/.cache/ashare-mcp/announcements")


def test_download_resolves_default_dir_without_network(monkeypatch, tmp_path):
    """Exercises download_announcement's dir-resolution + write path (no network).
    Guards the _DEFAULT_DIR/_default_dir() rename regression."""
    monkeypatch.setenv("ASHARE_DOWNLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(A, "_resolve_attachments", lambda ac: ("标题:测试", ["https://x/H2_AN_1.pdf"]))

    def _fake_dl(url, path, timeout=60.0):
        with open(path, "wb") as fh:
            fh.write(b"%PDF-1.4 test")
        return 13

    monkeypatch.setattr(A, "_download", _fake_dl)
    out = A.download_announcement("AN_TEST")
    assert out["save_dir"] == str(tmp_path)
    assert out["files"][0]["bytes"] == 13
    assert os.path.exists(out["files"][0]["path"])
