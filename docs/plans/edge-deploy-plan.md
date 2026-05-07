# Edge Metrics + Intranet Deployment — Implementation Plan

> **Status:** Plan document, intended to be reviewed and implemented by Codex.
> The user (taha) will hand this plan to Codex for implementation. The working copy lives in `~/.claude/plans/hey-so-i-think-misty-quasar.md`; this file is the repo-side handoff.

## ⚡ Codex — start here

**Recommended first step before touching any production code: complete the §4.1.a audit.** It is read-only, it answers two of the §7 open items, and every subsequent backend task in Workstream A depends on its findings. Doing it first prevents you from designing `oos_index.py` against assumptions that turn out to be wrong.

Concretely, in this order:

1. **Read end-to-end** without making changes:
   - `core/quant_core/research/score_history.py` — focus on lines 38–315 (bucketing, forward-return helpers, `bucketed_forward_returns`)
   - `core/quant_core/significance.py` — lines 40–125 (`monte_carlo_luck_test` and the centered-bootstrap null)
   - `core/quant_core/research/stats/hit_rate.py` — `wilson_ci`
   - `core/quant_core/signal_engine/` — find the indicator-parameter-grid construction site(s) and `_build_family_snapshot`
   - `services/api/app/models.py:670–840` — `WfoSignalSummary`, `WfoGlobalSignal`, `SignalEngineFamilyResult`, `SignalEngineGlobalResult`
   - `services/api/app/routers/runs.py` — find the actual leaderboard endpoint feeding `frontend/app/v1/page.tsx` (likely `list_strategy_leaderboard`, but verify; this resolves §7 item 3)

2. **Inspect real data** in the dev / local Postgres:
   - Pull at least 5 rows from `wfo_signal_summary` and dump `folds_json` for each. Document the JSON shape (key names, types, whether OOS windows are stored as date ranges or as fold indices into a separate price series). Heterogeneity across rows must be reported, not silently coerced.
   - Inspect `signal_score_history` — does any column flag "this score was produced by an out-of-sample fit"? If `is_oos` does not exist, you must add it via alembic in A.1; do not silently omit it.

3. **Write the §4.1.a-finding section** as a markdown block appended to this plan file (`docs/plans/edge-deploy-plan.md`) with three subsections:
   - **3.a — `folds_json` shape**: example payload + parser strategy
   - **3.b — `signal_score_history` OOS marker**: present (column name, semantics) or absent (proposed migration)
   - **3.c — leaderboard payload assembly**: confirmed endpoint name + file:line, plus the schema field where you will attach `edge: EdgeMetricsOut | None`

4. **Stop and ask the user before continuing** if any finding contradicts an assumption baked into Workstreams A.1.b–A.1.d. Specifically, raise a flag if:
   - `signal_score_history` has no IS/OOS distinction *and* cannot be augmented because the score-producing pipeline doesn't track it (this would invalidate the whole OOS-only methodology contract in §3.2 and require a deeper redesign).
   - `WfoSignalSummary.folds_json` does not store enough information to reconstruct OOS date ranges per fold.
   - The leaderboard endpoint feeding `/v1` is wired through a denormalized snapshot table that won't accept a per-row payload extension at request time.

Only after this audit lands and the user confirms should you start writing code for A.1.b. The audit cost is ~½ day; the cost of building on bad assumptions is several days of rework.

A note on style: when in doubt, keep changes additive — do not rename functions or break existing test contracts. The methodology fixes specified here are designed to coexist with the current 91+ test suite. Failing existing tests is a regression, not a refactor.

---


## 0. Audience and tone for this document

This is a *contract* with Codex. Every section is written so that an implementing agent can act without re-deriving intent. Treat ambiguity as a bug — when something here is unclear, flag it before implementing.

The plan covers two largely independent workstreams:
- **Workstream A — Edge metrics and methodology hardening** (backend-heavy; the supervisor demo content)
- **Workstream B — Intranet deployment** (infra; ships the demo on company wifi)

Workstream A can be developed locally without B. B unblocks the supervisor handoff.

---

## 1. Architectural decisions — locked

| Concern | Decision | Reason |
|---|---|---|
| **Hosting** | All services (frontend + API + worker + Postgres + Redis + MinIO + Caddy) deploy on a **single Oracle Cloud Always-Free Ampere A1 VM** (4 OCPU, 24 GB RAM, ARM64) via docker-compose | VM already provisioned; user wants single-vendor, single-cost-center, intranet-only |
| **Frontend hosting** | **Inside the same docker-compose**, served by Caddy. Drop Vercel. | Vercel is public-by-default; user requires the app to be reachable only from the company network |
| **Auth** | **Auth.js v5** (NextAuth) with the existing Postgres as the user store via Drizzle adapter. Drop Supabase. | Self-host everything; no external auth dependency |
| **Auth provider** | Credentials provider (email + bcrypt password) for v1; magic-link via SMTP if a relay is available | Intranet, small user list, no social logins needed |
| **Backend ↔ frontend trust** | Auth.js issues HS256 JWT signed with `NEXTAUTH_SECRET`; FastAPI verifies the same secret on every request | Stateless, no shared session table to keep in sync |
| **Network access control** | Caddy IP-allowlist on the company's egress NAT IP(s) + a wireguard "break-glass" path for the maintainer | Oracle Cloud has a public IP; without an allowlist the app is internet-reachable, which contradicts the intranet requirement |
| **CI/CD** | GitHub Actions → multi-arch buildx → GHCR → SSH `docker compose pull && up -d` to the Oracle VM | Free, simple, already common in the codebase's neighbourhood |
| **Account model** | Per-user ownership + `visibility ∈ {private, public}` toggle on user-scoped tables | Future-proofs sharing; private by default |
| **Deferred non-goals** | k8s, partitioning, SSO, audit log, multi-region HA, broker integration, multiple-hypothesis correction, regime-windowed Edge | Documented limitations; explicitly out of scope |

### 1.1 The "company wifi only" requirement — non-trivial

Oracle Cloud gives you a **public IP**. "Only on company wifi" means we have to add an explicit gate. Three viable patterns; pick one and implement it as part of Workstream B before exposing the demo:

| Option | How it works | Cost | Effort |
|---|---|---|---|
| **A. Caddy IP allowlist** *(recommended for v1)* | Caddy `@office { remote_ip <CIDR> }` matcher rejects everything outside the company's egress IP block. | Free | 30 min |
| **B. Tailscale / WireGuard** | VM joins a Tailnet; only Tailnet members reach it. | Tailscale free for ≤100 devices | 1–2 h |
| **C. Real on-prem** | Move the VM into the company network (not Oracle). | Hardware/VLAN | days |

**Decision required from user:** which option, and what is the company's egress IP / CIDR? Codex must NOT proceed with Workstream B Phase B.4 (DNS + TLS) without this answer.

---

## 2. Existing code — what to reuse, what to fix

Codex must read these files end-to-end before implementing. File:line pointers and findings:

### 2.1 `core/quant_core/research/score_history.py`

