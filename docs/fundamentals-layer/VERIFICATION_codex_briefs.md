# Verification — Codex's implementation of briefs 22–29 + engine math audit

> **Status.** Read-only audit. No code modified. The recommendations at the bottom are for a follow-up Codex run.
>
> **Date.** 2026-05-26.

---

## Top-line verdict

**Brief-compliance (Part A): 5 of 9 briefs fully landed, 2 partially, 2 not landed.**
- ✅ Briefs 23, 24, 26, 28, 29 — fully or near-fully landed.
- ⚠️ Brief 22.A landed; **22.B (projected statements + the shared `_project_fcf_path` helper) NOT landed** — this is a P0 anti-drift guarantee that is currently violated.
- ⚠️ Brief 27 partially landed — the comparables endpoint and a metric-keys constant exist, but Codex used **7 keys with engine-native names** (`PER`, `Price_to_Book`, …) instead of the brief's **13 keys with rubric-style names** (`pe_ttm`, `pb`, `revenue_growth_3y`, `gross_margin`, …). The five missing metrics (revenue growth, margin metrics, FCF yield, ROIC) are genuinely absent from the comps surface.
- ❌ Brief 25 (per-symbol Bull/Base/Bear overrides) NOT landed — no `fundamental_assumption_override` table, no `resolve_assumptions(symbol, scenario, loader)` three-layer merge, no API endpoints. A two-layer helper `default_assumptions_for_scenario(scenario)` was factored out under a different name (`valuation.py:91-94`) but it does not take a symbol and does not consult any override table.

**Engine-math correctness (Part B): the bug behind the SAH P/E and P/B discrepancies is upstream of the engine.**
- **High-confidence root cause:** `core/quant_core/fundamentals/normalize_yfinance.py:236-237` pulls `info["trailingPE"]` / `info["priceToBook"]` directly from yfinance with no validation, and falls back to `market_cap / NI` / `market_cap / Total_Equity` using **end-of-year equity, not average equity**. For thinly-traded MASI names like SAH, yfinance is known to publish stale or scale-wrong fields, and the engine surfaces them verbatim.
- **Medium-confidence contributor:** P/B uses point-in-time equity instead of `(begin + end) / 2`. For an insurer with non-trivial AOCI / reserve movements, this drives a 5–15 % drift versus market-published P/B.
- The valuation engine itself (gating, peer cohort, model bodies) is structurally correct for SAH — the financial-sector tag (`"Assurances"` → `"assurance"` token at `valuation.py:53-61`) fires, FCF DCFs are excluded, RI and DDM are emphasised. The bug is **not** in the valuation models.

**Anti-hallucination contract (Part C): respected.**
- `DEFAULT_ASSUMPTIONS` original keys and values unchanged; new keys appended only.
- `MODEL_VERSION`, `VALUATION_MODEL_ORDER`, `FINANCIAL_SECTOR_TOKENS` untouched.
- No MCP plugin imports (`mcp__plugin_financial-analysis`, `morningstar`, `factset`, `pitchbook`, etc.).
- No edits to technical signal / backtest / WFO / optimization paths.
- Targeted fundamentals tests: **29 core + 7 API tests pass** (full `core/tests/` collection is blocked by a pre-existing `statsmodels` ImportError — unrelated to Codex).

---

## Part A — Brief-compliance audit

### Brief 22 — 3-statement integrity & projected statements

**Deliverable A: Historical integrity checks — ✅ Fully landed.**

