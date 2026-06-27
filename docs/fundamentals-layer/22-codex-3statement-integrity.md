# 22 — Codex brief: 3-statement integrity & projected statements (P1)

> **Rubric.** `~/.claude/plugins/cache/claude-for-financial-services/financial-analysis/0.1.1/skills/3-statement-model/SKILL.md` and `…/audit-xls/SKILL.md`. Open them. The brief below is the *project-specific specialisation* of those rubrics — where the rubric and this brief disagree, this brief wins.
>
> **Why this brief exists.** The fundamental layer ingests historicals from yfinance and a workbook, then drops straight into valuation. Nothing in between checks that the three statements **cohere**. That is dangers D1, D2, D3 in `21-codex-briefs-INDEX.md`. Until this brief is implemented, the engine can silently consume a non-balancing balance sheet and produce a confident-looking fair value. That is the single most important hole to plug.

---

## Files Codex MUST read first (anti-hallucination gate)

Codex MUST open each file below, confirm the symbols and line numbers cited in this brief still exist, and quote any drift back in its PR description. **Do not write code before this gate is passed.**

1. `core/quant_core/fundamentals/domain.py` — entire file. The dataclasses are frozen; new ones must be added at the bottom and must not redefine fields that already exist on `AnnualMetricRow` / `FundamentalSnapshot`.
2. `core/quant_core/fundamentals/normalize_yfinance.py` — the canonical metric names that come out of yfinance. The integrity checks below MUST use those exact names; do not invent new metric vocabulary.
3. `core/quant_core/fundamentals/workbook.py` — the canonical metric vocabulary expected from the Excel ingest. Same rule: integrity checks use the existing names.
4. `core/quant_core/fundamentals/valuation.py` lines 1–50 (constants), and the FCFF / FCFE / RI / DDM functions reachable from `compute_symbol_valuations` at line 814 and `compute_valuation_ensemble` at line 742. **No edit to these functions in this brief.**
5. `services/api/app/services/fundamentals.py` — the orchestration of parse → score → valuate → persist. The integrity step is inserted **between parse and score**.
6. `services/api/app/schemas/fundamentals.py` — current API output. New fields are *additive only*.
7. `services/api/alembic/versions/b0c1d2e3f4a8_add_fundamental_bvc_documents.py` (or the actual head — Codex verifies). New migration's `down_revision` points at the true head.
8. `docs/fundamentals-layer/03-workbook-spec.md` — canonical sheet/row vocabulary. Integrity checks use these exact metric names.

If any of the above has shifted, **report the new location in the PR description before changing code**.

---

## Scope of this brief

Two deliverables, in order:

**Deliverable A — Integrity checks on historical statements.** Add a deterministic, idempotent step that runs every time a snapshot is built and produces a structured `IntegrityReport` per (symbol, statement_year). The report is stored in the DB, surfaced on the API, and shown on the Quality tab in the UI. If a critical check fails on the latest statement year, the snapshot is downgraded — pillars and valuations still compute, but with a `data_integrity` warning that haircuts confidence.

**Deliverable B — Projected 3-statement linkage.** Materialise the *forward* IS / BS / CFS that the valuation engine implicitly assumes. Today `_fcff_dcf` projects FCF arrays but never reifies them; brief B writes those projections out into the snapshot so the user can see them, and runs the same balance / tie-out / NI-link checks on the projection.

Deliverable A is the priority. Deliverable B is only valuable once A is in place.

**Out of scope** (do NOT do in this brief): editing any valuation model body, changing currency handling, ingesting forward consensus estimates, adding a new data source.

---

## Deliverable A — Historical 3-statement integrity checks

### A.1  The three checks (formulas are non-negotiable)

For each `(symbol, statement_year)`, compute the three classical identities. **All quantities are pulled from `AnnualMetricRow` rows using the metric names as they exist today** in `normalize_yfinance.py` / `workbook.py`. If a name is missing, that check is `unavailable`; it does NOT silently become `pass`.

