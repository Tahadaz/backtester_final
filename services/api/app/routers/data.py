from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from services.api.app.services.catalog import list_tickers, resolve_ticker
from services.api.app.db import get_db

router = APIRouter(prefix="/data", tags=["data"])

@router.get("/tickers")
def get_tickers(freq: str = "1D", session: Session = Depends(get_db)):
    return {"items": list_tickers(session, freq=freq)}

@router.get("/tickers/{ticker}")
def get_ticker(ticker: str, freq: str = "1D", session: Session = Depends(get_db)):
    row = resolve_ticker(session, ticker=ticker, freq=freq)
    if not row:
        raise HTTPException(status_code=404, detail="ticker_not_found")
    return row