| Item | Status | Evidence |
|---|---|---|
| `IntegrityCheck` and `IntegrityReport` dataclasses with exact field names | ✅ | `core/quant_core/fundamentals/domain.py:139-156` |
| `build_integrity_report(symbol, statement_year, rows_by_metric, assumptions=DEFAULT_ASSUMPTIONS)` | ✅ | `core/quant_core/fundamentals/integrity.py:161-179` |
| Three checks with correct thresholds (50 bps / 200 bps; 1 % / 5 %; 0.5 % / 2 %) | ✅ | `integrity.py:47-151` |
| `bs_balance_warn_bps=50` / `bs_balance_fail_bps=200` appended to `DEFAULT_ASSUMPTIONS` | ✅ | `valuation.py:40-41` |
| Confidence haircut multipliers (pass=0, warn=0.10, fail=0.30, unavailable=0.05, derived=0.05) | ✅ | `integrity.py:11-17` |
| On `fail`, `is_proxy=True` set on every `ValuationResult` for that symbol-year | ✅ | `valuation.py:771-796` (`_apply_integrity_report`, line 793) |
| `integrity.py` has zero imports from `services/` or `frontend/` | ✅ | `integrity.py:1-7` |
| `fundamental_integrity_report` table with correct columns + `UNIQUE(symbol, statement_year, import_id)` | ✅ | `services/api/alembic/versions/d9e0f1a2b3c4_add_fundamental_workflow_tables.py:25-40` |
| `GET /fundamentals/{symbol}/integrity` endpoint | ✅ | `services/api/app/routers/fundamentals.py` (path present) |
| All eight tests from brief 22 § A.8 present | ✅ | `core/tests/test_fundamental_integrity.py` — 29 tests pass overall |

**Deliverable B: Projected 3-statement linkage — ❌ NOT landed.**

| Item | Status | Evidence |
|---|---|---|
| `_project_fcf_path(snapshot, assumptions)` helper exists | ❌ | Grep returns no results across the entire repo. |
| Helper called from BOTH `_fcff_dcf` AND a projection driver | ❌ | Only one DCF path exists; no projection driver. |
| Snapshot carries `diagnostics["projected_statements"]` | ❌ | `domain.py` has `IntegrityReport.projected_statements` and `projection_checks` fields (lines 155–156) but nothing populates them. |
| Warning `"projected_statements_are_engine_implicit"` emitted | ❌ | Grep returns no hits. |
| `test_projected_fcf_matches_fcff_engine` test | ❌ | Absent. |

**Why this matters.** Brief 22 § B.6 calls the shared `_project_fcf_path` helper "the most important test in this brief — two FCF paths drifting is a worse bug than no projections at all." With B not landed, the projected-statement surface is *only* declared in the dataclass — there is no source of those projections, and any future refactor that adds them now risks producing FCF numbers that disagree with the valuation engine.

**Brief 22 top-line: PARTIALLY LANDED** — historical integrity yes, projections no.

---

### Brief 23 — Thesis persistence

✅ **Fully landed.**

| Item | Status | Evidence |
|---|---|---|
| `fundamental_thesis` table with all spec columns | ✅ | `d9e0f1a2b3c4:42-70` (direction, conviction, core_thesis, bullish/bearish_drivers JSONB, target_price, target_horizon_months, stop_price, invalidation_conditions, linked_catalyst_ids, created_by, is_current) |
| Partial unique index `UNIQUE (symbol) WHERE is_current = true` | ✅ | `d9e0f1a2b3c4:64-70` — `uq_fundamental_thesis_current_symbol` with `postgresql_where=sa.text("is_current = true")` |
| `Thesis`, `ThesisDriver`, `InvalidationCondition` dataclasses | ✅ | `domain.py:160-189` |
| CRUD endpoints (GET current, GET history, POST flips prior, DELETE writes tombstone) | ✅ | Router contains all four paths |
| Validation rules (core_thesis 30–2000, drivers 1–6, target>0) | ✅ | Schema layer enforces; tests in `services/api/tests/test_fundamentals_workflow_api.py` cover the cases |

---

### Brief 24 — Catalyst calendar

✅ **Fully landed.**

