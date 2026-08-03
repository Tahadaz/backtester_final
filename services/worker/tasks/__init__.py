def execute_run(*args, **kwargs):
    from .execute_run import execute_run as _execute_run

    return _execute_run(*args, **kwargs)


def execute_defaults_discovery(*args, **kwargs):
    from .defaults_discovery import execute_defaults_discovery as _execute_defaults_discovery

    return _execute_defaults_discovery(*args, **kwargs)


def ingest_excel_to_store(*args, **kwargs):
    from .ingest_market_data import ingest_excel_to_store as _ingest_excel_to_store

    return _ingest_excel_to_store(*args, **kwargs)


def refresh_single_symbol(*args, **kwargs):
    from .refresh_market_data import refresh_single_symbol as _refresh_single_symbol

    return _refresh_single_symbol(*args, **kwargs)


def refresh_all_tracked_symbols(*args, **kwargs):
    from .refresh_market_data import refresh_all_tracked_symbols as _refresh_all_tracked_symbols

    return _refresh_all_tracked_symbols(*args, **kwargs)


def execute_strategy_backtest_run(*args, **kwargs):
    from .strategy_backtest_runs import execute_strategy_backtest_run as _execute_strategy_backtest_run

    return _execute_strategy_backtest_run(*args, **kwargs)


def execute_cross_asset_backtest(*args, **kwargs):
    from .cross_asset.run_backtest import execute_cross_asset_backtest as _execute_cross_asset_backtest

    return _execute_cross_asset_backtest(*args, **kwargs)


def ingest_macro_series(*args, **kwargs):
    from .ingest_macro_series import ingest_macro_series as _ingest_macro_series

    return _ingest_macro_series(*args, **kwargs)


def execute_fundamental_import(*args, **kwargs):
    from .fundamentals import execute_fundamental_import as _execute_fundamental_import

    return _execute_fundamental_import(*args, **kwargs)


def refresh_yfinance_universe(*args, **kwargs):
    from .refresh_yfinance_fundamentals import refresh_yfinance_universe as _refresh_yfinance_universe

    return _refresh_yfinance_universe(*args, **kwargs)


def refresh_yfinance_for_symbol(*args, **kwargs):
    from .refresh_yfinance_fundamentals import refresh_yfinance_for_symbol as _refresh_yfinance_for_symbol

    return _refresh_yfinance_for_symbol(*args, **kwargs)


def refresh_stockanalysis_universe(*args, **kwargs):
    from .refresh_stockanalysis_fundamentals import refresh_stockanalysis_universe as _refresh_stockanalysis_universe

    return _refresh_stockanalysis_universe(*args, **kwargs)


def refresh_stockanalysis_for_symbol(*args, **kwargs):
    from .refresh_stockanalysis_fundamentals import refresh_stockanalysis_for_symbol as _refresh_stockanalysis_for_symbol

    return _refresh_stockanalysis_for_symbol(*args, **kwargs)


def refresh_fundamental_betas(*args, **kwargs):
    from .refresh_fundamental_betas import refresh_fundamental_betas as _refresh_fundamental_betas

    return _refresh_fundamental_betas(*args, **kwargs)


def execute_targeted_bvc_fundamental_import(*args, **kwargs):
    from .targeted_bvc_fundamentals import execute_targeted_bvc_fundamental_import as _execute_targeted_bvc_fundamental_import

    return _execute_targeted_bvc_fundamental_import(*args, **kwargs)


def refresh_fundamental_catalysts(*args, **kwargs):
    from .refresh_fundamental_catalysts import refresh_fundamental_catalysts as _refresh_fundamental_catalysts

    return _refresh_fundamental_catalysts(*args, **kwargs)


def compute_stat_arb_for_horizon(*args, **kwargs):
    from .stat_arb import compute_stat_arb_for_horizon as _compute_stat_arb_for_horizon

    return _compute_stat_arb_for_horizon(*args, **kwargs)


def refresh_signal_best_evidence_snapshot(*args, **kwargs):
    from .signal_best_evidence_snapshot import (
        refresh_signal_best_evidence_snapshot as _refresh_signal_best_evidence_snapshot,
    )

    return _refresh_signal_best_evidence_snapshot(*args, **kwargs)


def __getattr__(name):
    # RQ resolves dotted-string jobs by walking attributes from this package in
    # some versions. Keep heavy task modules lazy so API containers can import
    # lightweight enqueue helpers without loading worker-only dependencies.
    if name == "factor_selection_full":
        from importlib import import_module

        return import_module(f"{__name__}.factor_selection_full")
    raise AttributeError(name)


class _DefaultsDiscoveryProxy:
    @staticmethod
    def execute_defaults_discovery(*args, **kwargs):
        return execute_defaults_discovery(*args, **kwargs)


class _RefreshMarketDataProxy:
    @staticmethod
    def refresh_single_symbol(*args, **kwargs):
        return refresh_single_symbol(*args, **kwargs)

    @staticmethod
    def refresh_all_tracked_symbols(*args, **kwargs):
        return refresh_all_tracked_symbols(*args, **kwargs)


defaults_discovery = _DefaultsDiscoveryProxy()
refresh_market_data = _RefreshMarketDataProxy()

__all__ = [
    "execute_run",
    "execute_defaults_discovery",
    "ingest_excel_to_store",
    "refresh_single_symbol",
    "refresh_all_tracked_symbols",
    "execute_strategy_backtest_run",
    "execute_cross_asset_backtest",
    "ingest_macro_series",
    "execute_fundamental_import",
    "refresh_yfinance_universe",
    "refresh_yfinance_for_symbol",
    "refresh_stockanalysis_universe",
    "refresh_stockanalysis_for_symbol",
    "refresh_fundamental_betas",
    "execute_targeted_bvc_fundamental_import",
    "refresh_fundamental_catalysts",
    "compute_stat_arb_for_horizon",
    "refresh_signal_best_evidence_snapshot",
    "defaults_discovery",
    "refresh_market_data",
]
