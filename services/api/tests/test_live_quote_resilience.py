from __future__ import annotations

import pandas as pd

from services.api.app.services import bourse_live_quotes as quotes


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str):
        return self.values.get(key)

    def setex(self, key: str, _seconds: int, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)

    def close(self) -> None:
        pass


class _FakeSession:
    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"Open": [1.0], "High": [2.0], "Low": [1.0], "Close": [1.5], "Volume": [10.0]},
        index=pd.to_datetime(["2026-07-10"]),
    )


def test_primary_failure_opens_hour_cooldown_and_uses_bkb(monkeypatch) -> None:
    redis = _FakeRedis()
    calls: list[str] = []

    def fake_load(provider: str, _symbol: str):
        calls.append(provider)
        if provider == quotes.CASABLANCA_PROVIDER:
            raise TimeoutError("provider timed out")
        return _frame()

    monkeypatch.setattr(quotes, "_redis", lambda: redis)
    monkeypatch.setattr(quotes, "_load_one", fake_load)
    monkeypatch.setattr(quotes, "_upsert_quote_from_frame", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(quotes, "_append_quote_history", lambda *_args, **_kwargs: None)

    result = quotes.refresh_live_quotes(["ATW"], session_factory=_FakeSession)

    assert result["refreshed"] == ["ATW"]
    assert result["providers"] == {"ATW": quotes.BKB_PROVIDER}
    assert calls == [quotes.CASABLANCA_PROVIDER, quotes.BKB_PROVIDER]
    assert redis.get(quotes._provider_key(quotes.CASABLANCA_PROVIDER))

    calls.clear()
    result = quotes.refresh_live_quotes(["ATW"], session_factory=_FakeSession)
    assert result["refreshed"] == ["ATW"]
    assert calls == [quotes.BKB_PROVIDER]


def test_unmapped_bkb_symbol_uses_symbol_cooldown(monkeypatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(quotes, "_redis", lambda: redis)
    monkeypatch.setattr(quotes, "_load_one", lambda *_args: None)

    result = quotes.refresh_live_quotes(["INSTRUMENT"], session_factory=_FakeSession)

    assert result["refreshed"] == []
    assert result["failures"] == {"INSTRUMENT": "all_providers_unavailable_or_cooled_down"}
    assert redis.get(quotes._symbol_key(quotes.BKB_PROVIDER, "INSTRUMENT"))
