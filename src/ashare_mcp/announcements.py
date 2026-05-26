"""A-share disclosure announcements (公告) via EastMoney HTTP APIs.

This is independent of the baostock provider — baostock has no announcement
surface. Two capabilities:

  * ``list_announcements``  -> 东财公告列表 (np-anotice-stock ... /api/security/ann)
  * ``download_announcement`` -> 东财公告正文 (np-cnotice-stock ... /api/content/ann)
                                 resolves the real PDF attach_url and saves it.

Stdlib only (urllib), so the package adds no new dependencies. Reachable from
non-CN networks (unlike baostock's port 10030). All callers run these in a
worker thread; they do NOT touch baostock global state, so no baostock lock.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "Referer": "https://data.eastmoney.com/"}

_LIST_API = "https://np-anotice-stock.eastmoney.com/api/security/ann"
_CONTENT_API = "https://np-cnotice-stock.eastmoney.com/api/content/ann"
_PDF_FALLBACK = "https://pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf"
_FALLBACK_DIR = "~/.cache/ashare-mcp/announcements"


def _default_dir() -> str:
    """Default download directory. Set env ``ASHARE_DOWNLOAD_DIR`` (e.g. in the
    MCP server registration) to redirect downloads into a project folder;
    otherwise falls back to ~/.cache. An explicit ``save_dir`` arg always wins."""
    return os.path.expanduser(os.environ.get("ASHARE_DOWNLOAD_DIR") or _FALLBACK_DIR)


def _digits(code: str) -> str:
    """'sh.600519' / 'sz.002049' / '600519' -> '600519' (EastMoney wants the
    bare 6-digit security code in stock_list)."""
    m = re.search(r"(\d{6})", code or "")
    if not m:
        raise ValueError(f"无法从代码中解析 6 位证券代码: {code!r}")
    return m.group(1)


def _get_json(url: str, timeout: float = 20.0) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw)


def _columns_label(item: dict) -> str:
    cols = item.get("columns") or []
    names = [c.get("column_name") for c in cols if isinstance(c, dict) and c.get("column_name")]
    return " / ".join(names)


def list_announcements(
    code: str,
    start_date: str = "",
    end_date: str = "",
    page_size: int = 50,
    keyword: str = "",
    max_pages: int = 20,
) -> dict:
    """List disclosure announcements for a stock, newest first.

    code: 'sh.600519' / 'sz.002049' / '600519'.
    start_date / end_date: 'YYYY-MM-DD' inclusive filter (empty = no bound).
    page_size: max rows to return. keyword: case-sensitive substring on title.
    Returns {code, count, data:[{art_code, title, notice_date, type, pdf_url_guess}]}.
    Feed art_code into download_stock_announcement to fetch the PDF.
    """
    num = _digits(code)
    out: list[dict] = []
    page = 1
    while page <= max_pages and len(out) < page_size:
        qs = urllib.parse.urlencode({
            "sr": -1, "page_size": 100, "page_index": page, "ann_type": "A",
            "client_source": "web", "stock_list": num,
        })
        data = (_get_json(f"{_LIST_API}?{qs}") or {}).get("data") or {}
        items = data.get("list") or []
        if not items:
            break
        stop = False
        for it in items:
            nd = (it.get("notice_date") or it.get("display_time") or "")[:10]
            if end_date and nd > end_date:
                continue
            if start_date and nd < start_date:
                stop = True  # list is sorted desc -> nothing older remains
                break
            if keyword and keyword not in (it.get("title") or ""):
                continue
            art = it.get("art_code") or ""
            out.append({
                "art_code": art,
                "title": it.get("title") or "",
                "notice_date": nd,
                "type": _columns_label(it),
                "pdf_url_guess": _PDF_FALLBACK.format(art_code=art),
            })
            if len(out) >= page_size:
                stop = True
                break
        if stop:
            break
        page += 1
    return {"code": num, "count": len(out), "data": out}


def _resolve_attachments(art_code: str) -> tuple[str, list[str]]:
    """Return (notice_title, [pdf_url, ...]) for an announcement via the content
    API; fall back to the H2_<art_code>_1.pdf naming convention."""
    qs = urllib.parse.urlencode({"art_code": art_code, "client_source": "web", "page_index": 1})
    data = (_get_json(f"{_CONTENT_API}?{qs}") or {}).get("data") or {}
    title = data.get("notice_title") or ""
    urls: list[str] = []
    for a in data.get("attach_list") or []:
        if isinstance(a, dict) and a.get("attach_url"):
            urls.append(a["attach_url"])
    if not urls and data.get("attach_url"):
        urls.append(data["attach_url"])
    if not urls:
        urls.append(_PDF_FALLBACK.format(art_code=art_code))
    return title, urls


def _safe(name: str, limit: int = 40) -> str:
    name = re.sub(r"[^\w一-鿿-]", "_", name or "")
    return name[:limit].strip("_") or "announcement"


def _download(url: str, path: str, timeout: float = 60.0) -> int:
    req = urllib.request.Request(url, headers=_HEADERS)
    total = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(path, "wb") as fh:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            fh.write(chunk)
            total += len(chunk)
    return total


def download_announcement(art_code: str, save_dir: str = "") -> dict:
    """Download an announcement's PDF(s) by art_code to local disk.

    Returns {art_code, title, save_dir, files:[{path, url, bytes}]}. Open the
    returned path with the Read tool (it handles PDFs natively).
    """
    if not art_code:
        raise ValueError("art_code 不能为空(来自 list_announcements 的返回)")
    title, urls = _resolve_attachments(art_code)
    save_dir = os.path.expanduser(save_dir) if save_dir else _default_dir()
    os.makedirs(save_dir, exist_ok=True)
    files: list[dict] = []
    for i, url in enumerate(urls, 1):
        clean = url.split("?", 1)[0]
        ext = os.path.splitext(clean)[1] or ".pdf"
        suffix = f"_{i}" if len(urls) > 1 else ""
        fn = f"{art_code}{suffix}_{_safe(title)}{ext}"
        path = os.path.join(save_dir, fn)
        nbytes = _download(url, path)
        files.append({"path": path, "url": clean, "bytes": nbytes})
    return {"art_code": art_code, "title": title, "save_dir": save_dir, "files": files}
