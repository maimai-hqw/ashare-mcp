English | [简体中文](README_zh.md)

# ashare-mcp

An MCP server built on [baostock](http://baostock.com) that exposes **all 23**
baostock data endpoints as MCP tools: K-line, quarterly financials (profit /
operation / growth / balance / cash-flow / DuPont), performance express &
forecast reports, dividends, adjust factors, industry classification, index
constituents, the trading calendar, and macro series.

It also ships two **disclosure-announcement (公告) tools** backed by
EastMoney's public HTTP APIs — list announcements for a stock and download
the PDF — since baostock has no announcement surface. EastMoney's endpoints
are reachable outside mainland China, so these work even when baostock's
data port is blocked.

The data layer sits behind a `DataProvider` abstraction. v1 ships the
`baostock` backend, with the seam in place to add other sources later without
touching the tool layer. The announcement tools live alongside the provider
(they don't go through baostock at all).

## Install

```bash
uv sync
```

## Run (stdio)

```bash
uv run ashare-mcp
```

Configure it in a stdio MCP client (Claude Desktop / Claude Code / Cursor):

```json
{
  "mcpServers": {
    "ashare": {
      "command": "uv",
      "args": ["--directory", "/path/to/ashare-mcp", "run", "ashare-mcp"]
    }
  }
}
```

## Tools

| Category | Tools |
| --- | --- |
| Market | `get_stock_basic` `get_all_stock` `get_trade_dates` `get_history_k_data` |
| Dividend / adjust | `get_dividend_data` `get_adjust_factor` |
| Quarterly financials | `get_profit_data` `get_operation_data` `get_growth_data` `get_balance_data` `get_cash_flow_data` `get_dupont_data` |
| Reports | `get_performance_express_report` `get_forecast_report` |
| Industry / constituents | `get_stock_industry` `get_sz50_stocks` `get_hs300_stocks` `get_zz500_stocks` |
| Macro | `get_deposit_rate_data` `get_loan_rate_data` `get_required_reserve_ratio_data` `get_money_supply_data_month` `get_money_supply_data_year` |
| Disclosure (EastMoney) | `get_stock_announcements` `download_stock_announcement` |
| Utility | `get_current_time` |

Every baostock-backed data tool returns a uniform shape:
`{"count": int, "fields": [...], "data": [{...}, ...]}`. The announcement
tools return their own shape (see below).

### Disclosure announcements (公告)

Two EastMoney-backed tools, independent of baostock:

- **`get_stock_announcements(code, start_date="", end_date="", page_size=50, keyword="")`**
  — list a stock's announcements newest-first.
  `code` accepts `sh.600519` / `sz.002049` / `600519`.
  `start_date` / `end_date` are inclusive `YYYY-MM-DD` filters.
  `keyword` is a case-sensitive substring on the title (e.g. `重组`).
  Returns `{code, count, data:[{art_code, title, notice_date, type, pdf_url_guess}]}`.

- **`download_stock_announcement(art_code, save_dir="")`** — download the
  announcement PDF by the `art_code` returned above. Resolves the real
  attachment URL via EastMoney's content API (falls back to the
  `H2_<art_code>_1.pdf` convention if needed). Returns
  `{art_code, title, save_dir, files:[{path, url, bytes}]}` — open the
  returned `path` with the MCP client's file/Read tool to read the PDF.

Typical flow: call `get_stock_announcements` → pick an `art_code` →
`download_stock_announcement` → read the saved PDF.

## Codes

Pass baostock-form codes: `sh.600519`, `sz.000001`, `bj.430047`. Bare 6-digit
codes (e.g. `600519`) are normalized best-effort, but **ambiguous index codes**
(e.g. `000001` is both SSE Composite `sh.000001` and Ping An Bank `sz.000001`)
should be passed with an explicit prefix.

## Configuration

| Env var | Default | Meaning |
| --- | --- | --- |
| `ASHARE_SOURCE` | `baostock` | Data backend. Only `baostock` in v1. |
| `ASHARE_DOWNLOAD_DIR` | `~/.cache/ashare-mcp/announcements` | Where `download_stock_announcement` saves PDFs. Set this in your MCP client config to point downloads at a project folder. An explicit `save_dir` arg to the tool always wins. |

## Development

```bash
uv run pytest -q              # unit tests (no network)
uv run pytest -q -m network   # live baostock smoke test
```

## Notes

- baostock's data port must be reachable from your network (reachable inside
  mainland China; may time out elsewhere). If baostock tools start timing
  out, check this first. The EastMoney announcement tools use a separate
  HTTPS endpoint and are typically reachable outside CN.
- baostock needs **no registration**, but each process still must call
  `bs.login()` to open a session — this server logs in once and logs out on
  shutdown.
- The announcement tools are stdlib-only (no new dependencies) and run off
  the baostock session, so they keep working even if baostock is down.
