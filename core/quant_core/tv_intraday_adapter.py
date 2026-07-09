"""
tv_intraday_adapter.py — TradingView (unofficial, via tvdatafeed) intraday adapter
for Casablanca/MASI equities.

This is a separate file from data.py (which is already huge) so it can be
imported/tested independently, and so environments without tvdatafeed installed
don't break on import of this module (the tvDatafeed import is guarded).

tvdatafeed (https://github.com/rongardF/tvdatafeed) is an UNOFFICIAL TradingView
scraper — no official API / no ToS sanction. Treat any code path that uses this
adapter as manual/on-demand, not part of the scheduled production pipeline.

Install: pip install "git+https://github.com/rongardF/tvdatafeed"
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Sequence

import pandas as pd

from core.quant_core.data import BaseDataSource

logger = logging.getLogger(__name__)

try:
    from tvDatafeed import Interval, TvDatafeed

    _TVDATAFEED_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when package is missing
    Interval = None  # type: ignore
    TvDatafeed = None  # type: ignore
    _TVDATAFEED_AVAILABLE = False


# Map our internal interval strings to tvDatafeed's Interval enum.
_INTERVAL_MAP_NAMES = {
    "1d": "in_daily",
    "daily": "in_daily",
    "1h": "in_1_hour",
    "1hour": "in_1_hour",
    "15m": "in_15_minute",
    "15min": "in_15_minute",
}


def _resolve_interval(interval: str):
    """Resolve an internal interval string to a tvDatafeed Interval enum member.

    Raises ValueError for unsupported interval strings, and RuntimeError if
    tvDatafeed is not installed.
    """
    if not _TVDATAFEED_AVAILABLE:
        raise RuntimeError(
            "tvDatafeed is not installed. Install with: "
            'pip install "git+https://github.com/rongardF/tvdatafeed"'
        )
    key = str(interval).strip().lower()
    attr_name = _INTERVAL_MAP_NAMES.get(key)
    if attr_name is None:
        raise ValueError(
            f"Unsupported interval {interval!r} for TradingViewIntradayAdapter. "
            f"Supported: {sorted(_INTERVAL_MAP_NAMES)}"
        )
    return getattr(Interval, attr_name)


class TradingViewIntradayAdapter(BaseDataSource):
    """Adapter that fetches intraday (and daily) OHLCV bars from TradingView via
    the unofficial `tvdatafeed` scraper, anonymously (no login).

    Casablanca exchange code: "CSEMA" (validated in scratch/tv_spike.py).

    NOT wired into any scheduled task — manual/on-demand use only. See
    services/worker/tasks/ingest_intraday_market_data.py for the manual
    backfill entry point.
    """

    def __init__(
        self,
        exchange: str = "CSEMA",
        timezone: str = "UTC",
        cache_dir=None,
        use_cache: bool = False,
    ) -> None:
        super().__init__(timezone=timezone, cache_dir=cache_dir, use_cache=use_cache)
        self.exchange = exchange

    def _load_impl(
        self,
        symbols: Sequence[str],
        start: Optional[str],
        end: Optional[str],
        interval: str,
        **kwargs,
    ) -> Dict[str, pd.DataFrame]:
        if not _TVDATAFEED_AVAILABLE:
            raise RuntimeError(
                "tvDatafeed is not installed. Install with: "
                'pip install "git+https://github.com/rongardF/tvdatafeed"'
            )

        tv_interval = _resolve_interval(interval)
        n_bars = int(kwargs.get("n_bars", 5000))

        # One anonymous session, reused across all symbols in this batch.
        tv = TvDatafeed()

        out: Dict[str, pd.DataFrame] = {}
        for symbol in symbols:
            try:
                df = tv.get_hist(
                    symbol=symbol,
                    exchange=self.exchange,
                    interval=tv_interval,
                    n_bars=n_bars,
                )
                if df is None or len(df) == 0:
                    logger.warning(
                        "TradingViewIntradayAdapter: no bars returned for %s (exchange=%s, interval=%s)",
                        symbol,
                        self.exchange,
                        interval,
                    )
                    continue
                out[symbol] = df
            except Exception:
                logger.exception(
                    "TradingViewIntradayAdapter: failed to fetch %s (exchange=%s, interval=%s)",
                    symbol,
                    self.exchange,
                    interval,
                )
                continue

        return out