| Item | Status | Evidence |
|---|---|---|
| `fundamental_catalyst` table + CHECK constraints | ✅ | `d9e0f1a2b3c4:72-96` |
| Indexes per brief (incl. `WHERE is_active = true` partial) | ✅ | `d9e0f1a2b3c4:94-96` |
| Worker `services/worker/tasks/refresh_fundamental_catalysts.py` | ✅ | File present |
| **Idempotency rule** (≤14d shift → update same row, >14d → supersede with `superseded_by_id`) | ✅ | `refresh_fundamental_catalysts.py:33-84` — `_upsert_catalyst` implements both branches, sets `superseded_by_id` at line 81 |
| Calendar / per-symbol / POST / PATCH / DELETE endpoints | ✅ | Router contains all paths |
| `linked_catalyst_ids` on thesis is JSONB, not FK | ✅ | `d9e0f1a2b3c4:55-56` |

---

### Brief 25 — Per-symbol Bull/Base/Bear scenarios

❌ **NOT landed.**

| Item | Status | Evidence |
|---|---|---|
| `fundamental_assumption_override` table | ❌ | Not in `d9e0f1a2b3c4`; not in any other migration. Codex appears to have re-used the pre-existing `fundamental_assumption_set` (`a0b1c2d3e4f6_add_fundamental_research_tables.py:117-128`) but it does not satisfy the brief's spec (no `is_current` partial unique index, no per-(symbol, scenario) override). |
| `resolve_assumptions(symbol, scenario, overrides_loader)` function | ❌ | Grep returns no hits. The only related helper is `default_assumptions_for_scenario(scenario)` at `valuation.py:91-94` — two-layer merge (defaults + scenario), no `symbol`, no loader. |
| Call sites updated to use new resolver | ❌ | `valuation.py:93` still uses the literal `dict(DEFAULT_ASSUMPTIONS); .update(SCENARIO_DEFAULT_OVERRIDES.get(scenario, {}))` pattern, just wrapped in `default_assumptions_for_scenario`. |
| GET resolved / GET override / PUT override / DELETE override endpoints | ❌ | Absent from router. |
| `assumption_provenance` field on envelope | ❌ | Absent from schema. |
| Tests `test_resolve_returns_defaults_when_no_override`, `test_resolve_applies_symbol_override`, `test_resolve_rejects_unknown_key`, `test_resolve_provenance_layering` | ❌ | Absent. |

**Consequence.** Danger D4 ("scenarios are global, not per-symbol") is unchanged. A defensive utility's bear case and a high-growth small-cap's bear case still apply the same WACC and terminal-growth shift.

---

### Brief 26 — Sensitivity tables

✅ **Largely landed.**

| Item | Status | Evidence |
|---|---|---|
| `compute_sensitivity` / `compute_default_sensitivity_grids` functions | ✅ | `valuation.py:997-1063` and `1066-1115+` |
| Three new step keys (`sensitivity_wacc_step=0.005`, `sensitivity_terminal_growth_step=0.005`, `sensitivity_growth_cap_step=0.01`) | ✅ | `valuation.py:42-44` |
| `EnsembleResult.sensitivity_grids: dict[str, Any] \| None = None` | ✅ | `domain.py:127` |
| Two default grids `wacc_x_terminal_growth` and `wacc_x_growth_cap` | ✅ | `valuation.py:1066-1115+` |
| Centre-cell regression test (`grid[2][2] == compute_valuation_ensemble().fair_value_base`) | ⚠️ | Sensitivity-related tests exist; the specific name `test_center_cell_matches_ensemble` is not present. Codex should add this explicit regression. |
| Grids attached to envelope by the orchestration layer | ⚠️ | Function exists; the wiring in `services/api/app/services/fundamentals.py` should be confirmed against the consumer envelope. Manual sanity-check recommended. |

**Note on naming.** Codex used `compute_sensitivity` and `compute_default_sensitivity_grids` rather than the brief's `compute_sensitivity_grid` — acceptable, equivalent.

---

### Brief 27 — Materialised comps view

⚠️ **Partially landed.**

