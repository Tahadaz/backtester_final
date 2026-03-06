from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import numpy as np

from services.api.app.json_sanitize import sanitize_json_compatible
from services.api.app.schemas.runs import MaterializeStrategyDetailsResponse


def _contains_numpy_array(value: object) -> bool:
    if isinstance(value, np.ndarray):
        return True
    if isinstance(value, list):
        return any(_contains_numpy_array(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_numpy_array(item) for item in value.values())
    return False


def test_sanitize_materialized_strategy_details_payload() -> None:
    raw_payload = {
        "run_id": uuid4(),
        "symbol": "AAPL",
        "strategy_kind": "sma_cross",
        "metrics": {
            "sharpe": np.float64(1.23),
            "equity_curve": np.array([100_000.0, 101_250.5, 100_900.0]),
            "nested": {"max_drawdown": np.float32(0.145)},
        },
        "trade_performance": [
            {
                "n_trades": np.int64(12),
                "avg_return": np.float64(0.017),
                "percentiles": np.array([0.05, 0.5, 0.95]),
            }
        ],
        "trade_ledger": [
            {
                "entry_price": np.float64(182.3),
                "exit_price": np.float64(185.8),
                "pnl_path": np.array([0.0, 1.2, 3.5]),
            }
        ],
        "plots": {
            "price_indicators_trades": {
                "data": [
                    {"x": np.array([1, 2, 3]), "y": np.array([10.0, 11.0, 12.5])},
                ],
            }
        },
        "signal_label": "BUY",
        "signal_today": np.float64(1.0),
        "signal_date": datetime(2026, 3, 4, 12, 30, tzinfo=timezone.utc),
    }

    sanitized = sanitize_json_compatible(raw_payload)

    assert not _contains_numpy_array(sanitized)
    validated = MaterializeStrategyDetailsResponse.model_validate(sanitized)
    assert validated.run_id == raw_payload["run_id"]
    assert validated.symbol == "AAPL"
    assert validated.strategy_kind == "sma_cross"
