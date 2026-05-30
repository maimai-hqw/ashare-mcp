"""ashare-mcp FastMCP server (stdio).

Exposes the full baostock query surface as MCP tools. baostock is synchronous,
blocking, and process-global/not-thread-safe, so every call is dispatched to a
worker thread (``asyncio.to_thread``) under a single ``asyncio.Lock`` — the
event loop never blocks and two baostock calls never overlap.

NOTE: in stdio transport, stdout is the protocol channel. All logging goes to
stderr; never ``print`` to stdout here.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from . import announcements
from . import quotes
from . import screen
from .providers import get_provider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("ashare-mcp")

mcp = FastMCP("ashare-mcp")
_provider = get_provider()
_lock = asyncio.Lock()
logger.info("data source: %s", _provider.name)


async def _run(fn, *args, **kwargs):
    """Serialize and off-load a blocking provider call to a worker thread."""
    async with _lock:
        return await asyncio.to_thread(fn, *args, **kwargs)


# ====================================================================== #
# Utility
# ====================================================================== #
@mcp.tool()
async def get_current_time() -> str:
    """Current local server time as 'YYYY-MM-DD HH:MM:SS'. Useful for building
    relative date ranges (e.g. 'last 30 days') for the date parameters below."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ====================================================================== #
# Market
# ====================================================================== #
@mcp.tool()
async def get_stock_basic(code: str = "", code_name: str = "") -> dict:
    """Basic securities profile. Pass `code` (e.g. 'sh.600519') OR `code_name`
    (Chinese name). Empty both -> all securities.
    Fields: code, code_name, ipoDate, outDate, type (1股票/2指数/3其它),
    status (1上市/0退市)."""
    return await _run(_provider.get_stock_basic, code, code_name)


@mcp.tool()
async def get_all_stock(day: str = "") -> dict:
    """All securities and their trading status on a given day (default: latest
    trading day). `day` format 'YYYY-MM-DD'.
    Fields: code, tradeStatus (1可交易/0停牌), code_name."""
    return await _run(_provider.get_all_stock, day)


@mcp.tool()
async def get_trade_dates(start_date: str = "", end_date: str = "") -> dict:
    """Trading-calendar flags between two dates (default: from 2015-01-01).
    Fields: calendar_date, is_trading_day (1是/0否)."""
    return await _run(_provider.get_trade_dates, start_date, end_date)


@mcp.tool()
async def get_history_k_data(
    code: str,
    start_date: str = "",
    end_date: str = "",
    frequency: str = "d",
    adjustflag: str = "3",
    fields: str = "",
) -> dict:
    """Historical K-line bars.
    frequency: d=日 w=周 m=月 5/15/30/60=分钟线.
    adjustflag: 1后复权 2前复权 3不复权(默认).
    Dates 'YYYY-MM-DD'. `fields` is auto-selected per frequency (daily includes
    peTTM/pbMRQ/psTTM/pcfNcfTTM/turn/pctChg; minute adds a `time` column); pass
    a comma-separated `fields` string only to override."""
    return await _run(
        _provider.get_history_k_data, code, start_date, end_date, frequency, adjustflag, fields
    )


# ====================================================================== #
# Dividend / adjust factor
# ====================================================================== #
@mcp.tool()
async def get_dividend_data(code: str, year: str = "", yearType: str = "report") -> dict:
    """Dividend / rights-issue records.
    yearType: 'report'(预案公告年, default) / 'operate'(除权除息年) / 'dividend'(分红年).
    Fields include dividCashPsBeforeTax/AfterTax, dividStocksPs, dividRegistDate,
    dividOperateDate, dividPayDate."""
    return await _run(_provider.get_dividend_data, code, year, yearType)


@mcp.tool()
async def get_adjust_factor(code: str, start_date: str = "", end_date: str = "") -> dict:
    """Price adjustment factors (复权因子, baostock 涨跌幅复权算法).
    Fields: code, dividOperateDate, foreAdjustFactor, backAdjustFactor, adjustFactor."""
    return await _run(_provider.get_adjust_factor, code, start_date, end_date)


# ====================================================================== #
# Quarterly financials (year + quarter 1..4)
# ====================================================================== #
@mcp.tool()
async def get_profit_data(code: str, year: str = "", quarter: str = "") -> dict:
    """Quarterly profitability (季频盈利能力). quarter 1..4.
    Fields: roeAvg, npMargin, gpMargin, netProfit, epsTTM, MBRevenue, totalShare, liqaShare."""
    return await _run(_provider.get_profit_data, code, year, quarter)


@mcp.tool()
async def get_operation_data(code: str, year: str = "", quarter: str = "") -> dict:
    """Quarterly operating capability (季频营运能力). quarter 1..4.
    Fields: NRTurnRatio, NRTurnDays, INVTurnRatio, INVTurnDays, CATurnRatio, AssetTurnRatio."""
    return await _run(_provider.get_operation_data, code, year, quarter)


@mcp.tool()
async def get_growth_data(code: str, year: str = "", quarter: str = "") -> dict:
    """Quarterly growth (季频成长能力). quarter 1..4.
    Fields: YOYEquity, YOYAsset, YOYNI, YOYEPSBasic, YOYPNI, YOYOperation."""
    return await _run(_provider.get_growth_data, code, year, quarter)


