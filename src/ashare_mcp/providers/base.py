"""The data-source seam.

``DataProvider`` is the abstract surface every backend implements. The tool
layer in ``server.py`` depends only on this interface, never on ``baostock``
directly — so adding a second source (e.g. eastmoney) means writing a new
``DataProvider`` subclass, not editing any tool. v1 ships ``BaostockProvider``.

Every method returns the uniform payload shape produced by
``serialize.rs_to_payload``:

    {"count": int, "fields": [str, ...], "data": [{field: value, ...}, ...]}
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

Payload = Dict[str, Any]


class DataProvider(ABC):
    name: str = "base"

    # --- market ---------------------------------------------------------
    @abstractmethod
    def get_stock_basic(self, code: str = "", code_name: str = "") -> Payload: ...

    @abstractmethod
    def get_all_stock(self, day: str = "") -> Payload: ...

    @abstractmethod
    def get_trade_dates(self, start_date: str = "", end_date: str = "") -> Payload: ...

    @abstractmethod
    def get_history_k_data(
        self,
        code: str,
        start_date: str = "",
        end_date: str = "",
        frequency: str = "d",
        adjustflag: str = "3",
        fields: str = "",
    ) -> Payload: ...

    # --- dividend / adjust ---------------------------------------------
    @abstractmethod
    def get_dividend_data(self, code: str, year: str = "", yearType: str = "report") -> Payload: ...

    @abstractmethod
    def get_adjust_factor(self, code: str, start_date: str = "", end_date: str = "") -> Payload: ...

    # --- quarterly financials ------------------------------------------
    @abstractmethod
    def get_profit_data(self, code: str, year: str = "", quarter: str = "") -> Payload: ...

    @abstractmethod
    def get_operation_data(self, code: str, year: str = "", quarter: str = "") -> Payload: ...

    @abstractmethod
    def get_growth_data(self, code: str, year: str = "", quarter: str = "") -> Payload: ...

    @abstractmethod
    def get_balance_data(self, code: str, year: str = "", quarter: str = "") -> Payload: ...

    @abstractmethod
    def get_cash_flow_data(self, code: str, year: str = "", quarter: str = "") -> Payload: ...

    @abstractmethod
    def get_dupont_data(self, code: str, year: str = "", quarter: str = "") -> Payload: ...

    # --- performance reports -------------------------------------------
    @abstractmethod
    def get_performance_express_report(self, code: str, start_date: str = "", end_date: str = "") -> Payload: ...

    @abstractmethod
    def get_forecast_report(self, code: str, start_date: str = "", end_date: str = "") -> Payload: ...

    # --- industry / index constituents ---------------------------------
    @abstractmethod
    def get_stock_industry(self, code: str = "", date: str = "") -> Payload: ...

    @abstractmethod
    def get_sz50_stocks(self, date: str = "") -> Payload: ...

    @abstractmethod
    def get_hs300_stocks(self, date: str = "") -> Payload: ...

    @abstractmethod
    def get_zz500_stocks(self, date: str = "") -> Payload: ...

    # --- macro ----------------------------------------------------------
    @abstractmethod
    def get_deposit_rate_data(self, start_date: str = "", end_date: str = "") -> Payload: ...

    @abstractmethod
    def get_loan_rate_data(self, start_date: str = "", end_date: str = "") -> Payload: ...

    @abstractmethod
    def get_required_reserve_ratio_data(self, start_date: str = "", end_date: str = "", yearType: str = "0") -> Payload: ...

    @abstractmethod
    def get_money_supply_data_month(self, start_date: str = "", end_date: str = "") -> Payload: ...

    @abstractmethod
    def get_money_supply_data_year(self, start_date: str = "", end_date: str = "") -> Payload: ...
