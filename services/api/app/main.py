from __future__ import annotations
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from . import auth
from .config import settings
from .freshness import FreshnessHeadersMiddleware


from .routers import (
    analytics,
    bloomberg_bridge,
    dashboard_data,
    dashboard_indices,
    data,
    datasets,
    defaults,
    factor_selection,
    factor_signals,
    fundamentals,
    historical_portfolio_backtest,
    leaderboard,
    market_data,
    market_data_indices,
    ops,
    results,
    runs,
    snapshot,
    strategy,
    strategy_backtest_runs,
    strategy_signals,
    trials,
    value_signal,
    wfo_signals,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    yield
    stop_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(title="Quant API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Computed-At", "X-Upstream-Rev", "X-Cache"],
    )
    app.add_middleware(FreshnessHeadersMiddleware)

    # routers – auth is a no-op when API_KEY env var is unset
    app.include_router(runs.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(datasets.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(results.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(market_data.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(market_data_indices.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(ops.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(bloomberg_bridge.app_router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(bloomberg_bridge.bridge_router)
    app.include_router(defaults.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(analytics.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(value_signal.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(factor_signals.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(factor_selection.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(fundamentals.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(data.router)
    app.include_router(dashboard_indices.router)
    app.include_router(dashboard_data.router)
    app.include_router(leaderboard.router)
    app.include_router(trials.router)
    app.include_router(snapshot.router)
    app.include_router(strategy_signals.router)
    app.include_router(strategy.router)
    app.include_router(strategy_backtest_runs.router)
    app.include_router(historical_portfolio_backtest.router)
    app.include_router(dashboard_indices.router)
    app.include_router(wfo_signals.router)


    @app.get("/health")
    def health():
        return {"ok": True}

    return app

app = create_app()
