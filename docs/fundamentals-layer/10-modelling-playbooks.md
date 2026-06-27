# Modelling playbooks

Opinionated step-by-step checklists for tasks an analyst will repeatedly hit when using this engine. Each playbook is self-contained and references actual files / endpoints.

---

## Playbook 1 — I just uploaded a new workbook. What to check before trusting the scores

**Goal:** validate that the import landed cleanly before showing it to anyone.

1. **Check `FundamentalImport.status`** via `GET /fundamentals/imports/latest`. Must be `"succeeded"`. If `"failed"`, read `error_message`.
2. **Check `quality_issue_count`** on the same row. Anything above ~5 per symbol deserves a look at the QC tab.
3. **Open the Quality tab** of the `/fundamentals` page for 3 symbols you trust most (e.g. the largest by market cap). Confirm no `severity="error"` issues. `severity="warn"` is normal for FY gaps.
4. **Pillar coverage check** — for each of those 3 symbols, look at `snapshot.scores.component_count`. Expected: 6. If lower, some pillars couldn't be computed.
5. **Confirm cohort size** — if you uploaded fewer than 5 companies, percentile ranks are unreliable. Either upload a bigger universe or interpret scores only relative to each other.
6. **Spot-check a valuation** — pick the symbol you know best. Open the Valuation tab. Does the ensemble fair value match your gut within 25%? If not, dig.
7. **Compare to the previous import** — if you have one. `latest_imports_by_symbol` resolves the latest snapshot per symbol across supported data sources.

**Red flags:**
- Null pillar scores (cohort might be too small for the minimum 3-symbol scoring rule).
- Ensemble confidence < 0.5 (valuation is noise).
- > 30 quality issues for a single symbol (workbook layout drifted).

---

## Playbook 2 — Fair value range is very wide (>50% of base). How to diagnose

**Goal:** understand whether the wide band reflects real model disagreement or a single bad input.

1. **Open `GET /fundamentals/stocks/{symbol}/valuation`** to see the per-model breakdown.
2. **Sort models by `|fair_value - ensemble.fair_base|`** descending. The top 2 are your "swing" models.
3. **For each swing model, open `inputs` JSON**. Look specifically for:
   - DCF models: is `growth` near `growth_cap` (0.08)? If yes, the model is hitting the cap and overstating fair value.
   - Multiples models: is `peer_stats.{metric}.scope = "market"`? If yes, sector peers were too few (<3) and the fallback is using a heterogeneous cohort.
   - DDM: is `dividend_per_share` derived from `Dividend_Yield` or from `Dividendes / shares`? Yield-derived can be stale.
