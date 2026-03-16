from __future__ import annotations
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware


from . import auth
from .routers import datasets, results, runs, market_data, data, leaderboard, trials, snapshot, defaults, strategy_signals

def create_app() -> FastAPI:
    app = FastAPI(title="Quant API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # routers – auth is a no-op when API_KEY env var is unset
    app.include_router(runs.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(datasets.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(results.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(market_data.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(defaults.router, dependencies=[Depends(auth.require_api_key)])
    app.include_router(data.router)
    app.include_router(leaderboard.router)
    app.include_router(trials.router)
    app.include_router(snapshot.router)
    app.include_router(strategy_signals.router)


    @app.get("/health")
    def health():
        return {"ok": True}

    return app

app = create_app()
