from __future__ import annotations

from typing import Protocol

from core.quant_core.fundamentals.domain import FundamentalWorkbook


class FundamentalProvider(Protocol):
    def fetch(self, symbol: str) -> FundamentalWorkbook:
        ...


class ProviderUnavailableError(RuntimeError):
    pass


class UnmappedSymbolError(ValueError):
    pass


__all__ = [
    "FundamentalProvider",
    "ProviderUnavailableError",
    "UnmappedSymbolError",
]