1. **BS balance** — `Total_Assets − (Total_Liabilities + Total_Equity) ≈ 0`.
   - `delta = Total_Assets - Total_Liabilities - Total_Equity`
   - `rel_delta = delta / max(Total_Assets, 1.0)`  (guard division)
   - `status = pass` if `abs(rel_delta) <= 0.005` (50 bps), `warn` if `<= 0.02` (2 %), else `fail`.
   - The 50 bps / 2 % thresholds are tunable via `DEFAULT_ASSUMPTIONS["bs_balance_warn_bps"]` and `..._fail_bps"]` — Codex adds those two keys with values `50` and `200` (basis points). Document in `08-assumptions-and-defaults.md`.

2. **Cash tie-out** — `CFS_Ending_Cash ≈ BS_Cash_and_Equivalents`.
   - `delta = CFS_Ending_Cash - BS_Cash_and_Equivalents`
   - `rel_delta = delta / max(abs(BS_Cash_and_Equivalents), 1.0)`
   - `status = pass` if `abs(rel_delta) <= 0.01`, `warn` if `<= 0.05`, else `fail`.
   - If either side is missing, derive `CFS_Ending_Cash` as `CFS_Beginning_Cash + sum(CF_Operating, CF_Investing, CF_Financing, CF_FX_Effect)`. If the derivation is used, the check is marked `derived` and its severity caps at `warn`.

3. **NI link IS → CFS** — `IS_Net_Income == CFS_Net_Income_Top_Of_CFS`.
   - `delta = IS_Net_Income - CFS_Net_Income_Top_Of_CFS`
   - `rel_delta = delta / max(abs(IS_Net_Income), 1.0)`
   - `status = pass` if `abs(rel_delta) <= 0.005`, `warn` if `<= 0.02`, else `fail`.
   - If `CFS_Net_Income_Top_Of_CFS` is missing entirely (yfinance sometimes omits it), the check is `unavailable` and a warning is emitted: `"ni_link_unavailable: cannot verify IS→CFS net income link"`.

**Do not add a fourth check in this brief.** If a future brief wants debt-roll or working-capital roll, it goes in a separate file.

### A.2  Data structures (add to `core/quant_core/fundamentals/domain.py`)

```python
@dataclass(frozen=True)
class IntegrityCheck:
    name: str                       # "bs_balance" | "cash_tie_out" | "ni_link"
    status: str                     # "pass" | "warn" | "fail" | "unavailable" | "derived"
    delta: float | None             # signed absolute difference, currency units
    rel_delta: float | None         # signed relative difference, dimensionless
    inputs: dict[str, float | None] # the literal AnnualMetricRow values used
    message: str | None = None      # human-readable, French OK (matches UI)

@dataclass(frozen=True)
class IntegrityReport:
    symbol: str
    statement_year: int
    checks: list[IntegrityCheck]
    overall_status: str             # worst non-unavailable check status
    confidence_haircut: float       # 0.0 .. 0.5 — see A.4
```

`overall_status` rule: take the worst of `{pass, warn, fail}` across checks where `status != "unavailable"`. If all checks are `unavailable`, `overall_status = "unavailable"`.

`inputs` MUST be filled with the *exact* values consumed, including `None` for missing — this is what the UI shows on hover, and what makes the report auditable. Do not round, do not coerce `None` to `0`.

### A.3  Where the step lives in the pipeline

Insert into `services/api/app/services/fundamentals.py` orchestration **between parse and score**. The function lives in a new module `core/quant_core/fundamentals/integrity.py`:

```python
def build_integrity_report(
    symbol: str,
    statement_year: int,
    rows_by_metric: dict[str, float | None],
    assumptions: dict[str, float] = DEFAULT_ASSUMPTIONS,
) -> IntegrityReport: ...
```

`rows_by_metric` is the same dict used inside `valuation.py:_extract_metric` — Codex factors out a helper (`_latest_year_metric_map`) so both call sites share it. Do NOT inline the lookup in two places.

`integrity.py` MUST have **zero imports** from `services/` or `frontend/` — it stays pure-domain.

### A.4  Confidence haircut