@mcp.tool()
async def get_balance_data(code: str, year: str = "", quarter: str = "") -> dict:
    """Quarterly solvency / balance-sheet ratios (季频偿债能力). quarter 1..4.
    Fields: currentRatio, quickRatio, cashRatio, YOYLiability, liabilityToAsset, assetToEquity."""
    return await _run(_provider.get_balance_data, code, year, quarter)


@mcp.tool()
async def get_cash_flow_data(code: str, year: str = "", quarter: str = "") -> dict:
    """Quarterly cash-flow ratios (季频现金流量). quarter 1..4.
    Fields: CAToAsset, NCAToAsset, tangibleAssetToAsset, ebitToInterest, CFOToOR,
    CFOToNP, CFOToGr."""
    return await _run(_provider.get_cash_flow_data, code, year, quarter)


@mcp.tool()
async def get_dupont_data(code: str, year: str = "", quarter: str = "") -> dict:
    """Quarterly DuPont decomposition (季频杜邦指数). quarter 1..4.
    Fields: dupontROE, dupontAssetStoEquity, dupontAssetTurn, dupontPnitoni,
    dupontNitogr, dupontTaxBurden, dupontIntburden, dupontEbittogr."""
    return await _run(_provider.get_dupont_data, code, year, quarter)


# ====================================================================== #
# Performance reports
# ====================================================================== #
@mcp.tool()
async def get_performance_express_report(code: str, start_date: str = "", end_date: str = "") -> dict:
    """Performance express reports (业绩快报) filed in [start_date, end_date].
    Fields include performanceExpStatDate, performanceExpressROEWa, performanceExpressEPSChgPct."""
    return await _run(_provider.get_performance_express_report, code, start_date, end_date)


@mcp.tool()
async def get_forecast_report(code: str, start_date: str = "", end_date: str = "") -> dict:
    """Earnings forecast / pre-announcements (业绩预告) in [start_date, end_date].
    Fields include profitForcastExpStatDate, profitForcastType, profitForcastChgPctUp/Dwn."""
    return await _run(_provider.get_forecast_report, code, start_date, end_date)


# ====================================================================== #
# Industry / index constituents
# ====================================================================== #
@mcp.tool()
async def get_stock_industry(code: str = "", date: str = "") -> dict:
    """Industry classification (申万). Empty `code` -> whole market.
    Fields: updateDate, code, code_name, industry, industryClassification."""
    return await _run(_provider.get_stock_industry, code, date)


@mcp.tool()
async def get_sz50_stocks(date: str = "") -> dict:
    """SSE 50 (上证50) constituents on `date` (default latest).
    Fields: updateDate, code, code_name."""
    return await _run(_provider.get_sz50_stocks, date)


@mcp.tool()
async def get_hs300_stocks(date: str = "") -> dict:
    """CSI 300 (沪深300) constituents on `date` (default latest).
    Fields: updateDate, code, code_name."""
    return await _run(_provider.get_hs300_stocks, date)


@mcp.tool()
async def get_zz500_stocks(date: str = "") -> dict:
    """CSI 500 (中证500) constituents on `date` (default latest).
    Fields: updateDate, code, code_name."""
    return await _run(_provider.get_zz500_stocks, date)


# ====================================================================== #
# Macro
# ====================================================================== #
@mcp.tool()
async def get_deposit_rate_data(start_date: str = "", end_date: str = "") -> dict:
    """Benchmark deposit rates (存款利率) over a date range."""
    return await _run(_provider.get_deposit_rate_data, start_date, end_date)


@mcp.tool()
async def get_loan_rate_data(start_date: str = "", end_date: str = "") -> dict:
    """Benchmark loan rates (贷款利率) over a date range."""
    return await _run(_provider.get_loan_rate_data, start_date, end_date)


@mcp.tool()
async def get_required_reserve_ratio_data(start_date: str = "", end_date: str = "", yearType: str = "0") -> dict:
    """Required reserve ratio (存款准备金率). yearType: 0生效日期(default)/1公告日期."""
    return await _run(_provider.get_required_reserve_ratio_data, start_date, end_date, yearType)


@mcp.tool()
async def get_money_supply_data_month(start_date: str = "", end_date: str = "") -> dict:
    """Monthly money supply M0/M1/M2 (货币供应量-月). Dates 'YYYY-MM'."""
    return await _run(_provider.get_money_supply_data_month, start_date, end_date)


@mcp.tool()
async def get_money_supply_data_year(start_date: str = "", end_date: str = "") -> dict:
    """Yearly money supply M0/M1/M2 (货币供应量-年). Dates 'YYYY'."""
    return await _run(_provider.get_money_supply_data_year, start_date, end_date)


