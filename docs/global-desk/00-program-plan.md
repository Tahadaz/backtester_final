# Global Desk Program — Cross-Asset Signals for a Traded Book

**Date:** 2026-08-17
**Owner:** Taha · **Status:** spine drafted, awaiting approval before briefs are written
**Purpose change:** research artifact → **signals intended for execution on a desk book**

**Supersedes:**
- `docs/plans/multi-market-port.md` §"Non-goals" — the "no alpha claims outside Morocco, the Moroccan edge IS the moat" position is retired. Its port-readiness *findings* (§"Port-readiness findings") remain accurate and are reused.
- `docs/cross-asset-product/00-program-plan.md` §8 exclusions **D4** (commodities on fixtures only) and the eurobond entry ("data-blocked without Bloomberg exports"). Both were data-constrained decisions. The constraint is lifting.

**Reuses unchanged:** that program's D5 (one run ledger), D6 (route parameterization), D7 (one engine, N return kinds), §4 token guardrails, §5 reuse table, and **§6 financial invariants — which become stricter here, not looser.**

---

## 1. What changed, and why this is a small program rather than a large one

Three assets already exist and are load-bearing. This program is mostly connective tissue between them.

**A. The statistical harness is built and market-agnostic.** IC with BH-FDR, walk-forward (`core/quant_core/wfo/engine.py:43`), deflated Sharpe (`research/stats/robustness.py:94`), stationary bootstrap CI (`:108`), MC and shuffled-trade nulls, after-cost Sharpe, and a pre-registration habit carried through the 2026-07 studies. `signal_engine/*` and `wfo/*` contain zero Morocco references. **This is the actual moat — not any individual signal.**

**B. The cross-asset engine is built and correct.** `core/quant_core/cross_asset/` has `Instrument`/`FxPair`/`FuturesContract` with real roll rules (`first_notice`, `volume_crossover`, `n_days_before_expiry:N`), plus `time_series_momentum`, `carry_signal`, `vol_scale` — every one applying `.shift(lag)` with `lag>=1`, so no lookahead is baked in. One engine, three return kinds (`fx_excess`, `futures_excess`, `bond_duration`). Adding an asset class is a `ReturnSpec.kind` value, not a new stack.

**C. The Bloomberg bridge is built.** `tools/bloomberg_bridge/bridge.py`, `services/api/app/routers/bloomberg_bridge.py` (1354 lines), `bloomberg_connector.py`, three migrations, and the `bloomberg_ingest_batch` / `bloomberg_series` / `bloomberg_bridge_status` tables (`services/api/app/models.py:1114,1146`). Enrollment tokens, per-terminal hashed keys, outbound-HTTPS-only listener, app-queued preflight/discovery/backfill/refresh jobs, offline spooling, entitlement-aware discovery. It is architected exactly right for a supervised bank terminal.

**What is missing is narrow:** the bridge's universe is MASI (`FIELD_VISIT_RUNBOOK.md` steps 7-9). There is no global security master, no eurobond vertical, no real per-contract commodity data, and — because this was never a trading tool before — **no book**.

---

## 2. Decisions taken this session

