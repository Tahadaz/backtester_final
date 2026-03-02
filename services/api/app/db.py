from __future__ import annotations

from threading import Lock
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass

_engine = None
_SessionLocal: Optional[sessionmaker] = None
_init_lock = Lock()


def _ensure_session_factory() -> sessionmaker:
    global _engine, _SessionLocal
    if _SessionLocal is not None:
        return _SessionLocal
    with _init_lock:
        if _SessionLocal is None:
            # Lazy init: avoid DB-driver import/network side effects at module import time.
            _engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
            _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _SessionLocal


def get_db():
    SessionLocal = _ensure_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