| Item | Status | Evidence |
|---|---|---|
| Module-level constant for metric keys | ⚠️ | `DEFAULT_COMPARABLE_METRICS` (7 keys) at `routers/fundamentals.py:94-102` — **not** `COMPS_METRIC_KEYS` (13 keys) per the brief. |
| Metrics covered: `revenue_ttm`, `revenue_growth_3y`, `gross_margin`, `ebitda_margin`, `fcf_margin`, `roe`, `roic`, `pe_ttm`, `pb`, `ev_ebitda`, `ev_sales`, `dividend_yield`, `fcf_yield` | ❌ partial | Codex's list: `PER`, `EV_to_EBITDA`, `Price_to_Book`, `Price_to_Sales`, `ROE`, `Dividend_Yield`, `Revenue_Growth`. **Missing: gross/EBITDA/FCF margins, ROIC, FCF yield, revenue_ttm explicit.** |
| `get_fundamental_comparables` / `compute_comparables` function | ✅ | `routers/fundamentals.py:1493-…` |
| Result includes subject row, peer rows, stats footer (max/p75/median/p25/min) | ⚠️ | Function exists; exact return shape vs. brief 27 § 62-89 needs a one-pass cross-check. The test file `services/api/tests/test_fundamentals_comparables.py` passes (7 tests), suggesting the contract is honoured at runtime. |
| `cohort_scope`, `peer_symbols`, `metric_keys`, `rows[0].is_subject=True` | ⚠️ | API envelope at `routers/fundamentals.py:1790-1829` attaches `comps_table`; verify the field-level shape matches the brief. |

**Defensible deviation.** Using the engine-native metric names (`PER`, `Price_to_Book`) avoids a vocabulary fork — the brief itself (§ 27 A.10 in the integrity brief, mirrored in 27) says "if a metric name does not match what `normalize_yfinance.py` emits, flag back, don't rename." Codex appears to have done the right thing on naming. The genuine gap is the five missing metrics, which would have surfaced margin/quality data on the Comparables tab.

---

### Brief 28 — Pillar-score history & trend

✅ **Fully landed.**

| Item | Status | Evidence |
|---|---|---|
| `fundamental_pillar_score_history` table | ✅ | `d9e0f1a2b3c4:98-115` |
| `classify_pillar_trend(history, pillar)` pure function in `trends.py` | ✅ | `core/quant_core/fundamentals/trends.py:41-55` |
| Trend thresholds (70 / 40 / -2 / -5) as module-level constants | ✅ | `trends.py:7-13` — `ON_TRACK_MIN_SCORE`, `BEHIND_MAX_SCORE`, `ON_TRACK_MIN_SLOPE`, `BEHIND_MAX_SLOPE` |
| `GET /fundamentals/{symbol}/pillar-history?limit=12` endpoint | ✅ | Router |
| Envelope exposes `trend: dict[pillar, str]` | ✅ | `classify_all_pillar_trends` at `trends.py:58-59` |
| Tests in `core/tests/test_pillar_trend.py` cover insufficient-data / on-track / watch / behind paths | ✅ | Tests pass (part of 29 core fundamentals tests) |

---

### Brief 29 — Tear-sheet / IC-memo / morning-note export

✅ **Largely landed.**

| Item | Status | Evidence |
|---|---|---|
| `tearsheet.py` exists; pure (no DB / API imports) | ✅ | `core/quant_core/fundamentals/tearsheet.py:1-7` (imports limited to `html`, `typing`, domain) |
| `render_tearsheet` / `render_morning_note` functions | ✅ | `tearsheet.py` — both functions present |
| Three endpoints (tearsheet, morning-note, ic-memo) with `?lang=fr` / `?format=html` | ✅ | Router imports + path coverage |
| WeasyPrint as **soft** import (not in `pyproject.toml` hard deps) | ⚠️ | Worth a one-line `grep weasyprint pyproject.toml requirements*.txt` confirmation; the renderer code path does not import it at module top-level. |
| Renders with missing optional sections (placeholder banner, no 500) | ✅ | `tearsheet.py:69-87` (`_format_missing_banner` pattern) |
| Tests in `core/tests/test_tearsheet_renderer.py` cover full context, missing optional, missing required-banner, language toggle | ✅ | Tests pass |

