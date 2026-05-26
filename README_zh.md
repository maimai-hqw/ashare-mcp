[English](README.md) | 简体中文

# ashare-mcp

基于 [baostock](http://baostock.com) 的 A 股数据 MCP 服务器，把 baostock 的**全部** 23 个数据接口暴露成 MCP 工具：K 线、季频财务（盈利/营运/成长/偿债/现金流/杜邦）、业绩快报与预告、分红、复权因子、行业分类、指数成分股、交易日历、宏观数据。

数据层通过 `DataProvider` 抽象，目前实现 `baostock`，并预留了切换其他数据源（如 eastmoney）的接口缝。

## 安装

```bash
uv sync
```

## 运行（stdio）

```bash
uv run ashare-mcp
```

在 MCP 客户端（Claude Desktop / Claude Code / Cursor）里配置：

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

## 工具一览

| 分类 | 工具 |
| --- | --- |
| 行情 | `get_stock_basic` `get_all_stock` `get_trade_dates` `get_history_k_data` |
| 分红/复权 | `get_dividend_data` `get_adjust_factor` |
| 季频财务 | `get_profit_data` `get_operation_data` `get_growth_data` `get_balance_data` `get_cash_flow_data` `get_dupont_data` |
| 业绩报告 | `get_performance_express_report` `get_forecast_report` |
| 行业/成分股 | `get_stock_industry` `get_sz50_stocks` `get_hs300_stocks` `get_zz500_stocks` |
| 宏观 | `get_deposit_rate_data` `get_loan_rate_data` `get_required_reserve_ratio_data` `get_money_supply_data_month` `get_money_supply_data_year` |
| 工具 | `get_current_time` |

所有数据工具返回统一结构：`{"count": 条数, "fields": [字段名], "data": [{...}]}`

## 股票代码

传 baostock 格式：`sh.600519`、`sz.000001`、`bj.430047`。也支持纯 6 位数字（如 `600519`）自动补前缀；但**指数等有歧义的代码**（如 `000001` 既是上证指数 `sh.000001` 又是平安银行 `sz.000001`）请显式带前缀。

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ASHARE_SOURCE` | `baostock` | 数据源，v1 仅支持 `baostock` |

## 开发

```bash
uv run pytest -q              # 单元测试（不联网）
uv run pytest -q -m network   # baostock 联网冒烟测试
```

## 说明

- baostock 需要能连上其数据端口（境内可达，境外可能超时）。若工具开始超时，先排查网络。
- baostock **免注册**，但每次进程仍需调用 `bs.login()` 建立会话——本服务进程内只登录一次、退出时登出一次。