| # | Decision | Rationale |
|---|---|---|
| **G1** | **Daily bars, signals refreshed daily, positions rebalanced weekly** with a no-trade band. Not intraday. | Where the documented premia actually live: TSMOM (Moskowitz-Ooi-Pedersen) and carry (Koijen et al.) are monthly-to-weekly phenomena. At weekly turnover with vol targeting, costs are a manageable fraction of gross alpha in liquid FX/futures; at daily they begin to dominate. Bloomberg daily history is reliable and cheap in entitlement terms — the runbook itself flags hourly/minute availability as limited (step 10). Intraday is a different infrastructure commitment and would invalidate the existing harness's sample-size assumptions. |
| **G2** | **Signals daily / trades weekly**, with a rebalance band so small drifts don't trade. | Standard CTA practice. Cuts turnover materially versus rebalancing to target every period, at negligible tracking cost. Also produces a *weekly rebalance sheet*, which is a artifact a person can actually review before sending orders. |
| **G3** | **`/signals` becomes the single research surface**, with a two-level selector: **Scope** (Morocco Equities \| Global Cross-Asset) then **Mode**. `/cross-asset-research` is absorbed and redirected. `/offshore-lab` (stateless bond calculator) stays separate per the existing D6. | "Well organized" means *fewer* top-level routes, not more. This nets −1 route while adding four asset classes. Consistent with the existing guardrail #7: adding an asset class must mean adding a union-type value, not a folder. |
| **G4** | **A new `Book` surface** — current positions, target weights, risk contribution, and the weekly rebalance sheet. | This is the one genuinely new *concept*, and it is what separates a research app from a trading tool. Everything else in this program feeds it. |
| **G5** | **Bloomberg data is tagged and isolatable at the storage layer**; every series carries its source. Free sources remain the fallback path for anything that leaves the desk machine. | Terminal data is licensed to the user on that Terminal. The existing bridge already models this correctly (per-terminal keys, batch provenance, sha256) — G5 just makes the *downstream* store honour it, so a run can always answer "was this Bloomberg-derived?" |
| **G6** | **Eurobond vertical is in scope**, expressed as duration + credit-spread risk with an RV layer. | Directly unblocked by Bloomberg. This is the user's actual desk coverage and the highest-value addition. |
| **G7** | **Commodities move from fixtures to real per-contract chains.** | D4 chose fixtures because free continuous tickers are not tradable-faithful. Bloomberg gives genuine per-contract history, so the roll accounting the engine already implements becomes real rather than illustrative. |

---

## 3. What this system is honestly for

Stated plainly, because the purpose changed to real money and expectations should be set before code is written.

**This is a machine for harvesting documented risk premia with honest costs, and for refusing to fool itself.** Cross-asset trend, carry, curve/roll, and value are among the most replicated results in empirical finance. They are also crowded, capacity-constrained, and prone to multi-year drawdowns. A well-built version of this earns a respectable risk-adjusted return and diversifies a discretionary book. It does not find secret alpha, and any result here that looks like secret alpha is far more likely a bug, a lookahead, or a survivorship artifact — which is precisely what the harness in §1A exists to catch.

The corollary matters for sequencing: **the validation layer is not the last phase, it is the gate on every phase.**

---

## 4. Governance requirements (design inputs, not paperwork)

Trading a firm's book with a self-built systematic model imposes real constraints, and they change the architecture rather than merely wrapping it:

1. **Reproducibility is mandatory, not nice-to-have.** Every position the system proposes must be reconstructible from `(spec_hash, dataset_hash, git_commit, seed)`. The `Run` ledger already carries all four (`models.py:106`).
2. **No unexplainable positions.** Every proposed trade must decompose into named signal contributions. If you cannot say *why* in one sentence to a senior, the system has failed regardless of Sharpe. This rules out opaque ML as a first-line signal generator.
3. **Risk limits are inputs, not outputs.** Per-instrument, per-asset-class, and portfolio vol/exposure limits are configuration the desk sets, enforced in the sizing layer.
4. **Personal-account-dealing rules are separate from the book.** If any output is ever used personally, pre-clearance/restricted-list/holding-period rules apply and typically prohibit exactly the instruments the desk covers. Worth confirming early so the boundary stays clean.
5. **Data-use approval follows the path already established** — the bridge's supervisor/IT route in `FIELD_VISIT_RUNBOOK.md` is the correct precedent; extending it to a global universe should be flagged, not assumed.

---

## 5. Workstreams in dependency order

```
  W1  Global security master + Bloomberg universe expansion   ← unblocks everything
       │
       ├── W2  Data quality & PIT discipline layer
       │        │
       │   ┌────┼─────────────┬──────────────────┐
       │   ▼    ▼             ▼                  ▼
       │  W3   W4            W5                 W6
       │  FX   Rates &       Commodities        Global
       │       Credit        (real chains)      Equities
       │       (eurobonds)
       │        │
       └────────┴──────────► W7  Multi-asset portfolio construction
                                  │
                                  ├── W8  Validation gate (pre-registered)
                                  │
                                  └── W9  Book surface + weekly rebalance sheet
```

