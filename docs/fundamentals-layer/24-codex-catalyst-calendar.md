# 24 — Codex brief: catalyst calendar (P1)

> **Rubric.** `~/.claude/plugins/cache/claude-for-financial-services/equity-research/0.1.2/skills/catalyst-calendar/SKILL.md`. Open it. It describes an analyst's coverage-wide catalyst register. This brief is the schema specialisation.
>
> **Why.** Danger D6. Today the engine has no notion of "earnings on Thursday". A score refresh the day before an event is treated like any other day. Adding the calendar lets every other surface — thesis, morning note (brief 29), pillar trends (brief 28) — reference upcoming events.

---

## Files Codex MUST read first

1. `docs/fundamentals-layer/REVIEW_vs_plugin_skills.md` § 7.
2. `services/api/alembic/versions/a0b1c2d3e4f6_add_fundamental_research_tables.py` and siblings — do not duplicate any existing event-like table.
3. `services/worker/tasks/fundamentals.py`, `targeted_bvc_fundamentals.py`, `refresh_yfinance_fundamentals.py` — worker pattern for periodic ingest.
4. `core/quant_core/fundamentals/domain.py` — current dataclasses.
5. `docs/fundamentals-layer/20-claude-design-handoff.md` — the existing references to catalysts in the Thèse tab; reuse field names.

---

## Scope

A `fundamental_catalyst` table, a worker task that periodically populates earnings dates from yfinance (and is **extensible** to BVC / manual entry), and a calendar API plus a per-symbol "upcoming catalysts" list.

Out of scope for this brief: pulling from FactSet / Bloomberg (D6 follow-up), expected-impact NLP, automatic positioning recommendations.

---

## Data model

### Table `fundamental_catalyst`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | BIGSERIAL | PK |  |
| `symbol` | TEXT | NOT NULL |  |
| `event_type` | TEXT | NOT NULL CHECK in `('earnings','dividend','ex_dividend','agm','guidance','regulatory','product','m_and_a','split','other')` | Extend list only via migration. |
| `event_date` | DATE | NOT NULL | Calendar date of the event. |
| `event_date_confidence` | TEXT | NOT NULL CHECK in `('confirmed','estimated','rumour')` | yfinance dates default to `estimated` until inside the company's announcement window. |
| `impact_tier` | TEXT | NOT NULL CHECK in `('high','moderate','routine')` |  |
| `expected_direction` | TEXT | NULL CHECK in `('positive','negative','neutral',NULL)` |  |
| `title` | TEXT | NOT NULL |  |
| `notes` | TEXT | NULL | Markdown allowed. |
| `source` | TEXT | NOT NULL | `'yfinance'` / `'bvc'` / `'manual:<user>'` / `'consensus'`. |
| `source_payload` | JSONB | NULL | Raw provider payload for audit. |
| `created_at` | TIMESTAMP | NOT NULL DEFAULT now() |  |
| `updated_at` | TIMESTAMP | NOT NULL DEFAULT now() |  |
| `is_active` | BOOLEAN | NOT NULL DEFAULT true | Soft-deletes (e.g. event was cancelled / rescheduled — the new event is a new row referencing this one via `superseded_by_id`). |
| `superseded_by_id` | BIGINT | NULL FK to `fundamental_catalyst.id` |  |

Indexes:
- `(symbol, event_date)`
- `(event_date) WHERE is_active = true` — for the global calendar view.
- `(symbol) WHERE is_active = true AND event_date >= current_date` — for per-symbol upcoming.

### Idempotency rule for worker ingest

When the worker reads yfinance and writes a row, the upsert key is `(symbol, event_type, event_date, source)`. If the row exists and `event_date_confidence` differs, update the existing row (`updated_at = now()`). If `event_date` itself differs by ≤ 14 days, treat as the same event and update; if > 14 days, mark the prior row `is_active=false`, `superseded_by_id=new.id`. **Codex implements this in the worker; do NOT push it into the migration.**

---

## Worker task

Add `services/worker/tasks/refresh_fundamental_catalysts.py`:

- Iterates the universe (Codex reads how `refresh_yfinance_fundamentals.py` enumerates symbols and reuses that helper).
- For each symbol, calls `yfinance.Ticker(sym).calendar` and `…ticker.dividends.tail(N)`. Wrap in `try/except` — yfinance is flaky.
- Normalises into `fundamental_catalyst` rows with `source='yfinance'`, default `impact_tier='moderate'` for earnings, `'routine'` for dividends.
- Honours the idempotency rule above.
- Logs counts (created / updated / superseded) per run.
- Does **not** hit yfinance from the API process. Schedulable via the existing Celery / RQ pattern (Codex matches the existing worker registration).

