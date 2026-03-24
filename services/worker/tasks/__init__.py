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
    "defaults_discovery",
    "refresh_market_data",
]