| # | Workstream | Deliverable | Ship gate |
|---|---|---|---|
| **W1** | Global security master | Instrument registry keyed by Bloomberg ticker + free fallback, covering G10 FX, sovereign curves, credit indices, commodity futures roots, equity indices. Bridge discovery jobs generalized off MASI. | Discovery job returns entitlement status for the full global list; every instrument resolves to both a Bloomberg ticker and (where it exists) a free proxy |
| **W2** | Data quality & PIT | Staleness, gap, and outlier detection; source tagging (G5); explicit missing-vs-zero handling; roll-date integrity checks | Corrupted//stale fixtures are *caught*, not silently forward-filled. Invariant §6.3 has teeth |
| **W3** | FX | G10 TSM + carry on Bloomberg spot/forwards, replacing the yfinance+FRED approximation | Live run reconciles against the existing free-data run within documented tolerance |
| **W4** | Rates & credit (**eurobonds**) | Sovereign curve TSM/carry/roll-down; credit spread duration; eurobond RV layer (asset swap, z-spread, curve-relative) | A eurobond RV screen produces ranked candidates with spread decomposition |
| **W5** | Commodities | Real per-contract chains; genuine roll accounting; curve carry from the actual term structure | A commodity run is no longer labelled non-tradable in `warnings` |
| **W6** | Global equities | Index-level and cross-sectional factor exposure, survivorship-bias-free universe | Documented universe construction incl. delisted names |
| **W7** | Portfolio construction | Vol targeting, correlation-aware sizing, risk-parity-style allocation across sleeves, drawdown control, limit enforcement | Portfolio vol lands within tolerance of target out-of-sample |
| **W8** | **Validation gate** | Pre-registered acceptance criteria per sleeve; DSR with honest variant counts; walk-forward OOS; cost sensitivity; capacity analysis | **A sleeve that fails is not shipped to the book.** No exceptions, no post-hoc criteria changes |
| **W9** | Book surface | Positions, target weights, risk contribution, weekly rebalance sheet with per-trade rationale | A person can review the week's proposed trades and understand each one |

**W8 is not a phase you reach — it is the gate each of W3-W6 must pass before W7 will accept its sleeve.**

---

## 6. Strengthened invariants

The seven in `docs/cross-asset-product/00-program-plan.md` §6 carry over verbatim. Real money adds four:

8. **Costs are modelled pessimistically.** Bid-ask + slippage + financing/roll cost, sized to realistic desk fills, not mid-price fills. Where a cost is unknown, use the conservative end and label it.
9. **Capacity is stated.** Every sleeve declares the AUM at which its edge degrades. A strategy without a capacity number is not validated.
10. **Live-vs-backtest tracking from day one.** Once a sleeve trades, realized P&L is compared against the backtest's expectation continuously. Divergence beyond a pre-set band triggers review — this is the single most effective defence against a subtly broken backtest.
11. **Regime and drawdown disclosure.** Every sleeve reports its worst historical drawdown, its length, and the macro conditions in which it failed. Trend following's 2011-2013 and carry's crisis behaviour are features of the premia, not anomalies to hide.

---

## 7. Deliberately not built

- **Intraday / execution algos.** G1. Different infrastructure, different data, no evidence it is needed at weekly turnover.
- **Opaque ML signal generation.** Governance requirement §4.2. ML may be used for *diagnostics*, never as an unexplainable position source.
- **Options / vol strategies.** Real premia exist here, but they require an options data and greeks layer the app has none of. Candidate for a later program, not this one.
- **Anything that modifies the Moroccan equity/fundamentals pipeline.** It is validated and scheduler-wired. Global work is additive; MASI becomes one scope among several and its code path is untouched.
- **Single-name credit default modelling.** Out of scope; the credit sleeve is index- and curve-level plus eurobond RV.

---

## 8. Round-2 answers, resolved into decisions

