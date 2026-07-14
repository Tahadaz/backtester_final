# Fix: Technique-tab price plot frozen at May while market data runs to July

Implementation brief — self-contained, written for an implementing agent (Codex). All line numbers verified against the current working tree (branch `feat/sr-walk-forward`).

## Context / root cause (verified, do not re-derive)

The frontend "Technique" tab (`frontend/components/strategy/signal-technique-dashboard.tsx`, default source `wfo`) plots price from `GET /strategy/backtest-mc/best-chart` → `get_signal_best_backtest_chart` (`services/api/app/routers/strategy_signals/_backtest.py:262-290`). That endpoint is **stored-only**: it loads a `SignalBestEvidenceSnapshot` row via `_read_best_evidence_snapshot` (`_evidence.py:1873-1895` — 404 when missing, **never 409s on stale**) and returns `row.chart_payload_jsonb` verbatim.

The payload shape is `{symbol, horizon, variant, market_data_as_of, results: [row, ...]}` where each result row has **parallel arrays** `dates` (list of `"YYYY-MM-DD"` strings, **daily bars for every horizon** — horizon parameterizes signals, not resampling), `close_series` (floats), `position_series` (floats), plus `equity`, `trades`, `trade_ledger`, `metrics`, `mc`, `window_start`, `window_end`, `computed_at`, `data_as_of`, `is_stale`, etc. (built by `get_signal_backtest_results`, `_backtest.py:171-205`).

These arrays are frozen at the `window_end` of the last WFO `signal_backtest_run` (May/June depending on symbol) and only refresh when the weekly signal-backtest batch + best-evidence snapshot materialization rerun. Running WFO alone does not refresh them — hence the deployed app shows WFO evidence through July but a chart ending in May.

**Chosen fix:** at read time in this one endpoint, live-extend `dates`/`close_series` with post-backtest daily closes from market data. Never fabricate backtest output: `equity`, `trades`, `trade_ledger`, `metrics`, `mc` stay frozen; `position_series` is padded with `None`/`null`.

---

## Change 1 — API: extension helper

**File:** `services/api/app/routers/strategy_signals/_backtest.py`

