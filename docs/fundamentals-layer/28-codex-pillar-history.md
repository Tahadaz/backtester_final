# 28 — Codex brief: pillar-score history & trend (P2)

> **Rubric.** `~/.claude/plugins/cache/claude-for-financial-services/equity-research/0.1.2/skills/thesis-tracker/SKILL.md` § thesis scorecard.
>
> **Why.** Danger D9. Pillar scores are stateless today. Quality drifting from 78 → 52 over four quarters does not flag anywhere. Brief 28 stores a snapshot per import run and surfaces a per-pillar trend (`on_track` / `behind` / `watch`).

---

## Files Codex MUST read first

1. `core/quant_core/fundamentals/scoring.py` — to know the six pillar keys (`value`, `quality`, `growth`, `risk`, `cash_flow`, `health`) and the `overall_score` formula. The history schema mirrors those keys exactly — do not invent new pillar names.
2. The fundamental Alembic migration chain (see brief 21 § "Read these first") — for the `fundamental_import_run` table's id type / FK pattern.
3. `services/api/app/schemas/fundamentals.py` — for the existing pillar-score response shape.

---

## Scope

A `fundamental_pillar_score_history` table, the worker code to write a row on each successful import, an API endpoint for the per-symbol series, and a small trend classifier.

Out of scope: alerting / notification on trend breaches.

---

## Data model

### Table `fundamental_pillar_score_history`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | BIGSERIAL | PK |  |
| `symbol` | TEXT | NOT NULL |  |
| `import_run_id` | BIGINT | NOT NULL FK to `fundamental_import_run.id` |  |
| `as_of` | DATE | NOT NULL | The `latest_statement_year` end-of-year as a date, or the import date — Codex picks one based on what the workbook ingest treats as the "as of" today. Document the choice. |
| `value_score` | DOUBLE PRECISION | NULL |  |
| `quality_score` | DOUBLE PRECISION | NULL |  |
| `growth_score` | DOUBLE PRECISION | NULL |  |
| `risk_score` | DOUBLE PRECISION | NULL |  |
| `cash_flow_score` | DOUBLE PRECISION | NULL |  |
| `health_score` | DOUBLE PRECISION | NULL |  |
| `overall_score` | DOUBLE PRECISION | NULL |  |
| `pillar_coverage` | JSONB | NULL | Mirror of `snapshot.coverage` for the six pillars — for "how many metrics fed this score". |
| `created_at` | TIMESTAMP | NOT NULL DEFAULT now() |  |

Indexes: `(symbol, as_of DESC)`; `UNIQUE (symbol, import_run_id)`.

---

## Trend classifier (pure function)

```python
def classify_pillar_trend(
    history: list[dict],         # newest-first, max ~12 rows
    pillar: str,
) -> str:                        # "on_track" | "watch" | "behind" | "insufficient_data"
```

Rules (deliberately simple — Codex MUST NOT add smoothing / ML beyond this):
- If fewer than 3 historical rows for the pillar → `insufficient_data`.
- Compute the slope of the pillar over the last 4 rows (or fewer if 3) by least-squares.
- If `latest_score >= 70` AND `slope >= -2 pts per period` → `on_track`.
- Else if `slope <= -5 pts per period` OR `latest_score < 40` → `behind`.
- Else → `watch`.

Codex documents these constants as module-level so they are tunable in one place; do not scatter `70`, `40`, `-2`, `-5` literals.

This function is pure and lives in `core/quant_core/fundamentals/trends.py` (new file). It is unit-tested independent of the DB.

---

## Worker integration

The pillar-history row is written in the same transaction as the snapshot persistence. Reuse the existing import-run id; do NOT open a separate transaction. If the snapshot write succeeds but the history write fails, the whole import rolls back.

---

## API surface

| Method | Path | Notes |
|---|---|---|
| `GET` | `/fundamentals/{symbol}/pillar-history?limit=12` | Returns newest-first, capped at 24. Schema: `{symbol, items: list[PillarHistoryRow], trend: dict[pillar, str]}`. |

`PillarHistoryRow` = the table columns minus internals.

The per-symbol envelope endpoint **does not** include the history by default (it would bloat). It DOES include the `trend: dict[pillar, str]` summary (six entries) so the Quality tab can show the trend chip without a second request.

---

## UI spec update

Update `docs/fundamentals-layer/20-claude-design-handoff.md` Quality tab:
- Each pillar tile carries a trend chip: green `On Track`, amber `Watch`, red `Behind`, grey `—` (insufficient data).
- A small sparkline (last 8 points) per pillar inside the tile.

No frontend code in this brief.

---

## Tests

`core/tests/test_pillar_trend.py`:
- `test_insufficient_data_with_two_rows` → `insufficient_data`.
- `test_on_track_high_and_flat` — latest 75, slope -1 → `on_track`.
- `test_behind_steep_decline` — slope -8 → `behind`.
- `test_behind_low_score_regardless_of_slope` — latest 35, slope 0 → `behind`.
- `test_watch_middle_case` — latest 60, slope -3 → `watch`.

`services/api/tests/test_fundamentals_pillar_history_api.py`:
- Seed 5 historical rows via direct DB inserts (or the worker call), GET endpoint, assert order and shape.
- Assert envelope endpoint exposes the `trend` summary.

---

## Acceptance criteria

- [ ] Tests green; full suite green.
- [ ] Migration round-trip clean.
- [ ] An end-to-end import produces exactly one history row per (symbol, import_run_id).
- [ ] `GET /fundamentals/{symbol}/pillar-history` returns 200 with the shape above.
- [ ] The envelope `trend` field uses the same enum strings.
