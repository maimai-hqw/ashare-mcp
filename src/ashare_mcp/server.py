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
