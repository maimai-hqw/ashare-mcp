[English](README.md) | 简体中文

# ashare-mcp

基于 [baostock](http://baostock.com) 的 A 股数据 MCP 服务器，把 baostock 的**全部** 23 个数据接口暴露成 MCP 工具：K 线、季频财务（盈利/营运/成长/偿债/现金流/杜邦）、业绩快报与预告、分红、复权因子、行业分类、指数成分股、交易日历、宏观数据。

此外还内置两个**信息披露公告**工具，基于东方财富公开 HTTP 接口：列出某只股票的公告 + 按公告下载 PDF（baostock 不提供公告接口）。东方财富接口在境外也可访问，所以即使 baostock 数据端口被墙也能用。

数据层通过 `DataProvider` 抽象，目前实现 `baostock`，并预留了切换其他数据源的接口缝。公告工具与 provider 平行，**不走 baostock**。

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
| 信息披露（东财） | `get_stock_announcements` `download_stock_announcement` |
| 工具 | `get_current_time` |

所有 baostock 数据工具返回统一结构：`{"count": 条数, "fields": [字段名], "data": [{...}]}`。公告工具返回结构见下文。

### 信息披露公告

两个东财后端的工具，与 baostock 互不相干：

- **`get_stock_announcements(code, start_date="", end_date="", page_size=50, keyword="")`**
  —— 按时间倒序列出某只股票的公告。
  `code` 支持 `sh.600519` / `sz.002049` / `600519`。
  `start_date` / `end_date` 为闭区间 `YYYY-MM-DD` 过滤。
  `keyword` 是标题大小写敏感子串（例如 `重组`）。
  返回 `{code, count, data:[{art_code, title, notice_date, type, pdf_url_guess}]}`。

- **`download_stock_announcement(art_code, save_dir="")`** —— 按上一步拿到的
  `art_code` 下载 PDF。会先调东财公告正文接口拿真实附件 URL（拿不到时回退到
  `H2_<art_code>_1.pdf` 命名规则）。返回
  `{art_code, title, save_dir, files:[{path, url, bytes}]}`，把 `path`
  交给客户端的 Read 工具就能直接读 PDF 正文。

典型链路：`get_stock_announcements` → 选一条 `art_code` →
`download_stock_announcement` → 读取保存的 PDF。

## 股票代码

传 baostock 格式：`sh.600519`、`sz.000001`、`bj.430047`。也支持纯 6 位数字（如 `600519`）自动补前缀；但**指数等有歧义的代码**（如 `000001` 既是上证指数 `sh.000001` 又是平安银行 `sz.000001`）请显式带前缀。

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ASHARE_SOURCE` | `baostock` | 数据源，v1 仅支持 `baostock` |
| `ASHARE_DOWNLOAD_DIR` | `~/.cache/ashare-mcp/announcements` | `download_stock_announcement` 保存 PDF 的目录。在 MCP 客户端配置里设这个变量，可以让公告下载到项目目录里。工具调用时显式传 `save_dir` 优先级更高。 |

## 开发

```bash
uv run pytest -q              # 单元测试（不联网）
uv run pytest -q -m network   # baostock 联网冒烟测试
```

## 说明

- baostock 需要能连上其数据端口（境内可达，境外可能超时）。若 baostock 工具开始超时，先排查网络。东财公告工具走另一个 HTTPS 域名，境外通常可访问。
- baostock **免注册**，但每次进程仍需调用 `bs.login()` 建立会话——本服务进程内只登录一次、退出时登出一次。
- 公告工具只用标准库（不引入新依赖），也不走 baostock 会话，所以即使 baostock 挂了也能用。