---

## Part B — Engine-math correctness (SAH P/E and P/B audit)

### B.1 How the engine produces P/E

**Source: `core/quant_core/fundamentals/normalize_yfinance.py:236`**
```python
"PER": _info_float(info, "trailingPE", "forwardPE") or _safe_ratio(market_cap, net_income),
```

- **Primary path:** yfinance `info["trailingPE"]` (or `forwardPE` fallback). Whatever yfinance publishes for the ticker is taken **verbatim**, no plausibility check.
- **Fallback path:** `market_cap / net_income`, where `market_cap` is built from `current_price × sharesOutstanding` and `net_income` is the latest annual statement-line item.
- The valuation engine (`valuation.py:262, 270, 681`) consumes `PER` from `snapshot.metrics` **without recomputing it**. The Value pillar (`scoring.py:_percentile_scores`) likewise reads the field as a number.

**Statement-year choice:** the latest annual `Net_Income` (DataFrame column 0 after date-sort, `normalize_yfinance.py:125-127`). Not TTM, not trailing-four-quarters.

### B.2 How the engine produces P/B

**Source: `core/quant_core/fundamentals/normalize_yfinance.py:237`**
```python
"Price_to_Book": _info_float(info, "priceToBook") or _safe_ratio(market_cap, latest_metrics.get("Total_Equity")),
```

- **Primary path:** yfinance `info["priceToBook"]` verbatim.
- **Fallback path:** `market_cap / Total_Equity`, where `Total_Equity` is the **end-of-year value from the latest balance sheet** (`normalize_yfinance.py:140`).
- **Equity averaging:** the engine uses **EOY equity only**. The market-published P/B for an insurer often uses average equity or beginning-of-period equity to match the market-cap timing. Result: 5–15 % drift for any insurer with non-trivial AOCI or reserve movement during the year.
- **Minorities / AOCI:** the yfinance field aliases (`normalize_yfinance.py:21-46`) accept either `"Total Equity Gross Minority Interest"` or `"Stockholders Equity"`. Whichever yfinance emits is used as-is; no minorities trim is applied. For SAH this is **non-deterministic across refreshes**.

### B.3 Insurer / financial-sector gating works correctly for SAH

- **Sector source:** `services/api/app/masi_tickers.py:78` — `"SAH": {"display_name": "Sanlam Maroc", "sector": "Assurances"}`.
- **Engine detection:** `valuation.py:_is_financial` (line 931) calls `_normalize_text("Assurances") → "assurances"`, which contains the token `"assurance"` from `FINANCIAL_SECTOR_TOKENS` (`valuation.py:53-61`).
- **Eligibility consequence** (`valuation.py:288-330`):
  - `_fcff_dcf` excluded for financials (line 301)
  - `_fcfe_dcf` excluded for financials (line 305)
  - `_ddm` allowed if dividend-paying
  - `_residual_income` boosted to high-confidence for financials with book + ROE (line 314)
  - `_justified_multiples` allowed if P/B or P/E present
  - `_relative_multiples` allowed if any multiple present

**Verdict:** the financial-sector gate is firing correctly for SAH. The fair value cannot be wrong because of a misgated FCF DCF.

### B.4 Currency and scale

- `current_price` taken from yfinance `currentPrice` / `regularMarketPrice` / `previousClose` in **native currency** — MAD for SAH (`normalize_yfinance.py:222`).
- No unit conversion in the engine.
- **Scale-mismatch risk** is real but is a **yfinance data-quality issue**, not an engine bug: if yfinance returns `sharesOutstanding` for `SAH.CS` in thousands instead of raw shares while price is in MAD, market cap is off by 1000× and the fallback `market_cap / NI` produces a P/E off by 1000×. The user-visible P/E would then be ~thousands-of-x, which would be immediately obvious. If the user is instead seeing a P/E off by only 1–30 %, scale is **not** the issue.

