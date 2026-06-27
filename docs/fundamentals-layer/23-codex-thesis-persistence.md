# 23 — Codex brief: thesis persistence per symbol (P1)

> **Rubric.** `~/.claude/plugins/cache/claude-for-financial-services/equity-research/0.1.2/skills/thesis-tracker/SKILL.md` and `…/initiating-coverage/SKILL.md`. Open them. They describe what an analyst writes down; this brief is the schema specialisation for our app.
>
> **Why.** Danger D5 in `21-codex-briefs-INDEX.md`. The app today scores companies; it does not record *why* we own them. When Quality drops 20 points in a quarter, we cannot tell whether the thesis is broken or the data is noisy. This brief adds persistence and surfacing for the thesis. It does **not** add automation that rewrites theses from scores — humans write the thesis; the app stores and diffs it.

---

## Files Codex MUST read first

1. `docs/fundamentals-layer/REVIEW_vs_plugin_skills.md` § 6 (thesis / scenarios).
2. `services/api/alembic/versions/a0b1c2d3e4f6_add_fundamental_research_tables.py`, `b1c2d3e4f5a6_add_fundamental_data_source.py`, `c2d3e4f5a6b7_add_fundamental_currency_and_bands.py`, `b0c1d2e3f4a8_add_fundamental_bvc_documents.py` — to know the current research-table set and avoid duplicating tables.
3. `services/api/app/schemas/fundamentals.py` and `services/api/app/routers/fundamentals.py` — current envelope. Thesis fields are *additive*.
4. `core/quant_core/fundamentals/domain.py` — current dataclasses.
5. `docs/fundamentals-layer/20-claude-design-handoff.md` — the Thèse tab spec in the UI. Read which fields the design already names; reuse those names verbatim.

If the design doc already names fields (`core_thesis`, `bullish_drivers`, `bearish_drivers`, etc.) Codex MUST use those names. Do not invent parallel field names.

---

## Scope

A single table that stores one *current* thesis row per symbol, plus an append-only history of revisions. CRUD endpoints behind the existing auth path. No auto-generation. No NLP on scores.

Out of scope: catalyst calendar (brief 24), pillar history (brief 28), scenarios (brief 25). If Codex finds itself wanting to add catalysts here, stop — that goes in brief 24.

---

## Data model

New Alembic migration. `down_revision` = current head (Codex verifies).

### Table `fundamental_thesis`

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | BIGSERIAL | PK |  |
| `symbol` | TEXT | NOT NULL | FK or check against `stock_master.symbol` if that's the existing pattern — Codex matches what other fundamental tables do. |
| `as_of` | DATE | NOT NULL | Date the thesis became current. |
| `direction` | TEXT | NOT NULL | One of `long` / `short` / `pair_long` / `pair_short` / `avoid`. |
| `conviction` | TEXT | NOT NULL | One of `high` / `medium` / `low`. |
| `core_thesis` | TEXT | NOT NULL | 1–3 sentence narrative. Free text. Markdown allowed. |
| `bullish_drivers` | JSONB | NOT NULL | Array of `{title: str, detail: str, pillar: str | None}`. `pillar` is one of the six pillar names when applicable. |
| `bearish_drivers` | JSONB | NOT NULL | Same shape as above (risks / refutations). |
| `target_price` | DOUBLE PRECISION | NULL | Analyst target. Currency same as `EnsembleResult.currency`. |
| `target_horizon_months` | INT | NULL | E.g. 12. |
| `stop_price` | DOUBLE PRECISION | NULL | Hard exit trigger. |
| `invalidation_conditions` | JSONB | NOT NULL DEFAULT `'[]'` | Array of `{condition: str, breached: bool}`. UI shows these on the Thèse tab. |
| `linked_catalyst_ids` | JSONB | NOT NULL DEFAULT `'[]'` | Array of int — points at brief 24's `fundamental_catalyst.id`. NOT a FK (catalysts can be deleted); UI tolerates orphans. |
| `created_by` | TEXT | NOT NULL | Existing user-identity convention — Codex reads how other tables do it. |
| `created_at` | TIMESTAMP | NOT NULL DEFAULT now() |  |
| `is_current` | BOOLEAN | NOT NULL DEFAULT true | The history pattern (below) flips old rows to false. |

Indexes:
- `UNIQUE (symbol) WHERE is_current = true` — at most one current thesis per symbol (PostgreSQL partial unique index).
- `(symbol, created_at DESC)`.

### History pattern (no separate history table)

On every update via the API:
1. Insert the new row with `is_current = true`.
2. In the same transaction, `UPDATE fundamental_thesis SET is_current = false WHERE symbol = :sym AND id != :new_id;`.

This gives a free append-only audit log without a second table. The "latest thesis" read becomes `SELECT … WHERE is_current = true AND symbol = :sym`.

### What this table does NOT store