The integrity result feeds the existing confidence pipeline in `valuation.py` and `scoring.py`:

| `overall_status` | `confidence_haircut` | Effect |
|---|---|---|
| `pass` | `0.0` | No change. |
| `warn` | `0.10` | Multiplied into model `confidence_score` before weighting. Adds warning `"integrity_warn: {check_names}"`. |
| `fail` | `0.30` | Same multiplication. Adds warning `"integrity_fail: {check_names}"`. **Also** sets `is_proxy=True` on every `ValuationResult` for that symbol-year, which routes it through `proxy_weight_cap`. |
| `unavailable` | `0.05` | Mild haircut, warning `"integrity_unavailable"`. |
| `derived` | `0.05` | Treated like `warn`-light. Warning `"integrity_derived_cash"`. |

Where to wire it: `compute_symbol_valuations` (`valuation.py:814`) already takes `snapshot: FundamentalSnapshot`. Add the integrity report as an **optional** kwarg `integrity: IntegrityReport | None = None` and apply the haircut at the same point `confidence_score` is computed for each model. Do not change the per-model confidence rules in `06-valuation-models.md` — this multiplies on top of them.

### A.5  Persistence

New Alembic migration `<hash>_add_fundamental_integrity.py`:

- `down_revision` = current head (Codex verifies).
- New table `fundamental_integrity_report`:
  - `id` BIGSERIAL PK
  - `symbol` TEXT NOT NULL
  - `statement_year` INT NOT NULL
  - `import_run_id` BIGINT NOT NULL (FK to existing `fundamental_import_run.id` — Codex verifies the FK target by reading existing migrations)
  - `overall_status` TEXT NOT NULL
  - `confidence_haircut` DOUBLE PRECISION NOT NULL
  - `checks_json` JSONB NOT NULL — serialised `list[IntegrityCheck]`
  - `created_at` TIMESTAMP DEFAULT now()
  - UNIQUE (`symbol`, `statement_year`, `import_run_id`)
  - INDEX on (`symbol`, `statement_year`)

The persistence write happens in the worker (`services/worker/tasks/fundamentals.py` and / or `targeted_bvc_fundamentals.py` — Codex reads first to confirm), inside the same transaction as the snapshot write. If the snapshot write fails, the integrity write rolls back. If the integrity computation itself raises, **do not swallow** — let the import fail and surface the error.

### A.6  API surface

Add to `services/api/app/schemas/fundamentals.py`:

- `IntegrityCheckOut(name, status, delta, rel_delta, inputs, message)` — pydantic model mirroring the dataclass.
- `IntegrityReportOut(symbol, statement_year, checks: list[IntegrityCheckOut], overall_status, confidence_haircut)`.
- Add `integrity: IntegrityReportOut | None` to whatever existing schema represents one symbol's fundamentals envelope (Codex names this after reading the file — do NOT invent a new envelope).

Add to `services/api/app/routers/fundamentals.py`:

- A read-only endpoint `GET /fundamentals/{symbol}/integrity` returning the latest report. **Reuses the existing auth / tenancy decorator** used by the other endpoints in that router — do not add a new auth path.
- The per-symbol envelope endpoint includes the integrity report inline. Existing endpoints **add** the field; they do not remove or rename any existing field.

### A.7  UI surface (markdown spec only — no code in this brief)

Update `docs/fundamentals-layer/15-ui-goals-and-design.md` and `docs/fundamentals-layer/19-ui-tear-sheet-spec.md` with one new sub-section: "Quality tab — Integrity block". The block shows three rows (BS balance / Cash tie-out / NI link) with a status chip (`pass` = green, `warn` = amber, `fail` = red, `unavailable` / `derived` = grey). On hover, show the `inputs` dict. **Frontend implementation is a separate ticket**; this brief only authors the spec.

### A.8  Tests Codex MUST add

Location: `core/tests/test_fundamental_integrity.py`.