| Function | Line | Status |
|---|---|---|
| `_bucket_for(score)` | 42 | **Reuse as-is.** Fixed thresholds (`+50/+15/-15/-50`). No look-ahead risk from bucket boundary computation. |
| `_calculate_forward_returns(prices, h, method)` | 205 | **Reuse as-is.** Implements `close_to_close`, `open_to_open`, `close_to_open`, `open_to_close` with correct shifts. |
| `bucketed_forward_returns(score_series, prices, fwd_horizons, …)` | 253 | **REQUIRES MODIFICATION (W A.1).** Today it computes statistics over the entire `aligned_idx` (line 286–293). Has no parameter to constrain to OOS dates. Fix detailed in §4.1.b. |

`BUCKET_NAMES = ("strong_sell", "sell", "hold", "buy", "strong_buy")` (line 38).

### 2.2 `core/quant_core/significance.py`

| Function | Line | Status |
|---|---|---|
| `monte_carlo_luck_test(returns, metric, n_iter, seed, periods_per_year)` | 62 | **Reuse, but the null is "centered-return bootstrap" (line 92).** It tests whether the observed Sharpe / total-return is unlikely under H0: "underlying distribution has zero mean." It is **not** a bucket-informativeness test. Two implications: (1) it's still a useful gate (rejects buckets whose returns are noise around zero); (2) it does NOT prove the bucket carries more information than another bucket. Document this honestly. See §4.1.c for an additional label-shuffle test we will add. |
| `evaluate_significance(returns_by_key, …)` | 125 | Reuse-able if we want per-bucket significance in one call. |

### 2.3 `core/quant_core/research/stats/hit_rate.py`

| Function | Line | Status |
|---|---|---|
| `wilson_ci(k, n, alpha)` | 46 | **Reuse as-is.** Returns `(lower, upper)` for a binomial proportion. |

### 2.4 Persistence — where OOS lives

| Table | Model file | OOS information |
|---|---|---|
| `wfo_signal_summary` | `services/api/app/models.py:672` | `folds_json` (line 687) contains per-fold IS/OOS returns + window dates. Must be parsed to reconstruct OOS date ranges per (symbol, category, horizon, variant). |
| `wfo_global_signal` | `services/api/app/models.py:716` | Top-level consensus only — no fold-level OOS data. |
| `signal_engine_family_result` | `services/api/app/models.py:769` | `family_detail_json` (line 795) — verbatim `_build_family_snapshot()` output. Codex must read `_build_family_snapshot()` to determine whether OOS dates are present and in what shape. **If absent**, we must extend it; spec in §4.1.b.iii. |
| `signal_engine_global_result` | `services/api/app/models.py:823` | Aggregate — no fold-level OOS. |
| `signal_score_history` | per project memory: per-bar score history (date/symbol/source/category/horizon composite PK) | Source of truth for the score series fed into `bucketed_forward_returns`. Codex must check whether each row carries an `is_oos` flag; **if not**, Workstream A.1 includes adding it via alembic. |

### 2.5 Indicator parameter registry

Codex must read `core/quant_core/signal_engine/domain.py` (and `family_registry.py` if it exists) to find the indicator-parameter search space. The horizon-aware parameter cap (§4.1.d) must be applied at search-space construction time, not at evaluation time, so that capped searches never visit slow parameters and don't pollute the cached results.

### 2.6 Frontend dashboard

`frontend/app/v1/page.tsx` (385 lines today) is the page to restructure. The leaderboard payload that feeds it: per project memory, `services/api/app/routers/runs.py::list_strategy_leaderboard` is the prime suspect — Codex must verify and report the actual endpoint before §4.4.

---

## 3. Methodology specification — non-negotiable contract

Every Edge value displayed on the dashboard must satisfy these properties. Violations are bugs, not stylistic differences.

### 3.1 The bucket is the day's actual signal — never anything else

For each opportunity row at horizon h on the dashboard:

```
bucket(symbol, h) := bucket_label_from(latest_score(symbol, h, source))
```

There is **no `pick_best_bucket` function**, no "best-historical-bucket" override, no UI affordance to pick a different bucket in v1. The day's signal *is* the bucket. This solves the selection-bias problem cleanly because we are not choosing the bucket; the signal chooses it for us.

### 3.2 OOS-only forward-return statistics

All of `expected_return`, `hit_rate`, `std`, `profit_factor`, `expectancy`, `mc_luck_pvalue`, `bh_expected_return` for a `(symbol, horizon, source)` cell must be computed using **only** the dates `D_OOS(symbol, horizon, source)` defined as:

- **For `source = "wfo"`:** the union of test-window date ranges across all WFO folds for that (symbol, horizon).
- **For `source = "signal_engine"`:** the dates on which the score series was produced from a model fitted *not using* that day's data — i.e., a leave-one-out, expanding-window, or rolling-window scheme. Codex must confirm one of these is true today; if not, this requires an upstream fix.

The benchmark `bh_expected_return` is the mean forward return across **all OOS dates for the symbol at horizon h** (no bucket filter, same OOS date set as the cell statistics — same denominator universe).

### 3.3 Recent-window sample policy

For the bucket-cell statistics, take the **most recent N OOS observations** of the same bucket label, with:
- `N_target = 60`, `N_min = 30`
- Bounded by `max_lookback_years = 3` regardless of N
- If `n < 30`, badge fires **`insufficient`** (grey), not `proven_edge`

The window must be defined symmetrically across all symbols and horizons displayed in a single dashboard render — i.e., the window endpoint for every cell is the latest OOS date of the (symbol, horizon, source) up to *today*, not "today" globally. This avoids cross-symbol date mismatches when symbols have different data availability.

### 3.4 Canonical expectancy decomposition

For a bucket with OOS forward returns `r_1 … r_n` and `direction ∈ {long, short}`:

```
wins   = { r_i :  sgn(r_i) == sgn_for(direction) }   # long: r_i > 0; short: r_i < 0
losses = { r_i :  sgn(r_i) != sgn_for(direction) }   # zero treated as loss
P_win  = |wins|   / n
P_loss = |losses| / n
avg_win  = mean(wins)   if wins   else 0
avg_loss = mean(losses) if losses else 0   # negative number for long, positive for short
expectancy_canonical = P_win * avg_win - P_loss * avg_loss   # for short, sign-flip the whole thing so positive = good
expectancy_arith = mean(r_i)
# Invariant: expectancy_canonical == expectancy_arith (within 1e-9). Both are surfaced to satisfy quant audiences.
```

For `strong_buy` and `buy` buckets: `direction = long`. For `strong_sell` and `sell`: `direction = short`. For `hold`: skip — Edge tile renders nothing for `hold` buckets (the symbol is not actionable today).

### 3.5 Profit factor

```
pos_sum = sum(r_i for r_i in r if r_i > 0)
neg_sum = sum(-r_i for r_i in r if r_i < 0)
profit_factor = pos_sum / neg_sum  if neg_sum > 0 else None  # None means "all wins; cannot compute"
```

Frontend renders `None` as `—` with tooltip "Pas de pertes dans l'échantillon." It is not the same as 0 or ∞; do not coerce.

### 3.6 Edge ratio

```
edge_ratio = mean(r) / std(r, ddof=1)   if n > 1 and std > 0 else None
```