4. **Read `warnings`** on each swing model. Common smoking guns: `missing_positive_fcf`, `using_stable_payout_assumption`, `cost_of_equity_not_above_terminal_growth`.
5. **If `relative_multiples` is the outlier:** check the peer cohort. The sector classification on `stock_master.sector` may be wrong, dragging in unrelated firms.
6. **If `residual_income` is the outlier:** the ROE-COE spread is exaggerating fair value (no fade — see [V3](12-known-issues-and-limitations.md#-v3)). Treat with caution until V3 is fixed.
7. **If `justified_multiples` and `residual_income` disagree:** both depend on COE. Try overriding `cost_of_equity` via `PUT /fundamentals/stocks/{symbol}/assumptions/base` (e.g. nudge from 10.5% to 11.5%) and re-fetch. If both flip simultaneously, COE is the lever.

**What "wide" means:**
- `(fair_high - fair_low) / fair_base < 0.20` — narrow consensus, trust the number.
- `0.20-0.50` — typical for a firm with mixed signals; the band IS informative.
- `> 0.50` — true disagreement or input issues; investigate.

---

## Playbook 3 — Confidence is low. Which warnings matter most

**Goal:** triage warnings by severity for valuation reliability.

**High-priority warnings (fix these first):**

| Warning | Why it matters | Where to fix |
|---|---|---|
| `missing_positive_fcf` | DCFs can't run; ensemble lost ~40% of weight | Workbook FCF columns; check `Free_Cash_Flow` series |
| `missing_shares` | Per-share fair value impossible | `Shares_Outstanding` in snapshot metrics |
| `missing_net_debt_bridge` | FCFF DCF understates equity (see [V5](12-known-issues-and-limitations.md#-v5)) | Add `NetDebt` or `Total_Debt + Cash` to workbook |
| `wacc_not_above_terminal_growth` | DCF degenerate; model returns None | Override assumptions, lower terminal_growth or raise WACC |
| `currency_mismatch` | Cross-currency arithmetic is blocked | Use assumptions calibrated to the snapshot currency, or wait for an FX conversion layer |

**Medium-priority warnings:**

| Warning | Meaning |
|---|---|
| `using_stable_payout_assumption` | Payout was invalid/missing; engine substituted default |
| `fcfe_proxy_from_free_cash_flow` | FCFE built from FCF (see [V1](12-known-issues-and-limitations.md#-v1)) |
| `no_usable_peer_multiple` | Relative multiples couldn't find enough peers |
| `no_usable_justified_multiple` | Justified P/B and P/E both failed (likely ROE missing) |

**Low-priority (often ignorable):**

| Warning | Meaning |
|---|---|
| `model_not_eligible` | Expected — model gate fired (e.g. DCF on a bank) |
| `missing_fcf_yield_for_reverse_dcf` | Reverse DCF is diagnostic anyway, doesn't affect ensemble |

---

## Playbook 4 — Justified multiples disagrees with relative multiples by 30%. Which to trust

**Goal:** the two models are conceptually different — pick the right one for the firm.

**Use justified multiples when:**
- The firm has stable ROE and payout policy.
- You have confidence in `cost_of_equity` (i.e. a sensible beta or override).
- You believe the firm's fundamentals justify its trading level (top-down).
- Examples: mature financial sector firms, regulated utilities.

**Use relative multiples when:**
- The peer cohort is well-defined (≥3 sector peers with the same metrics present).
- The market is pricing the sector consistently.
- You're benchmarking, not asking "is the whole sector overvalued?".
- Examples: industrial firms in a competitive market, when sector consensus is informative.

**Conflict resolution rule of thumb:**
- If both are confidence="high" and disagree by >30%, the FIRM is genuinely mispriced vs peers OR the peer set is heterogeneous. Inspect `peer_stats[metric].count` — should be ≥3 per metric.
- If justified gives MAD 300 and relative gives MAD 200 → market is pricing this firm cheaper than its fundamentals justify. **Either** a buying opportunity **or** the market knows something the model doesn't (regulatory risk, governance, etc.). Read the news.
- If justified gives MAD 200 and relative gives MAD 300 → market is pricing this firm richer than its fundamentals justify. **Either** a sell **or** the firm has hidden growth optionality the model can't see.

---

## Playbook 5 — Reported ROE doesn't match DuPont implied ROE. What does the gap mean

**Goal:** the DuPont bridge gap (`reported_roe - net_margin × asset_turnover × equity_multiplier`) is a data-quality probe. Use it.

**Where to find it:**
```
GET /fundamentals/stocks/{symbol}
→ detail.diagnostics.dupont.roe_bridge_gap
→ detail.diagnostics.dupont.score   (100 − min(100, gap × 500))
```

**Interpretation table:**

| Gap (absolute) | DuPont score | Interpretation |
|---|---|---|
| < 0.005 | 97-100 | Clean — components reconcile to reported |
| 0.005-0.02 | 90-97 | Minor differences, likely rounding or definitional |
| 0.02-0.05 | 75-90 | Worth a look — possibly different period averaging |
| 0.05-0.10 | 50-75 | Probably an input error; check `Asset_Turnover`, `Equity_Multiplier` |
| > 0.10 | < 50 | Significant inconsistency — don't trust the snapshot for analytical use |

**Common causes when gap > 0.05:**
- `ROE` from workbook uses different equity period (beginning vs average) than DuPont denominator.
- `Equity_Multiplier` was computed from a different balance sheet snapshot.
- Workbook layout drift — `Asset_Turnover` is being read from the wrong cell.

---

## Playbook 6 — How to adjust assumptions for a Moroccan bank specifically

**Goal:** override the global defaults for a sector or single symbol via `FundamentalAssumptionSet`.

**Why banks differ from the defaults:**
- COE for Moroccan banks should reflect beta (typically 0.8-1.1) and any leverage risk premium. The default 10.5% assumes β=1; well-capitalized banks may deserve lower.
- WACC = COE for banks by methodological convention (debt = cheap funding source for banks, not capital structure choice).
- Terminal growth should match long-term banking sector ROE convergence, not GDP.

**Workflow:**

1. Open the Assumptions tab on `/fundamentals/stocks/{SYMBOL}` for one bank you trust.
2. Edit the JSON. Suggested overrides for a Moroccan bank:
   ```json
   {
     "scope_type": "sector",
     "scope_key": "Banques",
     "scenario": "base",
     "assumptions_json": {
       "cost_of_equity": 0.095,
       "wacc": 0.095,
       "terminal_growth": 0.025,
       "fade_years": 7,
       "growth_cap": 0.06,
       "stable_payout_ratio": 0.55
     }
   }
   ```
3. Submit via `PUT /fundamentals/stocks/{symbol}/assumptions/base`. The endpoint re-runs the valuation pipeline.
4. Verify changes on the Valuation tab. Fair values for **all** banks in the same `sector_key` should shift.
5. If you want to override one specific bank (not the whole sector), use `scope_type: "symbol", scope_key: "{SYMBOL}"`. Symbol-scoped overrides take precedence over sector-scoped.

**The override hierarchy** (`active_assumptions_for` in `services/api/app/services/fundamentals.py`):
- `scope_type="symbol"` matching `scope_key=symbol` → wins.
- Else `scope_type="sector"` matching `scope_key=sector` → wins.
- Else `scope_type="global"` with `scope_key="GLOBAL"` → fallback.
- Else `DEFAULT_ASSUMPTIONS` from `valuation.py:14`.

---

## Playbook 7 — When to use sector vs market scope in relative_multiples

**Goal:** understand when peer comparison falls back to market.

**Default:** relative multiples uses sector peers. If `len(sector_peers) >= peer_min_count` (default 3), `scope = "sector"`. Else `scope = "market"`.

**You see `scope = "market"` for a metric. What now?**

- Look at how many symbols in your universe carry that sector classification. Is the sector under-represented?
- Often the issue is sector taxonomy mismatch — e.g. "Industries" might cover too many heterogeneous firms, or "Banques" might be split into "Banques de détail" and "Banques d'affaires".
- Workarounds:
  - Increase the import cohort to include more sector peers.
  - Lower `peer_min_count` temporarily via assumption-set override (not recommended; defeats the safeguard).
  - Manually pick relative-multiples comparables if the engine's choice is wrong.

**When to trust `scope = "market"`:**
- For firms with no real peer set (conglomerates, unique business models). The market median is a starting point but not a confident anchor.
- The model's confidence will already reflect this (`"medium"` not `"high"`) — don't double-discount.

---

## Playbook 8 — How to interpret an unusually low "overall" score

**Goal:** decide whether a low overall means "bad fundamentals" or "bad data".

1. Check `snapshot.scores.component_count` and `snapshot.scores.overall_coverage_pct`. If weighted coverage is below 50%, `overall` is intentionally null.
2. Check per-pillar scores. If 5 of 6 pillars are >50 and one is 0, the overall is dragged by an outlier.
3. Trace the outlier pillar:
   - **Value low** → check `PER`, `Price_to_Book`, `EV_to_EBITDA`. Are they extreme? Sometimes a multi-year low price drives PE to extreme low (looks cheap) — but is actually a value trap.
   - **Quality low** → check `quality_components`. Is raw percentile, accounting discipline, or accrual quality the drag?
   - **Risk low** → check leverage ratios. A new high in Debt_to_Equity?
   - **Growth low** → can be cyclical trough. Cross-check with 3y-trailing growth ([S9](12-known-issues-and-limitations.md#-s9)).
4. Read the diagnostics tab. The DuPont bridge gap and accrual quality are leading indicators of "score is real" vs "score is noise".

---

## Playbook 9 — When to NOT use the fundamental engine

**Goal:** recognize the limits.

- **Distressed firms** — DCF inputs assume going concern; multiples assume stable peers. Distressed firms fail both. Use scenario analysis with bear-case explicit, treat outputs skeptically.
- **Early-stage / high-burn-rate firms** — negative FCF, no payout, often no peer cohort. The engine excludes these correctly (low usable_model_count) but doesn't add value here.
- **Holding companies / conglomerates** — sector classification is fuzzy. Consider running each segment separately if data permits.
- **Real estate / REITs** — book value and FFO matter; the engine doesn't compute FFO. Treat outputs as a starting point only.
- **One-time corporate actions** — IPO, large M&A, spin-off — break the historical comparability the engine assumes. Wait for 2 years of post-event data.
- **Cross-currency comparisons** — currency mismatches are blocked; FX conversion is still out of scope.

## See also

- [11-prompts-for-claude.md](11-prompts-for-claude.md) — ready-to-paste prompts that automate these playbooks.
- [12-known-issues-and-limitations.md](12-known-issues-and-limitations.md) — the issues these playbooks work around.
- [08-assumptions-and-defaults.md](08-assumptions-and-defaults.md) — what each tunable parameter does.
