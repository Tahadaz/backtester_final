from __future__ import annotations

import datetime as dt

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scripts.seed_fundamental_demo import _ensure_stock_rows
from services.api.app import models


def test_seed_fixture_does_not_overwrite_existing_bourse_share_count() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    models.StockMaster.__table__.create(engine)
    models.MarketDataStore.__table__.create(engine)

    try:
        with SessionLocal() as db:
            db.add(
                models.StockMaster(
                    symbol="MNG",
                    display_name="Managem",
                    sector="Mines",
                    market_region="masi",
                    is_active=True,
                    shares_outstanding=11_864_676,
                    shares_source="bourse_direct",
                    shares_as_of=dt.date(2026, 6, 2),
                )
            )
            db.commit()

            _ensure_stock_rows(
                db,
                [
                    {
                        "symbol": "MNG",
                        "name": "Managem",
                        "sector": "Mines",
                        "shares": 10_000_000,
                        "price": 2_750.0,
                    }
                ],
            )
            db.commit()

            stock = db.query(models.StockMaster).filter(models.StockMaster.symbol == "MNG").one()
            assert stock.shares_outstanding == 11_864_676
            assert stock.shares_source == "bourse_direct"
            assert stock.shares_as_of == dt.date(2026, 6, 2)
    finally:
        engine.dispose()