This is a per-trade signal-to-noise ratio. The display label is **"Ratio d'edge"**, not "Sharpe." The tooltip explains the formula and explicitly disclaims the Sharpe analogy.

### 3.7 The four gates — definition of "Proven Edge"

`proven_edge := mc & wilson & bh & n` where each gate is a boolean:

| Gate | Pass condition | Threshold rationale |
|---|---|---|
| `mc` | `mc_luck_pvalue < 0.01` | Stricter than 0.05; partial mitigation for deferred multiple-testing correction |
| `wilson` | `hit_ci_lower > 0.50` (long buckets) or `hit_ci_upper < 0.50` (short buckets, where "win" means `r < 0`) | Wilson lower bound clears the random-direction baseline |
| `bh` | `expected_return > bh_expected_return` (long) or `expected_return < bh_expected_return` (short) | Beats the do-nothing benchmark on the same OOS window |
| `n` | `n >= 30` | Floor for the Wilson CI to be meaningful |

The drill-down panel shows pass/fail per gate with the actual value vs threshold for each. **No gate has a UI affordance to override.**

### 3.8 Honest framing — for the demo

The drill-down's "Methodology" section must include these three caveats verbatim (Codex implements as a static accordion at the bottom of the panel):

> **Limites assumées.** (1) Pas de correction multi-hypothèses sur les p-valeurs : avec ~76 symboles × 3 horizons × 2 sources, on attend ~5% de faux positifs au seuil p < 0.05 ; le seuil est durci à p < 0.01 pour partiellement compenser. (2) Le test de Monte Carlo employé (`bootstrap_centered_returns`) teste si la moyenne des retours est non nulle, pas si l'étiquette de bucket est informative. Un test complémentaire de permutation des étiquettes est calculé séparément (voir §4.1.c) et exposé dans la même panneau. (3) Toutes les statistiques sont calculées sur la fenêtre des 30–60 dernières observations OOS (≤ 3 ans) — pertinentes pour le régime actuel, peu fiables hors régime.

---

## 4. Workstream A — Edge metrics & methodology hardening

Estimated total: **3.5–5 working days**, sequenced as follows. Sub-phases A.1 and A.2 must complete before A.3; A.3 and A.4 can overlap.

### 4.1 — Phase A.1 · OOS-aware foundation (1.5–2 days)

#### A.1.a — Audit `_build_family_snapshot()` and `signal_score_history` for OOS markers (½ day, *gate before everything else*)

Codex deliverables:

1. Read `core/quant_core/signal_engine/` to find `_build_family_snapshot` and any per-bar score-history producer.
2. Determine: does each row in `signal_score_history` already carry a flag indicating whether the score for that (date, symbol, source) was produced via an out-of-sample fit? If yes, name the column and the semantics in a one-paragraph audit note inserted into this plan as §4.1.a-finding. If no, propose a column to add (e.g., `is_oos BOOLEAN NOT NULL DEFAULT false`) with an alembic migration; backfill semantics specified in A.1.b.iii.
3. Read `WfoSignalSummary.folds_json` schema by inspecting at least 5 production rows. Document the JSON shape for `folds_json[*].oos_window` (or whatever the field is called) in §4.1.a-finding. If the shape is heterogeneous across rows, propose a defensive parser.

**STOP here and report findings before continuing.** A.1.b depends on these answers.

#### A.1.b — `oos_dates_for(symbol, horizon, source) -> set[pd.Timestamp]`  (½ day)

New module: `core/quant_core/research/oos_index.py`. Pure functions only. No I/O — receives data via injected loaders so it is unit-testable with synthetic inputs.

```python
@dataclass(frozen=True)
class OosWindow:
    start: pd.Timestamp  # inclusive
    end:   pd.Timestamp  # inclusive

def oos_windows_from_wfo(folds_json: list[dict]) -> list[OosWindow]:
    """Parse WfoSignalSummary.folds_json into normalized OOS windows.
    Tolerates the actual fold shape established in A.1.a-finding."""

def oos_dates_for_signal_engine(score_history_rows: Iterable[ScoreRow]) -> set[pd.Timestamp]:
    """Returns the date set where score was produced under an OOS fit.
    Source of truth: signal_score_history.is_oos == True (after A.1.a)."""

def oos_date_index(*, symbol: str, horizon: int, source: Literal["wfo", "signal_engine"],
                   wfo_loader: Callable, score_history_loader: Callable) -> pd.DatetimeIndex:
    """Top-level entry. Returns a sorted, tz-naive DatetimeIndex.
    Caches by (symbol, horizon, source, content_hash) for the duration of a request."""
```

**Tests** in `core/tests/test_oos_index.py`:
- `test_wfo_folds_simple`: synthetic `folds_json` with two non-overlapping windows; assert returned `OosWindow` list matches.
- `test_wfo_folds_overlapping`: deliberately overlapping windows; assert merged correctly.
- `test_wfo_folds_missing_field`: shape variation; assert defensive parser returns what it can without raising.
- `test_signal_engine_filters_is_rows`: two rows with `is_oos=True`, one with `is_oos=False`; assert the IS row is excluded.
- `test_oos_date_index_union_when_sources_combined`: integration shape (does not need a real DB).

#### A.1.c — Refactor `bucketed_forward_returns` to be OOS-aware (½ day)

**File:** `core/quant_core/research/score_history.py:253`.

Add an `oos_dates: pd.DatetimeIndex | None = None` keyword-only parameter. **Default `None` preserves current behavior** — do not break existing callers (per project memory: 91+ tests must stay green).

```python
def bucketed_forward_returns(
    score_series: pd.Series,
    prices: pd.Series | pd.DataFrame,
    fwd_horizons: Iterable[int],
    *,
    n_bootstrap: int = 5000,
    return_calc_method: str = "close_to_close",
    oos_dates: pd.DatetimeIndex | None = None,   # NEW
    recent_window: tuple[int, int] | None = None, # NEW: (n_min, n_target). When set, after OOS filter, take the most recent up to n_target obs per (bucket, h) cell.
    max_lookback_years: float | None = None,      # NEW: hard ceiling
) -> list[dict[str, Any]]:
```

Logic order (insert immediately after `aligned_idx` is computed at line 281):

```python
if oos_dates is not None:
    aligned_idx = aligned_idx.intersection(pd.DatetimeIndex(oos_dates))
if max_lookback_years is not None and len(aligned_idx) > 0:
    cutoff = aligned_idx.max() - pd.Timedelta(days=int(365.25 * max_lookback_years))
    aligned_idx = aligned_idx[aligned_idx >= cutoff]
```

The recent-window-per-bucket sub-selection happens inside the existing per-bucket loop (after `sub = df[df["bucket"] == b]`):

```python
if recent_window is not None:
    n_min, n_target = recent_window
    sub = sub.sort_index().tail(int(n_target))
    if len(sub) < n_min:
        cells.append(_empty_cell(b, h, n=int(len(sub))))
        continue
```