| # | Decision | Consequence |
|---|---|---|
| **G8** | **No instrument-access constraint.** International offshore cross-asset desk — anything is executable. | Universe selection is therefore driven by **liquidity, cost and data quality**, not by access. This is a harder discipline than an access constraint, because nothing external stops us from including an instrument we cannot honestly model. W1 must justify every inclusion on liquidity/cost grounds and cap the starting universe at ~40-60 instruments. |
| **G9** | **Bloomberg entitlements are unknown. Nothing may assume them.** Every sleeve ships with a working free-data path; Bloomberg is a documented *upgrade*, never a dependency. | Architecturally this is the right constraint anyway — it keeps the licensing boundary (G5) clean, keeps the app runnable off the desk machine, and means an entitlement gap degrades one sleeve's data quality rather than breaking the system. W1's first deliverable becomes an **entitlement discovery report**: point the existing discovery job at the global list and let it answer empirically. Scope W4's credit depth *after* that report, not before. |
| **G10** | **Risk budget is deferred and parameterized. Sleeves are ranked by risk instead.** Target vol, drawdown tolerance and limits are configuration with documented defaults, not hardcoded assumptions. | W7/W8 output a **ranked sleeve table** — risk-adjusted quality alongside realized vol, worst drawdown and length, capacity, and correlation to the other sleeves — so the budget decision is made from evidence later rather than guessed now. Default starting point for illustration only: 10% annualized portfolio vol. |
| **G11** | **History: maximum available, but regime-pertinent, with the boundaries stated.** | Longer is not automatically better. Constraints to document per instrument rather than paper over: EUR is synthetic pre-1999; credit indices (CDX/iTraxx) only exist from ~2004; several commodity contracts have materially different liquidity pre-2000. The sample **must** include at least one full crisis (2008) and the 2022 rates shock — a trend/carry book's behaviour in those episodes is the entire risk story, and a sample that excludes them is not a validation. |

## 9. Implementation

**Claude implements, in-session** (user instruction, 2026-08-17). This overrides the standing "Sonnet implements / Codex via `docs/ai` briefs" convention for this program. Briefs stay in `docs/global-desk/` as specs and are written one workstream ahead of the build.

### Progress

| # | Workstream | Status |
|---|---|---|
| W1 | Global security master | **Built 2026-08-17.** 47 instruments; entitlement report §6 is a generated skeleton **awaiting a terminal run**. |
| — | **TSMOM vertical slice** | **Built + run 2026-08-17.** Pre-registered study (`02-tsmom-preregistration.md`), 39 instruments on free data, 2000-2026. **Verdict: PROMISING, NOT DEPLOYABLE (7/8 gates).** Net Sharpe 0.699, maxDD −30.4%, 6.5yr longest drawdown. Report: `research-out/global-desk-tsmom/2026-08-17/report.md`. |
| W2-W9 | — | Not started. Partially superseded: the vertical slice already built calendar alignment + data-quality disclosure (part of W2). |

Full suite after all changes: **2343 passed, 5 skipped, 4 xfailed.**

### Bugs found by the vertical slice

Both would have invalidated any result produced before them, and one is repo-wide:

1. **Calendar misalignment** silently zeroed 30 of 39 instruments (union index + `min_periods=252`) while still reporting a Sharpe. Fixed; the runner now aborts on dead instruments.
2. **`deflated_sharpe_ratio` returned 0.0 for every input** — a units mismatch between the dimensionless Harvey-Liu-Zhu term and per-period Sharpes. **Any past DSR reported anywhere in this repo was meaningless**, including the cross-asset `validation.py` path. Fixed in `core/quant_core/research/stats/robustness.py`.
3. `price_returns` produced −306% across WTI's negative 2020 settlement. Fixed.

### The one thing that cannot be done from here

§6 of W1 — the entitlement discovery report — requires a Bloomberg terminal. The job is queued from the app UI (**Data → Bloomberg**, `Universe: global_all`, discovery-only) and its results fill the skeleton at `docs/global-desk/reports/entitlement-discovery.md`. Until that runs, **W4's credit depth and W5's real-chain commodities are unscoped**, and every registry contract multiplier remains unverified for live sizing. Nothing downstream should assume a result here.