Already imported at module top (do not re-import): `pandas as pd` (line 10), `load_ohlcv_for_symbol` (line 39, from `...market_data_loader`), `_clean_ohlcv` and `logger` (lines 40-49, from `._shared`; `_clean_ohlcv` = `drop_incomplete_ohlcv_rows`, the exact same cleaner the worker used to build the stored series — `services/worker/tasks/signal_backtest_batch.py:202-217` uses `ohlcv_window["Close"]` from `drop_incomplete_ohlcv_rows(load_ohlcv_for_symbol(db, symbol, "1D"))`, so appended closes match the stored series' field and adjustment).

Insert this helper immediately above `get_signal_best_backtest_chart` (currently line 262), i.e. after `build_stored_best_backtest_chart_payload` ends at line 259:

```python
def _extend_chart_payload_with_recent_closes(
    db: Session,
    payload: dict[str, Any],
    *,
    symbol: str,
) -> dict[str, Any]:
    """Append post-backtest daily closes to each stored result row's price line.

    Extends only ``dates``/``close_series`` and pads ``position_series`` with
    None so the frontend's parallel-array slicing stays aligned. ``equity``,
    ``trades``, ``trade_ledger``, ``metrics`` and ``mc`` stay frozen at the
    backtest's window_end — the extension is display-only price context, not a
    recomputed backtest. Copy-on-write: never mutates the stored JSONB payload.
    Best-effort: any failure returns the payload unchanged.
    """
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return payload

    def _row_last_date(row: Any) -> str | None:
        if not isinstance(row, dict):
            return None
        dates = row.get("dates")
        if isinstance(dates, list) and dates and isinstance(dates[-1], str):
            return dates[-1]
        window_end = row.get("window_end")
        return window_end if isinstance(window_end, str) else None

    last_dates = [d for d in (_row_last_date(row) for row in results) if d]
    if not last_dates:
        return payload

    # Cheap staleness guard: skip the OHLCV load entirely when the market
    # store has nothing newer than the oldest chart endpoint. ISO date
    # strings compare correctly as strings.
    from services.api.app.models import MarketDataStore

    mds = db.query(MarketDataStore).filter_by(symbol=symbol, timeframe="1D").first()
    market_as_of = mds.data_as_of.isoformat() if (mds and mds.data_as_of) else None
    if not market_as_of or market_as_of <= min(last_dates):
        return payload

    try:
        ohlcv = _clean_ohlcv(load_ohlcv_for_symbol(db, symbol, "1D"))
        if ohlcv is None or len(ohlcv) == 0 or "Close" not in ohlcv.columns:
            return payload
        close = ohlcv["Close"].copy()
        idx = pd.to_datetime(close.index)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        close.index = idx.normalize()
        close = close[~close.index.duplicated(keep="last")].sort_index().dropna()
    except Exception:
        logger.debug("best-chart price extension failed for %s", symbol, exc_info=True)
        return payload
    if len(close) == 0:
        return payload

    extended_any = False
    max_extended: str | None = None
    new_results: list[Any] = []
    for row in results:
        last_date = _row_last_date(row)
        dates = row.get("dates") if isinstance(row, dict) else None
        closes = row.get("close_series") if isinstance(row, dict) else None
        if (
            not last_date
            or not isinstance(dates, list)
            or not isinstance(closes, list)
            or not dates
            or len(dates) != len(closes)
        ):
            new_results.append(row)
            continue
        tail = close[close.index > pd.Timestamp(last_date)]
        if len(tail) == 0:
            new_results.append(row)
            continue
        new_dates = [ts.strftime("%Y-%m-%d") for ts in tail.index]
        new_closes = [float(v) for v in tail.to_numpy()]
        new_row = dict(row)
        new_row["dates"] = list(dates) + new_dates
        new_row["close_series"] = list(closes) + new_closes
        positions = row.get("position_series")
        if isinstance(positions, list):
            new_row["position_series"] = list(positions) + [None] * len(new_dates)
        new_row["backtest_end_date"] = last_date
        new_row["price_extended_through"] = new_dates[-1]
        new_row["price_extension_bars"] = len(new_dates)
        new_results.append(new_row)
        extended_any = True
        if max_extended is None or new_dates[-1] > max_extended:
            max_extended = new_dates[-1]

    if not extended_any:
        return payload
    return {**payload, "results": new_results, "price_extended_through": max_extended}
```

Notes for the implementer:
- Pad `position_series` with `None`, **not `0`** — `0` would fabricate a position exit at the boundary.
- `tail.to_numpy()` (not `.values`) to keep lint happy if the repo prefers it; either is acceptable if consistent with file style (the file uses `.values` elsewhere — match it if flagged).
- The tz/normalize/dedupe block mirrors the existing `_portfolio_benchmark` pattern in the same file (lines 619-624) — keep it identical in spirit.
- Do NOT extend `equity`, `trades`, `trade_ledger`, `score_series`, `global_score_series`, `metrics`, `mc`.

## Change 2 — API: wire into the endpoint

**File:** same, `get_signal_best_backtest_chart` (lines 262-290). Current tail:

```python
    payload = row.chart_payload_jsonb
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=404,
            detail=f"Stored best backtest chart for {symbol_upper}/{canonical_h} is unavailable.",
        )
    return payload
```

Change only the last line:

```python
    return _extend_chart_payload_with_recent_closes(db, payload, symbol=symbol_upper)
```

**Do NOT touch** `build_stored_best_backtest_chart_payload` (snapshots must stay frozen — extension is read-time only) and **do NOT touch** `get_signal_backtest_results` (`/backtest-mc`; its staleness is already handled via `is_stale` + enqueue-on-miss and the frontend bootstrap re-trigger).

## Change 3 — Frontend: Zod schema (REQUIRED — without this the tab blanks)

**File:** `frontend/lib/api.ts`, `SignalBacktestResultSchema` (lines 5801-5836). `fetchBestSignalBacktestChart` parses the response with `SignalBacktestResponseSchema.parse(...)`; the current `position_series: z.array(z.number()).nullable().optional()` (line 5821) **throws a ZodError on null padding**, and Zod strips unknown keys, so the new metadata fields must be declared.

1. Replace line 5821:
```ts
  position_series: z.array(z.number().nullable()).nullable().optional(),
```
2. Add after line 5823 (`global_score_series`):
```ts
  backtest_end_date: z.string().nullable().optional(),
  price_extended_through: z.string().nullable().optional(),
  price_extension_bars: z.number().nullable().optional(),
```

Two consumers were checked for null-tolerance and need **no** changes:
- `sliceBacktestSeries` (`frontend/components/strategy/signal-technique-dashboard.tsx:408-421`) slices all three arrays with the same start index — padding keeps them length-aligned.
- `signalBacktestHasChartPayload` (`api.ts:5861-5880`) only length-checks.
- `equity` is not plotted by the Technique tab (`PriceSignalsChart` receives only `close/position/dates`; metrics come from `metrics`), so the frozen shorter `equity` is harmless. Indicator overlays are fetched live per date and will cover the extended region automatically.

Important: the stored snapshot rows include `is_stale`, `metrics`, `mc` etc., matching the schema's required fields — the extension copies rows, so nothing required is removed.

## Change 4 — Frontend: guard fallback trade markers against null padding

**File:** `frontend/components/signals/price-signals-chart.tsx`, `createTradeMarkers` (lines 244-271). Currently nulls coerce to `0` (`finiteValue(...) ?? 0`, lines 252-253), which would paint a spurious "Sell" arrow at the first extended bar when no explicit `trade_ledger` is passed (the Technique tab passes `tradeMarkers={visibleLedger}` and uses `createExplicitTradeMarkers` at lines 348-353, but the fallback path must still be safe for other callers).

Replace lines 252-253:

```ts
    const prev = finiteValue(position[index - 1]) ?? 0
    const cur = finiteValue(position[index]) ?? 0
```

with:

```ts
    const prevRaw = finiteValue(position[index - 1])
    const curRaw = finiteValue(position[index])
    if (prevRaw == null || curRaw == null) continue
    const prev = prevRaw
    const cur = curRaw
```

(Padding only occurs at the tail, so this cleanly stops position-derived markers at `backtest_end_date`.)

## Change 5 — Frontend: label the frozen boundary (small, do it)

**File:** `frontend/components/strategy/signal-technique-dashboard.tsx`, header subtitle `<p>` at lines 1014-1019. Append inside the `<p>`, after the `indicatorLoading` line:

```tsx
{backtestRow?.backtest_end_date && backtestRow?.price_extended_through
  ? ` / backtest jusqu'au ${backtestRow.backtest_end_date}, prix jusqu'au ${backtestRow.price_extended_through}`
  : ""}
```

(`backtestRow` is a `SignalBacktestResult`; the fields exist after Change 3. UI copy is French like the surrounding strings; no accents used elsewhere in this file — keep `jusqu'au` as-is.)

No chart shading/vertical line: lightweight-charts has no cheap vertical-line primitive, and trade markers/ledger naturally stop at `backtest_end_date`, which already distinguishes the extended region.

---

## Tests

**File:** `services/api/tests/test_signal_backtest_api.py`. Follow the exact fixture style of `test_signal_best_backtest_chart_reads_stored_payload_without_trigger` (line 889-927): `SignalBestEvidenceSnapshot` + `MarketDataStore` rows in `_FakeDB`, `TestClient(_app(...))`. `dt`, `SignalBestEvidenceSnapshot`, `MarketDataStore`, `_FakeDB`, `_app` are already imported/defined in the file.

Monkeypatch target: `load_ohlcv_for_symbol` is imported into the router module at `_backtest.py:39`, and the router package re-exports names via `services.api.app.routers.strategy_signals`. Patch the `_backtest` module namespace directly:
`monkeypatch.setattr("services.api.app.routers.strategy_signals._backtest.load_ohlcv_for_symbol", fake_loader)`.

### Test A — extension happens, stored row not mutated

```python
def test_signal_best_backtest_chart_extends_price_with_newer_market_data(monkeypatch):
    chart_payload = {
        "symbol": "AAA",
        "horizon": "weekly",
        "variant": "expanded_ta_simple",
        "market_data_as_of": "2026-01-08",
        "results": [
            {
                "source": "wfo",
                "scope": "global",
                "scope_key": "global",
                "status": "succeeded",
                "side_policy": "long_short",
                "cooldown_bars": 0,
                "window_end": "2026-01-08",
                "dates": ["2026-01-07", "2026-01-08"],
                "close_series": [100.0, 101.0],
                "position_series": [0.0, 1.0],
                "equity": [1.0, 1.01],
            }
        ],
    }
    snapshot = SignalBestEvidenceSnapshot(
        symbol="AAA", horizon="weekly", cooldown_bars=0, status="succeeded",
        source="wfo", variant="expanded_ta_simple",
        evidence_payload_jsonb=None, chart_payload_jsonb=chart_payload,
        data_as_of=dt.date(2026, 1, 8), market_data_as_of=dt.date(2026, 1, 8),
    )
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 1, 12))

    index = pd.to_datetime(["2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12"])
    ohlcv = pd.DataFrame(
        {
            "Open": [99.0, 100.5, 101.5, 102.5],
            "High": [101.0, 102.0, 103.0, 104.0],
            "Low": [98.0, 99.5, 100.5, 101.5],
            "Close": [100.0, 101.0, 102.0, 103.0],
            "Volume": [1000.0, 1100.0, 1200.0, 1300.0],
        },
        index=index,
    )
    monkeypatch.setattr(
        "services.api.app.routers.strategy_signals._backtest.load_ohlcv_for_symbol",
        lambda *_a, **_k: ohlcv,
    )

    client = TestClient(_app(_FakeDB({SignalBestEvidenceSnapshot: [snapshot], MarketDataStore: [market_row]})))
    response = client.get("/strategy/backtest-mc/best-chart?symbol=AAA&horizon=weekly")

    assert response.status_code == 200
    body = response.json()
    row = body["results"][0]
    assert row["dates"] == ["2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12"]
    assert row["close_series"] == [100.0, 101.0, 102.0, 103.0]
    assert row["position_series"] == [0.0, 1.0, None, None]
    assert row["equity"] == [1.0, 1.01]              # frozen
    assert row["backtest_end_date"] == "2026-01-08"
    assert row["price_extended_through"] == "2026-01-12"
    assert row["price_extension_bars"] == 2
    assert body["price_extended_through"] == "2026-01-12"
    # copy-on-write: stored JSONB untouched
    assert snapshot.chart_payload_jsonb["results"][0]["dates"] == ["2026-01-07", "2026-01-08"]
    assert snapshot.chart_payload_jsonb["results"][0]["position_series"] == [0.0, 1.0]
```

(`import pandas as pd` — check the test file's imports; add if missing. If `drop_incomplete_ohlcv_rows` requires specific columns, the full OHLCV frame above satisfies it.)

### Test B — no-op when market data is not newer

```python
def test_signal_best_backtest_chart_noop_without_newer_market_data(monkeypatch):
    # same chart_payload/snapshot as Test A, but market data_as_of == last chart date
    ...
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 1, 8))
    monkeypatch.setattr(
        "services.api.app.routers.strategy_signals._backtest.load_ohlcv_for_symbol",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not load OHLCV")),
    )
    ...
    assert response.json() == chart_payload   # verbatim, no metadata fields added
```

### Existing test must stay green unmodified

`test_signal_best_backtest_chart_reads_stored_payload_without_trigger` (line 889) has `MarketDataStore.data_as_of == 2026-01-08 ==` last chart date, so the cheap guard returns the payload verbatim and `load_ohlcv_for_symbol` is never called. Verify it passes without edits. If `_FakeDB`'s `query(MarketDataStore).filter_by(...)` needs the guard's exact filter signature, it already supports it (used at `_backtest.py:113` and in existing tests).

---

## Verification

1. `python -m pytest services/api/tests/test_signal_backtest_api.py -q` — all pass, including the two new tests. (If the host env lacks deps: `docker exec infra-quant_api-1 python -m pytest services/api/tests/test_signal_backtest_api.py -q`.)
2. `cd frontend && npx tsc --noEmit` — no type errors from the schema change.
3. Live check against the running stack (symbol with stale chart, e.g. ATW weekly):
   `curl -s "http://localhost:<api-port>/strategy/backtest-mc/best-chart?symbol=ATW&horizon=weekly"` → expect `results[0].dates[-1]` ≈ latest close date (July), `backtest_end_date` ≈ 2026-06-10, `len(position_series) == len(dates)`, `len(equity) < len(dates)`, trailing `position_series` entries `null`.
4. Browser, Technique tab (source WFO): price line reaches the latest close; buy/sell markers and the trade ledger stop at `backtest_end_date`; subtitle shows "backtest jusqu'au … / prix jusqu'au …"; no Zod errors in console; range buttons (6M/1Y/…) still slice correctly.
5. After code changes: `graphify update .` (per project CLAUDE.md).

## Deployment / operational note (not part of the code change)

The extension fixes the *price line* only; positions/trades remain as-of the last signal-backtest batch. To bring those current on the deployed app after a WFO run, trigger the downstream chain via the ops API: `POST /ops/scheduler/run/weekly_signal_backtest_dispatch`, then `POST /ops/scheduler/run/weekly_signal_best_evidence_snapshot` (endpoint: `services/api/app/routers/ops.py:215-223`). On deployed stacks verify `WORKER_SCHEDULER_ENABLED=1` on the scheduler container so the weekly chain (Sat WFO → Sun backtest → Mon snapshot, `services/api/app/services/scheduler_registry.py:131-172`) actually fires; the local dev stack intentionally leaves it unset.
