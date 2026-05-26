from __future__ import annotations

from core.quant_core.fundamentals.domain import FundamentalWorkbook
from core.quant_core.fundamentals.workbook import parse_fundamental_workbook


class WorkbookFundamentalProvider:
    def fetch_bytes(self, payload: bytes) -> FundamentalWorkbook:
        return parse_fundamental_workbook(payload)