**Tests** in `core/tests/test_bucketed_forward_returns_oos.py`:
- `test_oos_filter_preserves_existing_behavior_when_none`: existing semantics unchanged when `oos_dates=None`. Run on a fixture that exists today (or build one from synthetic data).
- `test_oos_filter_drops_is_dates`: synthetic series where IS rows have `+5%` returns and OOS rows have `0%` returns; assert that `oos_dates=<OOS only>` yields `mean ≈ 0`, `oos_dates=None` yields `mean > 0`.
- `test_max_lookback_years_caps_window`: 5-year synthetic; `max_lookback_years=2` excludes years 0–3.
- `test_recent_window_picks_last_N`: 200 rows in a bucket; `recent_window=(30,60)` returns stats over the last 60.
- `test_insufficient_sample_emits_empty_cell`: `recent_window=(30,60)` with only 25 rows → `_empty_cell` with n=25.

#### A.1.d — Horizon-aware indicator parameter caps (½ day)

**File:** `core/quant_core/signal_engine/domain.py` (or the file where the indicator search space is constructed — Codex confirms in A.1.a-finding).

Add a constant and helper:

```python
HORIZON_PARAM_CAP: dict[str, dict[str, int]] = {
    "short":  {"sma": 20,  "ema": 20,  "rsi": 14, "macd_slow": 13, "stoch": 14, "obv_ema": 20, "ichimoku_kijun": 26},
    "medium": {"sma": 50,  "ema": 50,  "rsi": 21, "macd_slow": 26, "stoch": 14, "obv_ema": 21, "ichimoku_kijun": 26},
    "long":   {"sma": 200, "ema": 100, "rsi": 21, "macd_slow": 26, "stoch": 21, "obv_ema": 50, "ichimoku_kijun": 52},
}

def cap_param_grid(grid: dict[str, list[int]], horizon: str, family: str) -> dict[str, list[int]]:
    """Filter grid in-place; remove parameter values above the horizon cap.
    Raises if every value of a required parameter would be filtered out."""
```

Apply at search-space construction time in every place a parameter grid is built per family. Codex enumerates these call sites in the implementation report.

**Cache invalidation.** The change of search space changes the input hash that `signal_engine_family_result.input_hash` (line 806) uses. Codex confirms the hash includes a version of `HORIZON_PARAM_CAP` (or bumps a global `SIGNAL_ENGINE_VERSION` constant that flows into the hash) so that prior caches are invalidated automatically on deploy.

**Tests** in `core/tests/test_horizon_param_cap.py`:
- For each horizon × each family in the registry, assert no value in the constructed grid exceeds its cap.
- Assert that running the cap on an already-capped grid is idempotent.

### 4.2 — Phase A.2 · Edge module + endpoint + caching (1.5–2 days)

#### A.2.a — `core/quant_core/research/edge.py` (½ day)

Pure functions only. Imports from `score_history` and `significance` only — no DB, no SQLAlchemy.

```python
@dataclass(frozen=True)
class ExpectancyDecomp:
    p_win: float
    avg_win: float        # signed: positive for long, negative for short (because "win" means in-direction)
    p_loss: float
    avg_loss: float       # signed: opposite of avg_win
    expectancy: float     # P_win*avg_win - P_loss*avg_loss; compare equal to arithmetic mean

@dataclass(frozen=True)
class EdgeGates:
    mc: bool       # mc_luck_pvalue < 0.01
    wilson: bool   # hit_ci bounds clear the 0.5 baseline appropriate for direction
    bh: bool       # ER beats B&H in direction-correct sense
    n: bool        # n >= 30

@dataclass(frozen=True)
class EdgeMetrics:
    symbol: str
    horizon: int
    source: Literal["signal_engine", "wfo"]
    bucket: str                # one of BUCKET_NAMES
    direction: Literal["long", "short", "none"]
    n: int
    window_start: pd.Timestamp | None
    window_end:   pd.Timestamp | None
    expected_return: float | None
    hit_rate: float | None
    hit_ci_lower: float | None
    hit_ci_upper: float | None
    expectancy: ExpectancyDecomp | None
    edge_ratio: float | None
    profit_factor: float | None
    mc_luck_pvalue: float | None
    label_shuffle_pvalue: float | None  # see A.1.c
    bh_expected_return: float | None
    proven_edge: bool
    gates: EdgeGates
    methodology_version: str   # bump on any algo change so frontend can detect stale cache

def compute_canonical_expectancy(returns: np.ndarray, direction: Literal["long", "short"]) -> ExpectancyDecomp: ...
def compute_profit_factor(returns: np.ndarray) -> float | None: ...
def compute_edge_ratio(mean: float, std: float) -> float | None: ...
def direction_for_bucket(bucket: str) -> Literal["long", "short", "none"]: ...
def build_edge_payload(*, symbol, horizon, source, score_series, prices,
                       oos_dates, today_bucket: str, n_min=30, n_target=60,
                       max_lookback_years=3.0, mc_iter=2000, mc_seed=42) -> EdgeMetrics: ...
```

`build_edge_payload` orchestrates: calls `bucketed_forward_returns(..., oos_dates=oos_dates, recent_window=(n_min, n_target), max_lookback_years=max_lookback_years)` for `fwd_horizons=[horizon]`; pulls the cell for `today_bucket`; calls `monte_carlo_luck_test(returns, metric="total_return")`; calls `monte_carlo_label_shuffle_test` (A.1.c-NEW below); computes expectancy, edge_ratio, profit_factor; computes B&H; assembles gates; returns `EdgeMetrics`.

#### A.1.c-NEW — `monte_carlo_label_shuffle_test` (½ day, slotted with A.2.a)

The existing `monte_carlo_luck_test` does centered-return bootstrap. We need a complementary test with the right null for bucket informativeness. Add to `core/quant_core/significance.py`:

```python
def monte_carlo_label_shuffle_test(
    score_series: pd.Series,
    forward_returns: pd.Series,
    *,
    bucket: str,
    n_iter: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """H0: bucket assignment is uninformative — i.e., shuffling the score-to-date
    mapping gives a distribution of bucket-mean-returns equivalent to the observed.
    Returns the same shape as monte_carlo_luck_test. The 'observed' field is the
    actual bucket mean; the null is built by shuffling score_series's index labels
    (preserving the marginal score distribution) and recomputing the bucket mean."""
```

Tests:
- `test_label_shuffle_pvalue_close_to_one_when_no_signal`: random scores → p-value ~uniform → for a single iter with n_iter=2000, expect p ≥ 0.4 most of the time.
- `test_label_shuffle_pvalue_low_when_strong_signal`: deterministic positive return on `strong_buy` dates only → p-value < 0.01.
- `test_label_shuffle_seed_determinism`: same seed twice → identical p-value.

This adds `label_shuffle_pvalue` to `EdgeMetrics`. The drill-down panel surfaces it as a **secondary** check; it does **not** participate in the `proven_edge` gate (one MC test in the gate is enough; the second is for transparency).

#### A.2.b — Endpoint and caching (½ day)

**Endpoint:** `GET /analytics/edge` in `services/api/app/routers/analytics.py`.

Query params (all required unless marked):
- `symbol: str`
- `horizon: int` (in trading days)
- `source: Literal["signal_engine", "wfo"]`

Response: `EdgeMetricsOut` Pydantic model in `services/api/app/schemas/edge.py` mirroring the dataclass exactly. Use `model_config = ConfigDict(from_attributes=True)`.