- Pillar scores (those are computed and live in their own snapshot — joined by `symbol`).
- Catalyst event details (those live in brief 24's table — only `linked_catalyst_ids` here).
- Fair-value bands (those live on `EnsembleResult`).

Do not duplicate.

---

## Domain dataclass (no engine change)

Add to `core/quant_core/fundamentals/domain.py`:

```python
@dataclass(frozen=True)
class ThesisDriver:
    title: str
    detail: str
    pillar: str | None  # one of: value, quality, growth, risk, cash_flow, health, or None

@dataclass(frozen=True)
class InvalidationCondition:
    condition: str
    breached: bool

@dataclass(frozen=True)
class Thesis:
    symbol: str
    as_of: str                # ISO date
    direction: str
    conviction: str
    core_thesis: str
    bullish_drivers: list[ThesisDriver]
    bearish_drivers: list[ThesisDriver]
    target_price: float | None
    target_horizon_months: int | None
    stop_price: float | None
    invalidation_conditions: list[InvalidationCondition]
    linked_catalyst_ids: list[int]
    created_by: str
    created_at: str
    is_current: bool
```

`Thesis` is a domain object. The valuation engine MUST NOT import it. It exists for the API layer.

---

## API surface

Add to `services/api/app/schemas/fundamentals.py`:
- `ThesisIn` (no `id`, no `created_at`, no `is_current`).
- `ThesisOut` (full).
- `ThesisHistoryOut(items: list[ThesisOut])`.

Add to `services/api/app/routers/fundamentals.py`. All endpoints reuse the existing auth/tenant decorator pattern in that file:

| Method | Path | Body | Returns |
|---|---|---|---|
| `GET` | `/fundamentals/{symbol}/thesis` |  — | `ThesisOut` (the current) or 404. |
| `GET` | `/fundamentals/{symbol}/thesis/history` |  — | `ThesisHistoryOut` (DESC by `created_at`, max 50). |
| `POST` | `/fundamentals/{symbol}/thesis` | `ThesisIn` | `ThesisOut`. Validates input (see below), creates new row, flips prior to `is_current=false`, returns the new row. |
| `DELETE` | `/fundamentals/{symbol}/thesis` |  — | 204. Soft-delete by inserting a tombstone row with `direction='avoid'`, `conviction='low'`, `core_thesis='(removed)'` and flipping the prior. **Never hard-delete history.** |

### Validation rules in `ThesisIn`

- `direction` ∈ enum above.
- `conviction` ∈ enum above.
- `core_thesis` length 30–2000 chars. Strip control chars.
- `bullish_drivers` and `bearish_drivers` each have 1–6 items; per-item `title` ≤ 100 chars, `detail` ≤ 600 chars.
- `target_price > 0` if present; `target_horizon_months in [1..60]` if present; `stop_price > 0` if present.
- If both `target_price` and `stop_price` set, for `direction='long'` require `target_price > current_price > stop_price` (look up `current_price` from the latest `EnsembleResult` for the symbol; if absent, skip this rule and emit a `warnings` field on the response).

Validation failures → 422 with the existing error envelope.

### Integration with the symbol envelope

The existing per-symbol envelope endpoint (Codex names it after reading the router) gains an additive `thesis: ThesisOut | None` field. Other fields unchanged.

---

## UI spec update (markdown only)

Update `docs/fundamentals-layer/20-claude-design-handoff.md` Thèse tab section: add bullets describing the Edit / Save flow, the side-by-side diff against the prior `is_current=false` row, and the invalidation chips. **No frontend code in this brief.**

---

## Tests

`services/api/tests/test_fundamentals_thesis.py`:

| Test | Asserts |
|---|---|
| `test_post_thesis_creates_current_row` | First POST → 1 row, `is_current=true`. |
| `test_second_post_flips_prior` | Second POST → 2 rows, only newest is current. |
| `test_get_returns_current_only` | GET returns the newest, history endpoint returns both. |
| `test_validation_rejects_short_core_thesis` | 29-char `core_thesis` → 422. |
| `test_validation_rejects_inverted_target_stop_for_long` | `target < stop` for long → 422. |
| `test_validation_warns_when_current_price_unknown` | No `EnsembleResult` → 200 with `warnings` present. |
| `test_delete_writes_tombstone` | DELETE keeps history; current row is the tombstone. |
| `test_only_one_current_per_symbol_invariant` | Direct DB inspection: partial unique index honoured. |

---

## Open questions Codex flags back instead of guessing

- Tenant / multi-user model: if the existing router has a `user_id` or `org_id` context, mirror it on `fundamental_thesis`. If it does NOT, do **not** invent one — file the question here.
- Currency on `target_price` / `stop_price`: if `EnsembleResult.currency` is per-symbol, the thesis row inherits it implicitly (no new column). If the existing `Bands` migration stores a per-row currency on related tables, mirror that pattern.

---

## Acceptance criteria

- [ ] All thesis API tests green.
- [ ] `python -m pytest core/tests/ services/api/tests/ -q` green overall.
- [ ] Migration upgrade + downgrade clean.
- [ ] Partial unique index `UNIQUE (symbol) WHERE is_current = true` exists in PG (verify with `\d+ fundamental_thesis` or pg_indexes query).
- [ ] `docs/fundamentals-layer/20-claude-design-handoff.md` updated with the Edit/Save/diff flow bullets.
- [ ] No change to any valuation, scoring, or ensemble output.
