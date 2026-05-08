from __future__ import annotations

from fastapi import Header, HTTPException

from .config import settings


def require_auth(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    api_key = settings.API_KEY.strip()
    jwt_secret = settings.INTERNAL_JWT_SECRET.strip()

    # Dev mode: no auth configured at all
    if not api_key and not jwt_secret:
        return

    # API-key path (used by the Next.js proxy, which injects API_KEY server-side)
    if api_key and x_api_key == api_key:
        return

    # Bearer JWT path (forward-compat: used once Auth.js session minting is wired)
    if jwt_secret and authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        try:
            from jose import jwt  # type: ignore[import]
            jwt.decode(token, jwt_secret, algorithms=["HS256"])
            return
        except Exception:
            raise HTTPException(status_code=401, detail="invalid token")

    raise HTTPException(status_code=401, detail="missing or invalid credentials")


# Backward-compatible alias — existing routers use Depends(auth.require_api_key)
require_api_key = require_auth