# ====================================================================== #
# Disclosure announcements (公告) — EastMoney HTTP, not baostock
# ====================================================================== #
@mcp.tool()
async def get_stock_announcements(
    code: str,
    start_date: str = "",
    end_date: str = "",
    page_size: int = 50,
    keyword: str = "",
) -> dict:
    """List a stock's disclosure announcements (公告) from EastMoney, newest first.
    `code`: 'sh.600519' / 'sz.002049' / '600519'. `start_date`/`end_date`
    'YYYY-MM-DD' inclusive filter. `keyword`: substring on title (e.g. '重组').
    Returns {code, count, data:[{art_code, title, notice_date, type, pdf_url_guess}]}.
    Pass an art_code to download_stock_announcement to fetch the PDF.
    Source: EastMoney (reachable outside CN); not baostock."""
    return await asyncio.to_thread(
        announcements.list_announcements, code, start_date, end_date, page_size, keyword
    )


@mcp.tool()
async def download_stock_announcement(art_code: str, save_dir: str = "") -> dict:
    """Download an announcement's PDF by `art_code` (from get_stock_announcements)
    to local disk; resolves the real attachment URL via EastMoney's content API.
    `save_dir` default '~/.cache/ashare-mcp/announcements/'.
    Returns {art_code, title, save_dir, files:[{path, url, bytes}]} — open the
    returned `path` with the Read tool (it reads PDFs natively)."""
    return await asyncio.to_thread(announcements.download_announcement, art_code, save_dir)


# ====================================================================== #
# Value-hunt 市场初筛 (screen) — EastMoney 截面, not baostock
# ====================================================================== #
@mcp.tool()
async def screen_market(
    pe_min: float = 4,
    pe_max: float = 25,
    pb_max: float = 2.5,
    roe_min: float = 7,
    min_mktcap_yi: float = 50,
    min_price: float = 3,
    per_industry_cap: int = 8,
    total_cap: int = 120,
) -> dict:
    """价值投资市场初筛:一次性拉取全 A 股截面(东财行情),硬过滤 + 异常隔离 +
    强周期行业特判 + 行业内综合打分排序,产出主仓候选池与异常观察池。

    参数(均为年化口径阈值,留空用默认值):
      pe_min/pe_max: 非周期股 PE 区间(默认 4~25)。
      pb_max: ROE 偏低时的 PB 上限(默认 2.5;ROE≥12 时放宽到 3.0)。
      roe_min: 主仓 ROE 年化下限(默认 7;5~7 之间需高股息+低 PE 救援)。
      min_mktcap_yi: 总市值下限(亿,默认 50,剔除微盘)。
      min_price: 股价下限(默认 3,剔除仙股)。
      per_industry_cap: 每个一级行业最多保留的候选数(默认 8)。
      total_cap: 全市场候选总数上限(默认 120)。

    异常池单列(不计入主仓评分):极低 PE(0<PE<pe_min)、深度破净(PB<0.4)、
    业绩暴增(净利同比>300%,不论 PE 高低)、超高股息(>10%)——这些需人工甄别真假便宜。
    亏损股(PE<=0)按设计直接剔除(既不进主仓也不进异常池):本工具是「质量+价值」
    漏斗,深周期/困境反转/亏损股的判断留待后续深度分析阶段,不在此处放行。
    返回 {candidates, anomaly_pool, params, main_count, anomaly_count};
    candidates 每条含 score(0~100,越高越便宜/越优)。
    ROE 字段:每条候选/异常含 roe(年化估计,按「期间感知」因子年化)与
    roe_q(原始单期/累计 YTD f37,东财原值)。
    注:ROE 源字段 f37 为「最新报告期累计(YTD)ROE」(非单季)。内部按各股
    报告期(f221)用「期间感知」因子年化(一季报×4、半年报×2、三季报×4/3、
    年报×1;无 f221 时按当前日历窗口推断)再与上述年化阈值比较。
    数据源:东财(中国大陆外可达),非 baostock。"""
    return await asyncio.to_thread(
        screen.run_screen,
        pe_min=pe_min,
        pe_max=pe_max,
        pb_max=pb_max,
        roe_min=roe_min,
        min_mktcap_yi=min_mktcap_yi,
        min_price=min_price,
        per_industry_cap=per_industry_cap,
        total_cap=total_cap,
    )


# ====================================================================== #
# Batch realtime-snapshot quotes — EastMoney/Tencent HTTP, not baostock
# ====================================================================== #
@mcp.tool()
async def get_quotes(codes: str) -> dict:
    """批量实时快照行情(东财 push2delay 批量,腾讯 fallback;不依赖 baostock)。
    codes: 逗号/空格分隔的代码,如 'sh.600018,sz.301498,600332'(支持 sh./sz./bj./纯6位)。
    返回每只 {code,name,price,prev_close,open,high,low,pct_chg,volume,amount,pe_ttm,pb,mktcap_yi,turnover,halted}。
    用于刷新现价对照纪律触发档;一次调用取全部代码。"""
    return await _run(quotes.fetch_quotes, codes)


def main() -> None:
    """Run the server over stdio."""
    logger.info("starting ashare-mcp server (stdio)")
    try:
        mcp.run()
    finally:
        close = getattr(_provider, "close", None)
        if callable(close):
            try:
                close()
            except Exception as e:  # pragma: no cover - best-effort cleanup
                logger.warning("provider close failed: %s", e)


if __name__ == "__main__":
    main()
