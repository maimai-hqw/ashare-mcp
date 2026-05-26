English | [简体中文](README_zh.md)

# ashare-mcp

An MCP server built on [baostock](http://baostock.com) that exposes **all 23**
baostock data endpoints as MCP tools: K-line, quarterly financials (profit /
operation / growth / balance / cash-flow / DuPont), performance express &
forecast reports, dividends, adjust factors, industry classification, index
constituents, the trading calendar, and macro series.

The data layer sits behind a `DataProvider` abstraction. v1 ships the
`baostock` backend, with the seam in place to add other sources (e.g.
eastmoney) later without touching the tool layer.

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
| Utility | `get_current_time` |

Every data tool returns a uniform shape: `{"count": int, "fields": [...], "data": [{...}, ...]}`.

## Codes

Pass baostock-form codes: `sh.600519`, `sz.000001`, `bj.430047`. Bare 6-digit
codes (e.g. `600519`) are normalized best-effort, but **ambiguous index codes**
(e.g. `000001` is both SSE Composite `sh.000001` and Ping An Bank `sz.000001`)
should be passed with an explicit prefix.

## Configuration

| Env var | Default | Meaning |
| --- | --- | --- |
| `ASHARE_SOURCE` | `baostock` | Data backend. Only `baostock` in v1. |

## Development

```bash
uv run pytest -q              # unit tests (no network)
uv run pytest -q -m network   # live baostock smoke test
```

## Notes

- baostock's data port must be reachable from your network (reachable inside
  mainland China; may time out elsewhere). If tools start timing out, check
  this first.
- baostock needs **no registration**, but each process still must call
  `bs.login()` to open a session — this server logs in once and logs out on
  shutdown.