| Test | What it asserts |
|---|---|
| `test_bs_balance_pass_at_zero_delta` | Synthetic snapshot with A = L + E → `status="pass"`, `rel_delta == 0`. |
| `test_bs_balance_warn_at_1pct` | Delta = 1 % of assets → `status="warn"`. |
| `test_bs_balance_fail_at_5pct` | Delta = 5 % → `status="fail"`. |
| `test_cash_tie_out_derived_path` | `CFS_Ending_Cash` missing, derivation populates it → `status` capped at `warn`, message contains `derived`. |
| `test_ni_link_unavailable_when_top_of_cfs_missing` | Missing input → `status="unavailable"`, warning emitted. |
| `test_overall_status_picks_worst` | One `warn` + one `pass` + one `unavailable` → `overall_status="warn"`. |
| `test_haircut_applied_to_valuation_confidence` | Build a snapshot with `overall_status="fail"`, run `compute_symbol_valuations`, assert each `ValuationResult.confidence_score` is 0.30 lower than the no-integrity baseline. |
| `test_haircut_sets_is_proxy_on_fail` | Same setup; `is_proxy=True` on every result. |
| `test_integrity_does_not_mutate_snapshot` | Snapshot equal before / after `build_integrity_report` call (the function is pure). |

Plus one API test under `services/api/tests/test_fundamentals_integrity_api.py`:
- `test_get_integrity_returns_persisted_report` — seed a report through the service, GET it, assert response shape matches `IntegrityReportOut` exactly.

### A.9  Acceptance criteria for Deliverable A

- [ ] `python -m pytest core/tests/test_fundamental_integrity.py -q` is green.
- [ ] `python -m pytest services/api/tests/test_fundamentals_integrity_api.py -q` is green.
- [ ] `python -m pytest core/tests/ -q` is green overall (no regressions to the 91 existing passing tests).
- [ ] `alembic upgrade head` + `alembic downgrade -1` round-trips clean on a fresh DB.
- [ ] Running an import end-to-end on one MASI symbol produces exactly one `fundamental_integrity_report` row per `(symbol, statement_year, import_run_id)`.
- [ ] `GET /fundamentals/{symbol}/integrity` returns 200 with the schema above; missing symbol → 404 with the existing error envelope.
- [ ] `docs/fundamentals-layer/15-ui-goals-and-design.md` has the Quality-tab Integrity block sub-section.

### A.10  Open questions to flag back, not improvise

If Codex finds that the metric names in this brief (e.g. `Total_Assets`, `Total_Liabilities`, `Total_Equity`, `CFS_Ending_Cash`, `BS_Cash_and_Equivalents`, `IS_Net_Income`, `CFS_Net_Income_Top_Of_CFS`) **do not match** what `normalize_yfinance.py` or `workbook.py` actually emit, Codex MUST:

1. Stop coding.
2. Open this file, append the actual emitted names under a `## Open questions` heading at the bottom.
3. Wait for confirmation before continuing.

Do not silently rename. Do not fall back to fuzzy matching. The vocabulary is intentional.

---

## Deliverable B — Projected 3-statement linkage

Only start once Deliverable A is merged and green.

### B.1  What this delivers

A `ProjectedStatement` block on each `FundamentalSnapshot.diagnostics["projected_statements"]` containing, for `years = forecast_years + fade_years` (default 10), a yearly IS / BS / CFS skeleton whose lines are derived from the same assumption set the valuation engine consumed. **The projections are diagnostic — they do not change the fair value.** Their job is to make the implicit model auditable.

### B.2  Projection driver (formulas tied to existing assumptions)

Use the canonical `DEFAULT_ASSUMPTIONS` constants from `valuation.py:13-49` — do NOT introduce new ones. The driver is the same one already implicit in `_fcff_dcf`:

| Year `t` | Quantity | Formula | Source of inputs |
|---|---|---|---|
| 1..forecast_years | `Revenue_t` | `Revenue_{t-1} × (1 + g_t)` with `g_t` fading linearly from `growth_cap` to `terminal_growth` over `forecast_years + fade_years` | `growth_cap`, `terminal_growth`, `forecast_years`, `fade_years` from assumptions |
| same | `EBIT_t` | `Revenue_t × EBIT_margin_lastY` (held constant) | last-year IS metrics |
| same | `Net_Income_t` | `EBIT_t × (1 - tax_rate)` (debt service simplification noted in `warnings`) | `tax_rate` from assumptions |
| same | `FCF_t` | identical to what `_fcff_dcf` already computes — Codex factors out the existing closure into a named helper `_project_fcf_path(snapshot, assumptions)` and **reuses it** here. Two FCF paths producing different numbers is a P0 bug. |
| same | `BS_Total_Assets_t` | `Revenue_t × Asset_Turnover_lastY` | last-year BS / IS |
| same | `BS_Equity_t` | `BS_Equity_{t-1} + Net_Income_t × (1 - stable_payout_ratio)` | `stable_payout_ratio` from assumptions |
| same | `BS_Liabilities_t` | `BS_Total_Assets_t - BS_Equity_t` (plug) | derived |
| same | `CFS_Operating_t` | `Net_Income_t + (FCF_t - capex_lastY)` approximation | last-year CFS |
| same | `CFS_Investing_t` | `-capex_lastY × (Revenue_t / Revenue_lastY)` | last-year CFS |
| same | `CFS_Financing_t` | `- Net_Income_t × stable_payout_ratio` | dividend assumption |

These formulas are **deliberately coarse**. They are *not* a substitute for an analyst-built three-statement; they are the engine's own implicit model, surfaced. Codex MUST emit a `warnings` entry on the snapshot: `"projected_statements_are_engine_implicit"` so no consumer mistakes them for analyst-grade forecasts.

### B.3  Integrity checks on projections

Run the same three A.1 checks on each projected year. The projected BS will balance **by construction** (Liabilities is the plug), so the BS-balance check on projected years is a *regression* test — if it ever fails, the projection driver itself is broken.

Surface the projected-year integrity in the same `IntegrityReport` shape, under a new field:

```python
@dataclass(frozen=True)
class IntegrityReport:
    ...
    projection_checks: list[IntegrityCheck] = field(default_factory=list)
```

If any projection check is not `pass`, raise — this is an internal-consistency bug, not data quality.

### B.4  Persistence

Add to the migration from A.5 (or a follow-up migration if A is already shipped — Codex chooses based on whether A is merged):
- Column `projected_statements_json` JSONB NULL on `fundamental_integrity_report`.
- Column `projection_checks_json` JSONB NULL on the same row.

### B.5  API surface

`IntegrityReportOut` gains:
- `projected_statements: list[dict[str, float | None]]` (one dict per projected year, keys = metric names)
- `projection_checks: list[IntegrityCheckOut]`

### B.6  Tests

`core/tests/test_fundamental_projections.py`:
- `test_projected_fcf_matches_fcff_engine` — the projected FCF path equals the path `_fcff_dcf` consumes, to floating-point tolerance. **This is the most important test in this brief.** Two FCF paths drifting is a worse bug than no projections at all.
- `test_projected_bs_balances_by_construction` — every projected year has BS-balance `pass`.
- `test_warnings_include_engine_implicit` — the snapshot's warnings list includes `"projected_statements_are_engine_implicit"`.

### B.7  Acceptance criteria for Deliverable B

- [ ] Both projection tests are green.
- [ ] No existing fair-value test changes its numerical output (projections are diagnostic-only).
- [ ] One MASI symbol's response shows 10 years of projected lines on the API.
- [ ] `06-valuation-models.md` is updated with a short sub-section "Projected statements (diagnostic)" pointing back at this brief.

---

## What success looks like at the end of brief 22

Before: a user looks at a `BUY, fair value MAD 180, upside +24 %` output and has no way to know that the underlying balance sheet has a 6 % imbalance and the cash didn't tie out.

After: the same output carries an Integrity block — three checks with status chips, the raw deltas, a confidence haircut already baked into the upside number, and a projected three-statement they can read year-by-year to see what the engine actually assumed.

This is the difference between a screening tool and an institutional research tool, and it is the single largest gap closed by the brief series.