**Caching:**
- Redis key: `edge:v{methodology_version}:{source}:{symbol}:{horizon}:{score_revision_hash}`
- TTL: 25 hours (24 + buffer to outlast the next EOD refresh under DST quirks)
- `score_revision_hash` is the SHA-256 of `(data_as_of, latest score_series row count, latest folds_json hash)` per (symbol, horizon, source). When any of those change, cache key changes, no invalidation needed.
- Cold-cache behavior: endpoint returns `null` body and `200 OK` with header `X-Edge-Cache: cold`. Frontend renders shimmer.

**Warming task:** `services/worker/tasks/refresh_edge_cache.py::warm_edge_cache(symbols, horizons, sources)`. Triggered by APScheduler immediately after the daily 20:00 Africa/Casablanca score refresh, and on-demand via `POST /analytics/edge/warm` (admin-only — see Workstream B auth).

#### A.2.c — Dashboard payload integration (½ day)

Codex first verifies the leaderboard endpoint feeding `frontend/app/v1/page.tsx` (project memory points at `services/api/app/routers/runs.py::list_strategy_leaderboard`). Once confirmed:

- Extend `StrategyLeaderboardOut` schema with `edge: EdgeMetricsOut | None`.
- In the assembler, look up the cached Edge for each `(symbol, current_horizon, source)`. Source is selected by the user via the existing score-source toggle (see project memory on `dashboard_score_source`). If `EDGE_INLINE_LIMIT` (env, default 200ms) elapses, return `null` for the rest and let the frontend fetch them per row via `/analytics/edge`.

#### A.2.d — Tests

`core/tests/test_edge_metrics.py`:
- `test_canonical_expectancy_matches_arithmetic_within_1e9` — invariant (3.4)
- `test_canonical_expectancy_short_signal_inverts_sign`
- `test_profit_factor_no_losses_returns_none`
- `test_profit_factor_no_wins_returns_zero`
- `test_profit_factor_known_value` — fixture: `[+1, +2, -1, -2]` → PF = 3/3 = 1.0
- `test_edge_ratio_zero_std_returns_none`
- `test_proven_edge_all_gates_pass` — synthetic data engineered to pass each gate
- `test_proven_edge_fails_when_n_below_30`
- `test_proven_edge_fails_when_mc_pvalue_above_threshold`
- `test_proven_edge_fails_when_wilson_lower_below_half`
- `test_proven_edge_fails_when_er_below_bh`
- `test_oos_filter_excludes_is_dates_end_to_end`

`services/api/tests/test_edge_endpoint.py`:
- `test_happy_path` — warm cache returns full payload
- `test_cold_cache_returns_null_with_header`
- `test_source_switch_returns_different_payload`
- `test_unknown_symbol_returns_404`
- `test_horizon_zero_returns_422`

### 4.3 — Phase A.3 · Dashboard restyle from Claude design (1.5–2 days)

Source of truth: `C:\tmp\claude_design\project\ui_kits\app\01-dashboard.html`. Tokens and atoms in `_shared.css` and `colors_and_type.css` next to it.

#### A.3.a — Atoms (½ day)

Extract reusable shadcn-flavored components in `frontend/components/ui/` and `frontend/components/dashboard/`:

