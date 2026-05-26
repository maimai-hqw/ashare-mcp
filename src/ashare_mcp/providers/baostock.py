"""baostock-backed :class:`DataProvider`.

Each method maps 1:1 onto a baostock ``query_*`` call, normalizes the security
code where applicable, drains the result set via ``rs_to_payload``, and returns
the uniform payload. All calls assume they run under the server's single-flight
lock (baostock is process-global and not thread-safe).
"""

from __future__ import annotations

from typing import Optional

import baostock as bs

from ..codes import normalize_code
from ..serialize import rs_to_payload
from ..session import BaostockSession, silence_stdout
from .base import DataProvider, Payload

# query_history_k_data_plus exposes different field sets per frequency.
_K_FIELDS_DAILY = (
    "date,code,open,high,low,close,preclose,volume,amount,adjustflag,"
    "turn,tradestatus,pctChg,peTTM,psTTM,pcfNcfTTM,pbMRQ,isST"
)
_K_FIELDS_WEEK_MONTH = "date,code,open,high,low,close,volume,amount,adjustflag,turn,pctChg"
_K_FIELDS_MINUTE = "date,time,code,open,high,low,close,volume,amount,adjustflag"


def _n(v) -> Optional[str]:
    """Empty string -> None (baostock treats None as 'unset')."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _kfields(frequency: str) -> str:
    f = str(frequency).strip().lower()
    if f in ("d",):
        return _K_FIELDS_DAILY
    if f in ("w", "m"):
        return _K_FIELDS_WEEK_MONTH
    if f in ("5", "15", "30", "60"):
        return _K_FIELDS_MINUTE
    raise ValueError(f"无效的 frequency: {frequency!r}（取 d/w/m/5/15/30/60）")


class BaostockProvider(DataProvider):
    name = "baostock"

    def __init__(self, session: Optional[BaostockSession] = None) -> None:
        self._session = session or BaostockSession()

    def _q(self, fn, *args, **kwargs) -> Payload:
        """Login (idempotent), run a baostock query, normalize the result."""
        self._session.ensure_login()
        with silence_stdout():
            rs = fn(*args, **kwargs)
        return rs_to_payload(rs)

    def close(self) -> None:
        self._session.logout()

    # --- market ---------------------------------------------------------
    def get_stock_basic(self, code: str = "", code_name: str = "") -> Payload:
        return self._q(
            bs.query_stock_basic,
            code=normalize_code(code) if code else "",
            code_name=code_name or "",
        )

    def get_all_stock(self, day: str = "") -> Payload:
        return self._q(bs.query_all_stock, day=_n(day))

    def get_trade_dates(self, start_date: str = "", end_date: str = "") -> Payload:
        return self._q(bs.query_trade_dates, start_date=_n(start_date), end_date=_n(end_date))

    def get_history_k_data(
        self,
        code: str,
        start_date: str = "",
        end_date: str = "",
        frequency: str = "d",
        adjustflag: str = "3",
        fields: str = "",
    ) -> Payload:
        return self._q(
            bs.query_history_k_data_plus,
            normalize_code(code),
            fields or _kfields(frequency),
            start_date=_n(start_date),
            end_date=_n(end_date),
            frequency=str(frequency),
            adjustflag=str(adjustflag),
        )

    # --- dividend / adjust ---------------------------------------------
    def get_dividend_data(self, code: str, year: str = "", yearType: str = "report") -> Payload:
        return self._q(
            bs.query_dividend_data,
            code=normalize_code(code),
            year=_n(year) or "",
            yearType=yearType or "report",
        )

    def get_adjust_factor(self, code: str, start_date: str = "", end_date: str = "") -> Payload:
        return self._q(
            bs.query_adjust_factor,
            code=normalize_code(code),
            start_date=_n(start_date),
            end_date=_n(end_date),
        )

    # --- quarterly financials ------------------------------------------
    def _financial(self, fn, code: str, year: str, quarter: str) -> Payload:
        return self._q(fn, code=normalize_code(code), year=_n(year), quarter=_n(quarter))

    def get_profit_data(self, code: str, year: str = "", quarter: str = "") -> Payload:
        return self._financial(bs.query_profit_data, code, year, quarter)

    def get_operation_data(self, code: str, year: str = "", quarter: str = "") -> Payload:
        return self._financial(bs.query_operation_data, code, year, quarter)

    def get_growth_data(self, code: str, year: str = "", quarter: str = "") -> Payload:
        return self._financial(bs.query_growth_data, code, year, quarter)

    def get_balance_data(self, code: str, year: str = "", quarter: str = "") -> Payload:
        return self._financial(bs.query_balance_data, code, year, quarter)

    def get_cash_flow_data(self, code: str, year: str = "", quarter: str = "") -> Payload:
        return self._financial(bs.query_cash_flow_data, code, year, quarter)

    def get_dupont_data(self, code: str, year: str = "", quarter: str = "") -> Payload:
        return self._financial(bs.query_dupont_data, code, year, quarter)

    # --- performance reports -------------------------------------------
    def get_performance_express_report(self, code: str, start_date: str = "", end_date: str = "") -> Payload:
        return self._q(
            bs.query_performance_express_report,
            code=normalize_code(code),
            start_date=_n(start_date),
            end_date=_n(end_date),
        )

    def get_forecast_report(self, code: str, start_date: str = "", end_date: str = "") -> Payload:
        return self._q(
            bs.query_forecast_report,
            code=normalize_code(code),
            start_date=_n(start_date),
            end_date=_n(end_date),
        )

    # --- industry / index constituents ---------------------------------
    def get_stock_industry(self, code: str = "", date: str = "") -> Payload:
        return self._q(
            bs.query_stock_industry,
            code=normalize_code(code) if code else "",
            date=_n(date) or "",
        )

    def get_sz50_stocks(self, date: str = "") -> Payload:
        return self._q(bs.query_sz50_stocks, date=_n(date) or "")

    def get_hs300_stocks(self, date: str = "") -> Payload:
        return self._q(bs.query_hs300_stocks, date=_n(date) or "")

    def get_zz500_stocks(self, date: str = "") -> Payload:
        return self._q(bs.query_zz500_stocks, date=_n(date) or "")

    # --- macro ----------------------------------------------------------
    def get_deposit_rate_data(self, start_date: str = "", end_date: str = "") -> Payload:
        return self._q(bs.query_deposit_rate_data, start_date=_n(start_date) or "", end_date=_n(end_date) or "")

    def get_loan_rate_data(self, start_date: str = "", end_date: str = "") -> Payload:
        return self._q(bs.query_loan_rate_data, start_date=_n(start_date) or "", end_date=_n(end_date) or "")

    def get_required_reserve_ratio_data(self, start_date: str = "", end_date: str = "", yearType: str = "0") -> Payload:
        return self._q(
            bs.query_required_reserve_ratio_data,
            start_date=_n(start_date) or "",
            end_date=_n(end_date) or "",
            yearType=yearType or "0",
        )

    def get_money_supply_data_month(self, start_date: str = "", end_date: str = "") -> Payload:
        return self._q(bs.query_money_supply_data_month, start_date=_n(start_date) or "", end_date=_n(end_date) or "")

    def get_money_supply_data_year(self, start_date: str = "", end_date: str = "") -> Payload:
        return self._q(bs.query_money_supply_data_year, start_date=_n(start_date) or "", end_date=_n(end_date) or "")