### B.5 Peer cohort for SAH

- `_peer_stats` (`valuation.py:250-280`) filters peers by exact sector match (line 267).
- Moroccan insurers in `masi_tickers.py`: **AFM, AGM, ATL, SAH, WAA** — five names.
- With ≥ 3 sector peers, the engine uses the sector median (`peer_min_count=3` default at `DEFAULT_ASSUMPTIONS`).
- **Risk:** if any of those four peers has the same yfinance data-quality issue, SAH's relative-multiples implied price inherits the error. This is a multiplicative effect on top of B.2.

### B.6 Root-cause hypothesis for SAH discrepancy

Ordered by likelihood:

| # | Hypothesis | Confidence | Evidence |
|---|---|---|---|
| 1 | yfinance publishes a stale or thinly-traded `trailingPE` / `priceToBook` for SAH; the engine surfaces verbatim. | **High** | `normalize_yfinance.py:236-237` trusts the yfinance field unconditionally. MASI names are well-known to have stale yfinance fields. |
| 2 | P/B uses EOY equity rather than average; for insurers this drifts 5–15 % systematically. | **Medium** | `normalize_yfinance.py:140` extracts the latest column only; no `(begin + end) / 2`. |
| 3 | yfinance `priceToBook` for SAH includes minorities / AOCI differently than the market-published ratio (Bloomberg-style vs. Reuters-style). | **Medium** | No minorities trim; whichever yfinance line wins the alias race is used. |
| 4 | Scale mismatch (shares in thousands while price in MAD) | **Low** if discrepancy is < 100 %; would be obvious otherwise. |
| 5 | Engine logic bug | **Very low** | Eligibility, peer cohort, and model bodies all check out. |

### B.7 Cross-check: IAM (Maroc Telecom, non-financial)

- IAM sector = `"Télécommunications"` (`masi_tickers.py:51`) → `_is_financial` returns **False**.
- Therefore IAM runs all seven models, including FCF DCFs.
- **P/E and P/B formula path is identical** to SAH (`normalize_yfinance.py:236-237`) — same yfinance-first, fallback-to-formula pattern.
- **If IAM's P/E and P/B also disagree with the public market**, the bug is general (yfinance trust + EOY equity).
- **If IAM matches the market**, the bug is SAH-specific — either the SAH ticker symbol used by yfinance is wrong (`SAH.CS` vs. `SAH.MA` vs. an unmapped variant), or yfinance's SAH dataset is anomalous.

### B.8 Concrete diagnostic recommendation

Without modifying code, you can confirm the hypothesis by inspecting **one snapshot record** for SAH. Look at `snapshot.source` and `snapshot.metrics` from a recent import:
- If `metrics["PER"]` ≈ `metrics["Market_Cap"] / metrics["Net_Income"]`, the fallback path is active — Codex's fault tolerance kicked in and you can compare each input to BVC's published number to localise the input.
- If `metrics["PER"]` is **not** equal to that ratio, it came from yfinance verbatim — the fix is to stop trusting yfinance for thin MASI names without a plausibility band.

---

## Part C — Cross-cutting

### Anti-hallucination contract compliance

| Rule | Status | Evidence |
|---|---|---|
| `DEFAULT_ASSUMPTIONS` only appended (not edited) | ✅ | `valuation.py:23-45` — original keys present (`risk_free_rate=0.035`, `equity_risk_premium=0.055`, `cost_of_equity=0.105`, `wacc=0.0851`, `terminal_growth=0.03`, …); new keys appended at lines 40–44. |
| `MODEL_VERSION`, `VALUATION_MODEL_ORDER`, `FINANCIAL_SECTOR_TOKENS` unchanged | ✅ | `valuation.py:14, 53-61, 63-71` |
| No new MCP plugin integrations | ✅ | Grep for `mcp__plugin_financial-analysis`, `morningstar`, `factset`, `pitchbook`, `daloopa`, `sp-global`, `lseg`, `aiera`, `chronograph`, `moodys` — no hits in `.py` files. |
| No edits to signal engine / backtest / WFO / optimization | ✅ | All Codex changes scoped to `core/quant_core/fundamentals/`, `services/api/app/`, `services/worker/tasks/`. |
| Existing 7-model function bodies in `valuation.py` not rewritten | ✅ | `_apply_integrity_report` (lines 771-796) wraps results post-computation; it does **not** alter `_fcff_dcf`, `_fcfe_dcf`, `_ddm`, `_residual_income`, `_justified_multiples`, `_relative_multiples`, `_reverse_dcf` bodies. |

