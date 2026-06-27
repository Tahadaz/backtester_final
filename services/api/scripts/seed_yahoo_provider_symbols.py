from __future__ import annotations

from sqlalchemy.orm import Session

from app import models
from app.db import SessionLocal


def _default_yahoo_symbol(symbol: str, market_region: str | None) -> str:
    # US tickers usually match the canonical app symbol. European/Asian rows
    # should be verified by an admin after seeding because exchange suffixes vary.
    return symbol if market_region == "us" else symbol


def seed_yahoo_provider_symbols(db: Session) -> int:
    rows = (
        db.query(models.StockMaster)
        .filter(
            models.StockMaster.is_active.is_(True),
            models.StockMaster.market_region.in_(["us", "european", "asian"]),
        )
        .order_by(models.StockMaster.symbol.asc())
        .all()
    )
    created = 0
    for stock in rows:
        exists = (
            db.query(models.ProviderSymbolMap.id)
            .filter(models.ProviderSymbolMap.symbol == stock.symbol, models.ProviderSymbolMap.provider == "yahoo")
            .first()
            is not None
        )
        if exists:
            continue
        db.add(
            models.ProviderSymbolMap(
                symbol=stock.symbol,
                provider="yahoo",
                provider_symbol=_default_yahoo_symbol(stock.symbol, stock.market_region),
                confidence=0.9 if stock.market_region == "us" else 0.5,
                is_verified=False,
                override_reason="Seeded for fundamental yfinance coverage; verify non-US suffixes before production use.",
            )
        )
        created += 1
    db.commit()
    return created


def main() -> None:
    db = SessionLocal()
    try:
        created = seed_yahoo_provider_symbols(db)
        print(f"created_yahoo_provider_symbol_rows={created}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