Add a thin manual-entry path: `POST /fundamentals/{symbol}/catalysts` (see API surface) writes a row with `source='manual:<user>'` and full validation.

---

## Domain dataclasses

Add to `core/quant_core/fundamentals/domain.py`:

```python
@dataclass(frozen=True)
class Catalyst:
    id: int
    symbol: str
    event_type: str
    event_date: str           # ISO date
    event_date_confidence: str
    impact_tier: str
    expected_direction: str | None
    title: str
    notes: str | None
    source: str
    created_at: str
    updated_at: str
    is_active: bool
    superseded_by_id: int | None
```

---

## API surface

Schemas:
- `CatalystIn` — for manual creation. Required: `event_type`, `event_date`, `impact_tier`, `title`. Optional: rest.
- `CatalystOut` — mirrors `Catalyst`.
- `CatalystCalendarOut` — `{from_date: date, to_date: date, items: list[CatalystOut]}`.

Endpoints (under existing auth):

| Method | Path | Notes |
|---|---|---|
| `GET` | `/fundamentals/calendar?from=YYYY-MM-DD&to=YYYY-MM-DD&impact_tier=high,moderate&symbol=ATW` | Filterable; defaults: `from=today`, `to=today+30d`, all tiers. Cap at 500 rows; if more, respond with `truncated=true` and the cap. |
| `GET` | `/fundamentals/{symbol}/catalysts?upcoming_only=true` | Per-symbol. Default upcoming-only, last 90 days when `upcoming_only=false`. |
| `POST` | `/fundamentals/{symbol}/catalysts` | Manual create. Body = `CatalystIn`. |
| `PATCH` | `/fundamentals/catalysts/{id}` | Update `event_date` / `impact_tier` / `notes`. Triggers supersession only if `event_date` changes by > 14 days. |
| `DELETE` | `/fundamentals/catalysts/{id}` | Soft-delete (`is_active=false`). Never hard-delete. |

---

## Linkage with thesis (brief 23)

`fundamental_thesis.linked_catalyst_ids` references `fundamental_catalyst.id`. The thesis surface displays each linked catalyst's title + date + impact chip. If a catalyst is soft-deleted, the thesis surface shows it greyed with `(annulé)`. No DB-level FK — read-side tolerance only.

---

## UI spec update

Update `docs/fundamentals-layer/20-claude-design-handoff.md`:
- New "Calendrier" block at the universe sidebar level: a flat list of the next 30 days, grouped by week, coloured by `impact_tier`.
- Thèse tab gains a "Catalyseurs liés" sub-block referencing brief 23.

No frontend code in this brief.

---

## Tests

`services/api/tests/test_fundamentals_catalysts.py`:

| Test | Asserts |
|---|---|
| `test_post_catalyst_creates_row` | Manual POST creates one active row. |
| `test_get_calendar_filters_by_date_range` | Two rows seeded; calendar GET with narrow range returns one. |
| `test_get_calendar_filters_by_impact_tier` | Tier filter works. |
| `test_patch_within_14d_updates_same_row` | PATCH date by +3d → same row updated, no new row. |
| `test_patch_beyond_14d_supersedes` | PATCH date by +30d → new row, prior `is_active=false`, `superseded_by_id` set. |
| `test_delete_is_soft` | DELETE keeps row, `is_active=false`. |
| `test_calendar_truncation_flag` | Seed > 500 rows, response has `truncated=true`. |

`core/tests/test_catalyst_worker_normalisation.py` (pure-unit, mock yfinance return value):
- `test_yfinance_earnings_row_normalised` — known yfinance shape → expected `Catalyst` fields.
- `test_yfinance_missing_calendar_does_not_raise` — empty / `None` → zero rows, no exception.

---

## Acceptance criteria

- [ ] Migration upgrade / downgrade clean.
- [ ] All catalyst tests green; full suite green.
- [ ] Worker task registers in the existing scheduler and can be run on demand (`python -m services.worker.tasks.refresh_fundamental_catalysts --symbols ATW`).
- [ ] One manual end-to-end: POST a manual catalyst on a known symbol, GET the calendar in a date range that covers it, assert it shows up.
- [ ] No change to valuation or scoring output.