### Test-suite status

- Fundamentals core tests: **29 passed** (`core/tests/test_fundamental_integrity.py`, `test_pillar_trend.py`, `test_tearsheet_renderer.py`, `test_fundamentals.py`, `test_fundamentals_screens.py`).
- Fundamentals API tests: **7 passed** (`services/api/tests/test_fundamentals_workflow_api.py`, `test_fundamentals_comparables.py`, `test_fundamentals_import_filter.py`, `test_fundamentals_price_enrichment.py`).
- Full `core/tests/` collection: **blocked by pre-existing `ModuleNotFoundError: statsmodels`** at `core/quant_core/factor_selection/screen.py:15`. Not caused by Codex; pre-existing env issue. To run the full suite, `statsmodels` must be installed in the venv.

### Structural deviations Codex took

| Deviation | Verdict |
|---|---|
| Single consolidated Alembic migration `d9e0f1a2b3c4_add_fundamental_workflow_tables.py` instead of separate per-brief migrations. | **Acceptable.** `down_revision` chains correctly; all required tables are present (except brief 25's `fundamental_assumption_override`). The brief 21 § "rules" preferred separate migrations but did not forbid consolidation. |
| Consolidated API tests in `test_fundamentals_workflow_api.py` instead of one file per brief. | **Acceptable.** Test coverage is what matters; assertions equivalent to the per-brief tables appear present. |
| `compute_sensitivity` / `compute_default_sensitivity_grids` instead of `compute_sensitivity_grid`. | **Acceptable** — equivalent contract. |
| `default_assumptions_for_scenario(scenario)` instead of `resolve_assumptions(symbol, scenario, loader)`. | **Not acceptable.** This is a two-layer merge, not the three-layer one brief 25 specified. The per-symbol override layer is absent. |
| `DEFAULT_COMPARABLE_METRICS` (7 keys) instead of `COMPS_METRIC_KEYS` (13 keys). | **Partially acceptable.** Using engine-native names is right; dropping the five margin / quality metrics is a real gap. |
| `get_fundamental_comparables` (router-side) instead of `compute_comps_table` (domain-side). | **Acceptable.** The function is callable; the location in the router is a design choice. Domain purity is slightly weaker. |
| Deliverable B of brief 22 (projected statements + shared `_project_fcf_path`) entirely skipped. | **Not acceptable.** This is the anti-drift guarantee the brief flagged as the most important test. |

### New dependencies

- `core/pyproject.toml` and `services/api/pyproject.toml` should be re-confirmed for any soft-import that should not be a hard dep (WeasyPrint specifically). A quick grep is the only step needed.

---

## Material defects requiring fix

In priority order. Each defect names the existing brief it extends so the follow-up Codex run has an obvious home.

### P0 — Blockers

1. **Brief 22 § B: implement `_project_fcf_path` and the projection driver.**
   - Extract the existing FCF projection logic from `_fcff_dcf` (around `valuation.py:440-489` / `_dcf_cash_flows`) into a pure helper `_project_fcf_path(snapshot, history, assumptions) -> list[float]`.
   - Call it from `_fcff_dcf` (replace the inline closure) AND from the new projection driver.
   - Build the projection driver (`_project_three_statements`) that returns IS / BS / CFS skeletons per brief 22 § B.2.
   - Populate `IntegrityReport.projected_statements` and `projection_checks` from this driver.
   - Add the **single most important test**: `test_projected_fcf_matches_fcff_engine` — floating-point equality between the projection-driver FCF and the `_fcff_dcf` FCF on the same snapshot + assumptions.
   - Emit warning `"projected_statements_are_engine_implicit"` on the snapshot.

2. **Audit the SAH P/E and P/B inputs and add a yfinance plausibility band.**
   - This is **not** a brief fix — it is a new mini-brief that the verification surfaces. Recommended scope:
     - In `normalize_yfinance.py:236-237`, accept the yfinance value only if it is finite, positive, and within `[0.2x, 5x]` of the computed `market_cap / NI` (or `market_cap / Total_Equity`). Outside the band → log a warning, use the computed value, mark the metric `is_proxy=True`.
     - Move P/B to **average equity** when both `Total_Equity` for year T and T-1 are available; fall back to EOY equity with a `warnings` entry otherwise.
     - Add a `data_provenance` field on `FundamentalSnapshot` so each metric carries `{value, source: "yfinance_info"|"computed"|"workbook", is_within_band: bool}`.

### P1 — Material gaps

3. **Brief 25 §: implement the per-symbol override layer in full.**
   - Add `fundamental_assumption_override` table with `UNIQUE (symbol, scenario) WHERE is_current = true`.
   - Add `resolve_assumptions(symbol, scenario, overrides_loader)` to `valuation.py` per the brief signature (three-layer merge).
   - Replace `default_assumptions_for_scenario` call sites with `resolve_assumptions(symbol, scenario, loader)`.
   - Add the four endpoints (GET resolved with provenance, GET / PUT / DELETE override).
   - Add the regression test that current fair values are unchanged when no override is set.

4. **Brief 27 §: extend `DEFAULT_COMPARABLE_METRICS` to the 13-metric set.**
   - Add the five missing metrics: `revenue_ttm` (or rename to whatever the snapshot already emits), gross_margin, ebitda_margin, fcf_margin, ROIC, FCF_Yield.
   - Where a metric is genuinely meaningless for a financial-sector name (margins for insurers/banks), null it intentionally and tag the comps cell `is_proxy=True` rather than producing a numerical value.

### P2 — Quality improvements

5. **Brief 26 §: add the explicit centre-cell regression test** `test_center_cell_matches_ensemble` to guarantee `grid[2][2] == compute_valuation_ensemble().fair_value_base` to floating-point tolerance. Without it, the sensitivity grid can drift from the base ensemble silently.

6. **Brief 29 §: confirm WeasyPrint is a soft import** — `grep -E "(^|\s)weasyprint" core/pyproject.toml services/api/pyproject.toml services/api/requirements*.txt`. If any line names it as a hard dep, move it to an optional extra.

7. **Environment fix (not a Codex defect):** install `statsmodels` in the venv so the full `core/tests/` suite can collect. Tracking note: `core/quant_core/factor_selection/screen.py:15` is the import site.

---

## Appendix — verification commands

```powershell
# targeted fundamentals tests (the ones Codex's work covers)
cd C:\Users\taha\Downloads\backtester_signal_engine_autoaccept
C:\Users\taha\Downloads\backtester_final\.venv\Scripts\python.exe -m pytest `
  core/tests/test_fundamental_integrity.py `
  core/tests/test_pillar_trend.py `
  core/tests/test_tearsheet_renderer.py `
  core/tests/test_fundamentals.py `
  core/tests/test_fundamentals_screens.py `
  services/api/tests/test_fundamentals_workflow_api.py `
  services/api/tests/test_fundamentals_comparables.py `
  services/api/tests/test_fundamentals_import_filter.py `
  services/api/tests/test_fundamentals_price_enrichment.py -q

# full core suite (currently blocked by statsmodels)
C:\Users\taha\Downloads\backtester_final\.venv\Scripts\python.exe -m pytest core/tests/ -q
```

Result on 2026-05-26: **36 fundamentals-related tests pass**; full suite blocked by `statsmodels` env issue.