| Component | File | Spec |
|---|---|---|
| `SignalBadge` | `frontend/components/ui/signal-badge.tsx` | Props `family: 'trend'\|'momentum'\|'oscillation'\|'volume'\|'composite'`, `score: number`. Maps score to one of 5 levels (per §3.7-style thresholds). Renders the right French label per family (the design's `famLabel` / `aggLabel`) with the right token class (`sig-bull-strong` … `sig-bear-strong`). |
| `Eyebrow` | `frontend/components/ui/eyebrow.tsx` | Tailwind: `text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground`. |
| `Segmented` | `frontend/components/ui/segmented.tsx` | Pill row with active = card-with-shadow. Generic typed by option value. |
| `SetupStep` | `frontend/components/dashboard/setup-step.tsx` | `{ index, title, options, value, hint, onChange }`. Renders the design's `.step` block. |
| `KpiTile` | `frontend/components/dashboard/kpi-tile.tsx` | `{ label, value, sub, tone? }`. Renders the design's `.stat` block. |
| `EdgeTile` | `frontend/components/dashboard/edge-tile.tsx` | Detailed below. |
| `EdgePanel` | `frontend/components/dashboard/edge-panel.tsx` | Detailed below. |

#### A.3.b — Restructure `frontend/app/v1/page.tsx`

Layout, top to bottom:

1. Page header (`Tableau de Bord V1`, sub line, action buttons `[Filtres][Exporter][Recalculer]`). Reuse the design.
2. KPI strip — 4 tiles: `Univers actif` / `Signaux haussiers` / `Signaux baissiers` / `E[R] médian (opt.)` (the last derives from the new Edge data — median of `expected_return` across rows where `proven_edge=true`).
3. 5 setup steps row: `1. Horizon` (Court/Moyen/Long), `2. Univers` (Actions/Secteurs/Indices), `3. Source` (Signal Engine/WFO/Les deux), `4. Catégorie` (Toutes/Très liq./Mid), `5. S/R` (Off/Auto/Manuel).
4. Market hierarchy tabs (`mktabs`) + sub-tabs (`subtabs`).
5. Filter bar with chips: liquidity (active/inactive amber), sector dropdown, search input, glossary link, **new**: `[ ] Edge prouvé seulement` toggle.
6. Signal table:
   - Columns (per design 01-dashboard, **defer 7J sparkline column**):
     - `[ ]` selection / `Ticker` / `Nom` / `Prix` / `Var.` / `ADV20` / `Trend.` / `Mom.` / `Osc.` / `Vol.` / `Signal` / `E[R]` (with period selector) / `Hit% [IC 95%]` / `→`
   - The Edge tile lives in the existing card layout above the row, OR (preferred) as a wide column on the rightmost side called `Edge` showing edge ratio + small expectancy decomposition.
   - Default sort: `proven_edge desc → edge_ratio desc → opportunity_score desc`.
7. Footer note (E[R] formula + IC explanation + glossary link).

#### A.3.c — `EdgeTile` spec

Compact card visible on every row (or as a column cell, depending on the layout chosen in A.3.b):

```
┌─────────────────────────────────┐
│  Edge ratio                  ★  │   ← star = Proven Edge badge (green); hollow if not
│  +0,42                          │   ← edge_ratio formatted with sign and locale
│  +1,8% · 64% · PF 1,42 · n=42   │   ← ER · HR · PF · n  (one line, mono)
│  42 obs OOS · 18 mois           │   ← window
└─────────────────────────────────┘
```

Click → opens `EdgePanel` for that row.

States: cold-cache → shimmer; `bucket == "hold"` → tile renders dim "Pas de signal aujourd'hui" with no metrics; `n < 30` → grey badge "Insuffisant" with tooltip "Échantillon < 30 obs OOS".

#### A.3.d — `EdgePanel` spec

Slide-over panel (use existing `Sheet` component from `frontend/components/ui/sheet.tsx`), opened from the tile.

Sections, top to bottom:

1. **Header** — `<symbol> · <horizon>j · source: <Signal Engine|WFO>` toggle for source (refetches on change). Bucket label as a read-only chip (no override affordance, per §3.1).
2. **4-gate checklist:**
   ```
   ✓ Test de chance MC : p = 0.004 (< 0.01)
   ✓ Wilson LB : 0.58 (> 0.50)
   ✓ Bat le buy-and-hold : +1.8% > +0.4%
   ✓ Échantillon : 42 (≥ 30)
   ```
3. **Test complémentaire (label shuffle)** — `Label-shuffle MC : p = 0.012` with one-line explainer.
4. **Décomposition de l'expectance** — table:
   ```
   P(gain)  = 0.61    avg_gain = +2.10%
   P(perte) = 0.39    avg_perte = -1.40%
   E = 0.61·2.10 - 0.39·1.40 = +0.74%   ← matches mean returns
   ```
5. **Distribution des retours OOS du bucket** — small histogram (Recharts bar). 20 bins between min and max, vertical guide at zero.
6. **Méthodologie / limites** — accordion with the verbatim text from §3.8.
7. **Lien** — "Voir matrice prédictive complète" → `/analytics?symbol=<sym>&horizon=<h>`.

#### A.3.e — Frontend API client

`frontend/lib/api.ts`:
- `EdgeMetricsSchema` (Zod) mirroring `EdgeMetricsOut`.
- `fetchEdge(symbol: string, horizon: number, source: 'signal_engine'|'wfo'): Promise<EdgeMetrics | null>` — returns `null` on cold-cache.

#### A.3.f — Feature flag

Env var `NEXT_PUBLIC_EDGE_ENABLED` (default `true`). When `false`:
- `EdgeTile` returns `null`.
- The `Edge prouvé seulement` filter and the badge-first sort are hidden.
- The `E[R]` and `Hit% [IC 95%]` columns fall back to `—` (or the columns are hidden — Codex picks the cleaner of the two; document the choice).

### 4.4 — Phase A.4 · Verification

| Check | How |
|---|---|
| All A.1 / A.2 unit tests green | `python -m pytest core/tests/test_oos_index.py core/tests/test_bucketed_forward_returns_oos.py core/tests/test_horizon_param_cap.py core/tests/test_edge_metrics.py services/api/tests/test_edge_endpoint.py -q` |
| Full backend suite still green | `python -m pytest core/tests/ -q` (must be ≥ existing pass count) |
| Manual API check | `curl 'http://localhost:8000/analytics/edge?symbol=ATW&horizon=21&source=signal_engine'` returns sensible JSON; gates parse; mean ≈ canonical expectancy. |
| Source switch | Same call with `source=wfo` returns a different payload. |
| Frontend build | `npm --prefix frontend run typecheck && npm --prefix frontend run build` clean. |
| Demo dry-run | Pick 2–3 symbols where `proven_edge=true`. Walk: row → drill-down → 4 gates → decomposition → histogram → cross-link. Pick 1 with `false`. Pick 1 with `bucket=hold`. Pick 1 with `n<30`. All four states render without error. |

---

## 5. Workstream B — Intranet deployment (single-VM, all-Docker)

Estimated total: **2–3 working days** parallel to or after A.

### 5.1 — Phase B.1 · Stack composition (½ day)

**Single docker-compose stack** running on the Oracle VM, reachable behind Caddy with IP allowlist:

```
caddy            (80, 443 public; IP-allowlisted)
  ├── frontend   (Next.js standalone; port 3000)
  ├── api        (FastAPI; port 8000)
  └── (Auth.js shares the frontend container — no separate service)
worker           (RQ; no exposed port)
postgres         (port 5432; only on internal network)
redis            (port 6379; only on internal network)
minio            (port 9000 + 9001 console; admin-only path under Caddy)
```

Frontend Dockerfile becomes a real production build:

```Dockerfile
# frontend/Dockerfile
FROM node:22-alpine AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
```

`frontend/next.config.js` must set `output: 'standalone'` for the multi-stage build to produce `server.js`.

`infra/docker-compose.gcp.yml` adds a `frontend` service pulling `ghcr.io/<owner>/bt-frontend:<tag>`.

### 5.2 — Phase B.2 · Auth.js v5 + Postgres adapter (1–1.5 days)

**Why Auth.js v5 specifically:** v5 (`next-auth@beta` as of writing) is the App Router-native API. It supports the Drizzle adapter for Postgres, JWT sessions out of the box, and clean middleware integration.

#### B.2.a — Schema

Auth.js owns four tables: `users`, `accounts`, `sessions`, `verification_tokens`. They live in the existing Postgres database, in the public schema (avoids needing Auth.js to know about a separate schema). Migration via Drizzle:

- `frontend/auth/schema.ts` defines the four tables with the exact shape the Drizzle Auth.js adapter expects. This is **separate from** the SQLAlchemy models — Drizzle only writes/reads these four tables; SQLAlchemy never touches them.
- `frontend/auth/migrate.ts` is a one-shot runner: `npm run db:auth-migrate` applies missing migrations on deploy. Add to the deploy workflow.

#### B.2.b — Auth.js config

`frontend/auth/index.ts`:

```ts
import NextAuth from "next-auth"
import Credentials from "next-auth/providers/credentials"
import { DrizzleAdapter } from "@auth/drizzle-adapter"
import { db } from "./db"
import bcrypt from "bcryptjs"
import { z } from "zod"

const Creds = z.object({ email: z.string().email(), password: z.string().min(8) })

export const { auth, handlers, signIn, signOut } = NextAuth({
  adapter: DrizzleAdapter(db),
  session: { strategy: "jwt" },
  trustHost: true,            // intranet: Caddy fronts us; X-Forwarded-Host trusted
  pages: { signIn: "/login" },
  providers: [
    Credentials({
      credentials: { email: {}, password: {} },
      authorize: async (raw) => {
        const parsed = Creds.safeParse(raw)
        if (!parsed.success) return null
        const u = await db.query.users.findFirst({ where: eq(users.email, parsed.data.email) })
        if (!u || !u.passwordHash) return null
        const ok = await bcrypt.compare(parsed.data.password, u.passwordHash)
        return ok ? { id: u.id, email: u.email } : null
      },
    }),
  ],
  callbacks: {
    jwt: ({ token, user }) => { if (user) token.uid = user.id; return token },
    session: ({ session, token }) => { session.user.id = token.uid as string; return session },
  },
})
```

`frontend/middleware.ts`:

```ts
export { auth as middleware } from "@/auth"
export const config = { matcher: ["/((?!api/auth|_next|login|signup|favicon|public).*)"] }
```

`frontend/app/api/auth/[...nextauth]/route.ts` exports `handlers.GET` and `handlers.POST`.

`frontend/app/login/page.tsx`, `frontend/app/signup/page.tsx`, `frontend/app/account/page.tsx` — minimal shadcn forms; signup writes to `users` with `bcrypt.hash(password, 12)` and an admin must approve (a `users.is_active BOOLEAN DEFAULT false` column gate). For v1 with a small user list this is acceptable; document that signup is "request access" not "instant access".

#### B.2.c — FastAPI verifies Auth.js JWT

Auth.js with `session.strategy: "jwt"` issues a **JWE-encrypted JWT** by default (using `NEXTAUTH_SECRET`). FastAPI must decrypt and verify.

Two clean options; pick **option 2** for simplicity:

- **Option 1:** Auth.js custom `encode/decode` using HS256 plain JWT; FastAPI verifies HS256 with `python-jose`. Trade-off: weakens token confidentiality (anyone who reads the cookie sees claims).
- **Option 2 (recommended):** Frontend's API proxy at `frontend/app/api/[...path]/route.ts` reads `auth()` server-side, gets the user id, and forwards to the backend with a short-lived **internal JWT** signed by `INTERNAL_JWT_SECRET` (HS256). The browser never sees this token. FastAPI verifies HS256.

```ts
// frontend/app/api/[...path]/route.ts (sketch)
import { auth } from "@/auth"
import jwt from "jsonwebtoken"

export async function GET(req: Request, ctx: { params: { path: string[] } }) {
  const session = await auth()
  if (!session?.user) return new Response("Unauthorized", { status: 401 })
  const internalToken = jwt.sign(
    { sub: session.user.id, email: session.user.email },
    process.env.INTERNAL_JWT_SECRET!,
    { algorithm: "HS256", expiresIn: "5m" }
  )
  const url = `${process.env.API_BASE}/${ctx.params.path.join("/")}${new URL(req.url).search}`
  return fetch(url, { headers: { Authorization: `Bearer ${internalToken}` } })
}
// (and similar for POST/PUT/PATCH/DELETE)
```

`services/api/app/auth.py::get_current_user` decodes the HS256 token, returns `User(id=UUID(claims["sub"]), email=claims["email"])`.

#### B.2.d — Multi-tenancy schema

Same migration as in §6.1 (W A's parallel deliverable, but not required for the demo). Codex implements after Workstream A ships:
- Add `owner_id UUID NOT NULL` and `visibility ENUM('private','public') NOT NULL DEFAULT 'private'` to: `run`, `dataset`, `saved_strategy`, `strategy_decision`, `strategy_leaderboard`, `signal_backtest_run`, `wfo_signal_summary`. **Not** to shared catalogs.
- Backfill `owner_id` to a seed admin user; set NOT NULL.
- All routers filter `or_(owner_id == user.id, visibility == 'public')` on read and require `owner_id == user.id` on write.

### 5.3 — Phase B.3 · Image build, registry, deploy (1 day)

`.github/workflows/build-images.yml`:

```yaml
name: build-images
on:
  push: { branches: [main], paths: ['services/**', 'core/**', 'frontend/**', 'pyproject.toml'] }
jobs:
  build:
    runs-on: ubuntu-latest
    permissions: { contents: read, packages: write }
    strategy:
      matrix: { svc: [api, worker, frontend] }
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-qemu-action@v3
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with: { registry: ghcr.io, username: ${{ github.actor }}, password: ${{ secrets.GITHUB_TOKEN }} }
      - uses: docker/build-push-action@v5
        with:
          context: .
          file: services/${{ matrix.svc == 'frontend' && 'frontend' || matrix.svc }}/Dockerfile
          platforms: linux/arm64
          push: true
          tags: |
            ghcr.io/${{ github.repository_owner }}/bt-${{ matrix.svc }}:${{ github.sha }}
            ghcr.io/${{ github.repository_owner }}/bt-${{ matrix.svc }}:latest
          cache-from: type=gha
          cache-to:   type=gha,mode=max
```

(File path mapping for `frontend` is messy — the workflow above uses a ternary; if your matrix expression doesn't permit it, split into three jobs or add a `dockerfile` matrix key.)

`.github/workflows/deploy-vm.yml`:

```yaml
name: deploy-vm
on:
  workflow_run:
    workflows: [build-images]
    types: [completed]
    branches: [main]
jobs:
  deploy:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    steps:
      - uses: appleboy/ssh-action@v1
        with:
          host:     ${{ secrets.ORACLE_HOST }}
          username: deploy
          key:      ${{ secrets.ORACLE_SSH_KEY }}
          script: |
            set -euo pipefail
            cd /opt/bt
            git fetch && git reset --hard origin/main
            docker compose --env-file /etc/bt/env pull
            docker compose --env-file /etc/bt/env run --rm api alembic -c alembic.ini upgrade head
            docker compose --env-file /etc/bt/env run --rm frontend npm run db:auth-migrate
            docker compose --env-file /etc/bt/env up -d --remove-orphans
            docker image prune -f
      - name: smoke
        run: |
          curl -fsS https://api.${{ secrets.DOMAIN }}/health
          curl -fsS https://app.${{ secrets.DOMAIN }}/login | grep -q "Connexion"
```

ARM64 build validation pre-commit: run locally `docker buildx build --platform linux/arm64 -f services/worker/Dockerfile .` to surface numba/numpy issues before pushing the workflow.

### 5.4 — Phase B.4 · Caddy IP allowlist + DNS (½ day, blocked on §1.1 decision)

`infra/Caddyfile.gcp` excerpt:

```
{
  email <ops@<domain>>
}

(office_only) {
  @office {
    remote_ip <COMPANY_EGRESS_CIDR>     # e.g., 196.200.10.0/24
    remote_ip <MAINTAINER_VPN_CIDR>     # e.g., a Tailscale 100.64.0.0/10
  }
  handle @office {
    respond ""                          # placeholder; real handlers per route
  }
  handle {
    respond "Forbidden" 403
  }
}

api.<domain> {
  import office_only
  reverse_proxy api:8000
  encode gzip
  log { output file /var/log/caddy/api.log }
}

app.<domain> {
  import office_only
  reverse_proxy frontend:3000
  encode gzip
  log { output file /var/log/caddy/app.log }
}
```

`COMPANY_EGRESS_CIDR` is the variable Codex must obtain from the user before this phase ships.

DNS: two A records pointing at the Oracle reserved public IP. Caddy auto-issues Let's Encrypt certs.

### 5.5 — Phase B.5 · Observability, backups, runbook (½ day)

- **Sentry** SDKs in API (`sentry_sdk[fastapi]`) and frontend (`@sentry/nextjs`). Free tier (~5k events/mo).
- **Caddy access logs** rotate daily via `logrotate`.
- **Postgres backups**: cron on the VM, `pg_dump -Fc | gzip` to a separate MinIO bucket `bt-backups`, 30-day retention via MinIO lifecycle. Restore runbook in `docs/ops/restore.md`.
- **Uptime check**: UptimeRobot free pinging `/health` every 5 min, email on 2 consecutive failures.
- **Idle-reclaim heartbeat**: a tiny systemd timer on the VM that GETs `/health` every 10 minutes from `localhost`. Generates enough internal traffic that the VM never hits Oracle's idle threshold.

---

## 6. Critical files reference

| Workstream | Sub-phase | File | Role |
|---|---|---|---|
| A | A.1.a | `core/quant_core/signal_engine/`, `services/api/app/models.py:769-983` | Audit; insert findings into §4.1.a-finding |
| A | A.1.b | `core/quant_core/research/oos_index.py` (NEW) | OOS date-set construction |
| A | A.1.b | `core/tests/test_oos_index.py` (NEW) | OOS date-set tests |
| A | A.1.c | `core/quant_core/research/score_history.py:253` | Add `oos_dates`, `recent_window`, `max_lookback_years` params |
| A | A.1.c | `core/tests/test_bucketed_forward_returns_oos.py` (NEW) | OOS-aware tests |
| A | A.1.d | `core/quant_core/signal_engine/domain.py` | `HORIZON_PARAM_CAP`, `cap_param_grid` |
| A | A.1.d | `core/tests/test_horizon_param_cap.py` (NEW) | Cap behavior tests |
| A | A.1.c-NEW | `core/quant_core/significance.py` | `monte_carlo_label_shuffle_test` |
| A | A.2.a | `core/quant_core/research/edge.py` (NEW) | Pure Edge metrics module |
| A | A.2.b | `services/api/app/routers/analytics.py` | New `/analytics/edge` endpoint + warm endpoint |
| A | A.2.b | `services/api/app/schemas/edge.py` (NEW) | Pydantic models |
| A | A.2.b | `services/worker/tasks/refresh_edge_cache.py` (NEW) | Cache warmer |
| A | A.2.c | `services/api/app/routers/runs.py::list_strategy_leaderboard` | Attach `edge` per row |
| A | A.2.d | `core/tests/test_edge_metrics.py` (NEW), `services/api/tests/test_edge_endpoint.py` (NEW) | Tests |
| A | A.3 | `frontend/app/v1/page.tsx`, `frontend/components/ui/{signal-badge,eyebrow,segmented}.tsx`, `frontend/components/dashboard/{setup-step,kpi-tile,edge-tile,edge-panel}.tsx`, `frontend/lib/api.ts` | Restyle + Edge UI |
| B | B.1 | `frontend/Dockerfile`, `frontend/next.config.js`, `infra/docker-compose.gcp.yml` | Frontend in Docker |
| B | B.2 | `frontend/auth/{index.ts,schema.ts,db.ts,migrate.ts}` (NEW), `frontend/middleware.ts`, `frontend/app/{login,signup,account}/page.tsx` (NEW), `frontend/app/api/[...path]/route.ts`, `frontend/app/api/auth/[...nextauth]/route.ts` (NEW), `services/api/app/auth.py` | Auth.js + JWT verify |
| B | B.3 | `.github/workflows/build-images.yml`, `.github/workflows/deploy-vm.yml`, `.github/workflows/ci.yml` (NEW) | CI/CD |
| B | B.4 | `infra/Caddyfile.gcp` | IP allowlist + DNS |
| B | B.5 | `services/api/app/main.py` (Sentry init), `frontend/sentry.{client,server,edge}.config.ts`, `docs/ops/restore.md` (NEW) | Observability + backups |

---

## 7. Open items / blocking inputs

Codex must obtain answers to these before the corresponding phase ships:

1. **§4.1.a-finding** — does `signal_score_history` already carry an OOS marker? Resolve before A.1.b.
2. **§4.1.a-finding** — what is the actual JSON shape of `WfoSignalSummary.folds_json[*]`? Resolve before A.1.b.
3. **§4.2.c** — confirm `services/api/app/routers/runs.py::list_strategy_leaderboard` is the dashboard payload assembler; if not, name the actual endpoint.
4. **§1.1** — company egress CIDR for Caddy IP allowlist (or chosen alternative: Tailscale, on-prem). Resolve before B.4.
5. **Domain name** for `api.<domain>` and `app.<domain>`. Resolve before B.4.
6. **Maintainer VPN / break-glass path** — how does the maintainer reach the box from home? (Tailscale on a personal device is the simplest.)
7. **SMTP relay availability** — if the company has one, switch Auth.js from Credentials to magic-link (cleaner UX). Otherwise stay with Credentials.

## 8. Sequencing recommendation

Realistic 5–7 working day plan:

| Day | Workstream A (backend/edge) | Workstream B (deploy) |
|---|---|---|
| 1 | A.1.a audit, A.1.b oos_index | B.1 frontend Docker spec |
| 2 | A.1.c bucketed_forward_returns refactor + tests | B.2.a/b Auth.js scaffolding |
| 3 | A.1.d param caps, A.1.c-NEW label shuffle test | B.2.c FastAPI JWT verify |
| 4 | A.2.a/b edge module + endpoint + caching | B.3 CI/CD workflows |
| 5 | A.2.c/d leaderboard integration + tests | B.4 Caddy + DNS (after egress CIDR known) |
| 6 | A.3 dashboard restyle + Edge UI | B.5 backups + Sentry |
| 7 | A.4 verification + demo dry-run | smoke test in prod |

Workstream B is mostly independent of A; both can run in parallel if Codex has bandwidth.

## 9. Demo dry-run checklist

Before showing the supervisor:
- 2–3 symbols where badge fires green; rehearse: row → drill-down → 4 gates → expectancy decomposition → histogram → label-shuffle pvalue → cross-link.
- 1 symbol with badge=false; show *which* gate fails and why.
- 1 symbol with `bucket=hold`; show the dim "Pas de signal aujourd'hui" state.
- 1 symbol with `n<30`; show the grey "Insuffisant" state.
- One-line answers ready:
  - *"Multiple-testing correction?"* → "Deferred. Stricter `p < 0.01` partially mitigates. Proper FDR in next iteration."
  - *"Bucket selection bias?"* → "We measure the bucket the signal selected today, not the best historical bucket. No selection."
  - *"Look-ahead?"* → "All ER/HR/PF computed on OOS forward returns only. WFO test windows + signal-engine OOS reconstruction. Audit + tests in `test_oos_index.py` and `test_bucketed_forward_returns_oos.py`."
  - *"What's your null hypothesis?"* → "Two complementary tests. Centered-return bootstrap (`monte_carlo_luck_test`) tests if the bucket's mean is non-zero. Label-shuffle test (`monte_carlo_label_shuffle_test`) tests if bucket assignment is informative."
  - *"Regime stability?"* → "Stats over the last 30–60 OOS observations, ≤ 3-year ceiling. Designed for current regime. Not robust to a regime break — known limitation."

---

## 10. Out-of-scope (post-demo, in priority order)

1. Multi-tenancy schema migration (W B.2.d) — needed before opening signup beyond the seed admin.
2. Data engineering hardening: CASCADE on FKs, run retention with `is_pinned`, pg_dump cron, MinIO orphan cleanup, missing indexes.
3. Remaining UI ports from the Claude design: Data, Glossary, Signals, Strategy, Backtest, Analytics. Header refactor + font swap to Roboto/Roboto Mono.
4. Multiple-hypothesis correction (BH-FDR) on Edge p-values across the dashboard.
5. Regime-windowed Edge view (rolling 12 / 24 month).
6. Determinism layer: pinned RNG seeds in `run.spec_json`, code-SHA stamping on results, library-version capture, immutable data snapshots.
7. Audit log: append-only "who viewed/modified what when".
8. Corporate-actions handling (splits, dividends, suspensions, holiday calendars) in the equity data layer.
