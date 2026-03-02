from __future__ import annotations

from fastapi import Header, HTTPException

from .config import settings


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = settings.API_KEY.strip()
    if not expected:
        return
    if x_api_key == expected:
        return
    raise HTTPException(status_code=401, detail="invalid or missing API key")
