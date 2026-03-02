def execute_run(*args, **kwargs):
    from .execute_run import execute_run as _execute_run

    return _execute_run(*args, **kwargs)


def execute_defaults_discovery(*args, **kwargs):
    from .defaults_discovery import execute_defaults_discovery as _execute_defaults_discovery

    return _execute_defaults_discovery(*args, **kwargs)


def ingest_excel_to_store(*args, **kwargs):
    from .ingest_market_data import ingest_excel_to_store as _ingest_excel_to_store

    return _ingest_excel_to_store(*args, **kwargs)


class _DefaultsDiscoveryProxy:
    @staticmethod
    def execute_defaults_discovery(*args, **kwargs):
        return execute_defaults_discovery(*args, **kwargs)


defaults_discovery = _DefaultsDiscoveryProxy()

__all__ = [
    "execute_run",
    "execute_defaults_discovery",
    "ingest_excel_to_store",
    "defaults_discovery",
]
