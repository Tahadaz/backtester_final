# Indicator Parameter Recalibration — Implementation Plan

## Goal

Recalibrate the per-horizon parameter grids in [core/quant_core/signal_engine/candidates.py](../../core/quant_core/signal_engine/candidates.py) so that for every indicator family, the `short` / `medium` / `long` grids cleanly map to the trade-thesis duration the user wants. Nothing else in the A→G pipeline changes.

## Horizon Definitions (canonical, 1D bars)

| Horizon | Thesis duration | Bar range | Why this bar range |
|---------|------------------|-----------|--------------------|
| `short` | 1 week → 1 month | 5–20 | 5 trading days = 1 calendar week; 20 ≈ 1 calendar month. |
| `medium` | 1 month+ → 3-4 months | 21–80 | 21 ≈ 1 month + 1 day (no overlap with short); 80 ≈ 4 calendar months. |
| `long` | 6 months → 1 year+ | 120–250 | 120 ≈ 6 calendar months; 250 ≈ 1 trading year. |

**The 80–120 zone (4–6 months) is intentionally a gap.** It does not appear in any horizon. This faithfully reflects the user's definitions, which describe `medium` as "1 to 3-4 months" and `long` as "6 months to a year+", with no horizon in between. Any indicator configuration whose effective lookback falls in 80–120 bars is excluded from all three grids.

## Why Period-To-Horizon Mapping Is Not One-Size-Fits-All

For most indicators, the parameter `N` controls a lookback window and the thesis duration is approximately N bars. But four classes break this rule:

1. **Triple-smoothed indicators (TRIX)**: effective lookback ≈ 3 × N. The raw period must be divided by 3 to compensate.
2. **Bounded oscillators (RSI, MFI, Stochastic)**: as N grows, the math averages gains and losses out and the oscillator collapses toward its midpoint. Past N≈50 the indicator loses discrimination. To express a long-horizon thesis, period and *thresholds* must both move (longer period + wider thresholds → fires only on rare structural extremes).
3. **AF-driven indicators (PSAR)**: no period at all. Horizon is encoded by the acceleration factor (low AF = trend lasts long).
4. **Cumulative-flow indicators (OBV, A/D)**: the raw series is path-dependent and has no intrinsic horizon. Horizon comes from the EMA reference applied to the cumulative series — same mapping as EMA on price.

These four exceptions get bespoke ranges; everything else uses a direct lookback mapping.

## Slot-Filling Policy

The existing pipeline expects exactly 30 candidates per `(family, horizon)` pair (`_take_first_n` in [candidates.py](../../core/quant_core/signal_engine/candidates.py)). The new bands sometimes contain fewer than 30 unique integer configurations (e.g., the trend-filter `short` band 5–20 has only 16 integers). The slot-filling policy is:

- **Single-parameter families**: build the integer set across the ideal band. If `|integers| < 30`, widen the upper bound by 1 each iteration until 30 unique values are reached. Document the widened upper bound. The "ideal" band reflects horizon meaning; the "implementation" band is what the contract forces.
- **Multi-parameter families**: take the Cartesian product of the small per-parameter base grids, filter by the ordering constraint (`fast < slow`, etc.), sort canonically, take first 30. Base grids are sized so the post-filter Cartesian has ≥30 entries. If not, widen the slowest parameter's grid by appending one larger value and rebuild.
- **Threshold-extended families** (`rsi`, `mfi`, `adx`): period × threshold-pair Cartesian. Adjusting the number of threshold pairs is a knob to reach 30 without changing the period band.

The widening behavior already exists in the codebase: see [candidates.py:282-289](../../core/quant_core/signal_engine/candidates.py#L282-L289) (`extra_slow` for `ema_cross`) and [candidates.py:450-466](../../core/quant_core/signal_engine/candidates.py#L450-L466) (`extra_p3` for `uo`). Generalize this pattern into a helper.

---

## Per-Indicator Reasoning and Ranges

For each family below: **mechanics** explains what the parameter does and why a given period maps to a given thesis duration; **anchors** lists the canonical defaults that must land inside the new bands (so the recalibration respects established literature); **ranges** gives the ideal band per horizon with endpoint justification.

### 1. SMA — `price_vs_sma`, parameter `window`

**Mechanics.** SMA(N) is the unweighted mean of the last N closes. Each bar contributes 1/N weight; the indicator forgets a bar entirely after N bars. The center of mass of its weight is (N-1)/2 bars in the past — so SMA(20) "represents" what was happening about 10 bars ago on average. A `close > SMA(N)` rule says "the current price exceeds the mean over the last N bars," and empirically the position lasts as long as price stays on that side, which is on the order of N bars. **Period directly equals thesis duration.**

**Anchors.** SMA(20) (Bollinger), SMA(50) (Murphy intermediate trend), SMA(200) (textbook structural trend).

| Horizon | Ideal band | Slot-filled band | Why these endpoints |
|---------|-----------|-------------------|---------------------|
| short | 5–20 (16 ints) | **5–34** | Lower 5 = 1 trading week. Upper 20 = 1 calendar month. Widened to 34 to fill 30 slots; periods 21–34 represent "1+ month" thesis but stay below medium's 4-month ceiling — soft overlap is acceptable here. |
| medium | 21–80 (60 ints) | **21–80**, sub-sampled | Lower 21 = 1 month + 1 day, no overlap with short. Upper 80 ≈ 4 calendar months, the user's "3-4 months" ceiling. SMA(50) lands mid-band as anchor. |
| long | 120–250 (131 ints) | **120–250**, sub-sampled | Lower 120 ≈ 6 calendar months, the user's floor. Upper 250 ≈ 1 trading year, anchored on SMA(200). Past 250 the warmup eats into the 756-bar `long` train window and bars beyond a year contribute negligibly on Moroccan history. |

### 2. EMA — `price_vs_ema`, parameter `window`

**Mechanics.** EMA(N) uses smoothing factor α = 2/(N+1). All historical bars technically contribute, but the **effective memory is ~N bars** and the center of mass is (N-1)/2 — identical horizon meaning to SMA(N). This is why "EMA(20)" and "SMA(20)" are interchangeable as horizon descriptors in technical-analysis literature. **Use the same ranges as SMA.**

**Anchors.** EMA(12) and EMA(26) (MACD legs), EMA(50), EMA(200).

| Horizon | Slot-filled band |
|---------|-------------------|
| short | 5–34 |
| medium | 21–80 |
| long | 120–250 |

### 3. EMA Cross — `ema_cross`, parameters `fast`, `slow`

**Mechanics.** Signal flips when EMA(fast) crosses EMA(slow). The signal is sensitive to changes that move the fast EMA but not the slow one. The thesis duration is dominated by **slow** (the position holds as long as the slow EMA stays on the right side); fast controls the trigger reactivity. The empirically robust ratio is slow ≈ 2–4 × fast: below 2× both legs respond similarly and the cross becomes noisy; above 4× the cross lags badly.

**Anchors.** (5, 20), (12, 26), (20, 50), (50, 200) — Murphy classics.

| Horizon | fast band | slow band | Why |
|---------|-----------|-----------|-----|
| short | 3–10 | 12–25 | Slow ≈ 2–5 weeks → "react to recent momentum shifts." (5, 20) lands at the upper edge. |
| medium | 8–20 | 26–60 | Slow ≈ 1–3 months. (12, 26) at the bottom, (20, 50) at the top. |
| long | 20–50 | 60–200 | Slow ≈ 3+ months. The Golden Cross (50, 200) sits at the upper end. |

**Slot fill.** Per horizon, build small base grids (e.g. short fast={3,4,5,6,7,8,9,10}, slow={12,15,18,20,22,25}), take Cartesian product, filter `fast < slow`, sort by `(slow, fast)`, take first 30. If <30, append one larger slow value.

### 4. Ichimoku — `ichi_cloud`, parameters `tenkan`, `kijun`, `senkou_b`

**Mechanics.** Tenkan = midpoint of last `tenkan` high-low range; Kijun = midpoint of last `kijun` high-low range; Senkou B = midpoint of last `senkou_b` high-low range, shifted forward. Trade rule: `close > cloud AND tenkan > kijun`. The **kijun** is the dominant equilibrium reference and defines the indicator's horizon.

**Anchors.** Hosoda's (1969) original (9, 26, 52). On a 1D bar this is kijun ≈ 1 month, senkou_b ≈ 2 months — squarely a swing-trade horizon.

| Horizon | tenkan | kijun | senkou_b | Why |
|---------|--------|-------|----------|-----|
| short | 5–10 | 12–20 | 22–40 | Kijun = 2-4 weeks → equilibrium reference within 1 month. |
| medium | 9–18 | 22–40 | 44–80 | Hosoda's (9, 26, 52) lives here. Kijun = 1–2 months. |
| long | 18–30 | 40–80 | 90–180 | Kijun = 2–4 months → structural equilibrium. Cloud spans 4–9 months. |

**Constraint** `tenkan < kijun < senkou_b` is mathematically required (otherwise the cloud is degenerate). Cartesian → filter → sort by `(senkou_b, kijun, tenkan)` → first 30.

### 5. PSAR — `psar_trend`, parameters `af_step`, `af_max`

**Mechanics.** PSAR has **no period parameter**. AF starts at `af_step`, increases by `af_step` on each new extreme, and caps at `af_max`. The signal flips when price crosses the SAR. Horizon is encoded by **how willing the SAR is to flip**: low AF = SAR drifts slowly, trends last long; high AF = SAR catches up fast, trends end quickly.

**Anchors.** Wilder (1978): `af_step = 0.02`, `af_max = 0.20`. Wilder explicitly described this as a "swing trader's stop" — i.e., medium horizon by our definitions.

| Horizon | af_step | af_max | Why |
|---------|---------|--------|-----|
| short | 0.025, 0.03, 0.035, 0.04, 0.045, 0.05 | 0.20, 0.25, 0.30, 0.35, 0.40 | Fast acceleration + high cap → SAR closes on price within ~5–15 bars → flip-prone, fits "1 wk – 1 mo" trades. Cartesian = 30. |
| medium | 0.01, 0.015, 0.02, 0.025, 0.03 | 0.15, 0.20, 0.25, 0.30, 0.40, 0.50 | Wilder's (0.02, 0.20) lands here. Trends last ~4–8 weeks. Cartesian = 30. |
| long | 0.005, 0.0075, 0.01, 0.0125, 0.015 | 0.08, 0.10, 0.12, 0.15, 0.18, 0.22 | Slow acceleration + tight cap → SAR stays far from price → trends survive months of pullbacks. Cartesian = 30. |

**This fixes the existing bug** at [candidates.py:135-139](../../core/quant_core/signal_engine/candidates.py#L135-L139) where `_PSAR_PARAMS["short"] == _PSAR_PARAMS["medium"]`.

### 6. MACD — `macd_cross`, parameters `fast`, `slow`, `signal`

**Mechanics.** MACD line = EMA(fast) − EMA(slow). Signal line = EMA(signal) of MACD line. Trade rule: buy when MACD crosses signal. The horizon is dominated by **slow** (the slowest EMA in the chain). The `signal` smoother only filters trigger noise; it does not change horizon meaning.

**Anchors.** Appel (1979): (12, 26, 9), explicitly designed for daily-bar swing trading on equities — i.e., a 1–2 month thesis. Lands in `medium`.

| Horizon | fast | slow | signal | Why |
|---------|------|------|--------|-----|
| short | 5–10 | 12–20 | 5–9 | Slow ≈ 2–4 weeks. (8, 17, 9) is a known short-MACD variant. |
| medium | 10–18 | 22–45 | 7–12 | Appel's (12, 26, 9) sits low in band. Slow = 1–2 months. |
| long | 18–30 | 50–100 | 9–18 | Slow ≈ 3–5 months → genuine slow momentum. EMA(100) − EMA(20) is the upper limit where MACD still produces meaningful crosses; past slow=100 the indicator becomes too rare to evaluate. |

**Constraint** `fast < slow`. Cartesian → filter → sort by `(slow, fast, signal)` → first 30.

### 7. ROC — `roc_zero`, parameter `period`

**Mechanics.** ROC(N) = (close / close[N bars ago] − 1) × 100. Pure N-bar return — no smoothing, no averaging. **The horizon meaning is exactly N bars**, the cleanest direct mapping in the family.

**Anchors.** ROC(12) is the conventional swing-trade momentum (Murphy).

| Horizon | Ideal band | Slot-filled band | Why |
|---------|-----------|-------------------|-----|
| short | 5–20 (16 ints) | **5–34** | Lower 5 = 1-week return. Upper 20 = 1-month return. Widened to 34 to fill 30 slots. |
| medium | 22–60 (39 ints) | **22–80**, sub-sampled | Lower 22 = ~1-month return, no overlap with short. Upper 80 ≈ 4-month return. ROC(60) ≈ 3-month return as anchor. |
| long | 120–250 (131 ints) | **120–250**, sub-sampled | Lower 120 ≈ 6-month return. Upper 250 ≈ 1-year return. |

### 8. TRIX — `trix_zero`, parameter `period`

**Mechanics.** TRIX = rate of change of triple-smoothed EMA. Triple smoothing means **the effective lookback ≈ 3 × N**. This is the trap: TRIX(15) is *not* a 15-bar indicator — its effective memory is ~45 bars. We must divide the raw period band by 3 to get the right effective horizon.

**Anchors.** Hutson (1983): TRIX(15) for daily swing trading → effective 45 bars (~2 months) → `medium`.

| Horizon | period band | Effective lookback | Slot-filled band | Why |
|---------|-------------|---------------------|-------------------|-----|
| short | 2–7 (raw) | 6–21 | **2–31** widened | Effective lookback maps to 1 wk – 1 mo after the 3× factor. Widened upper to fill 30 slots; effective top ~93 bars stays below long's 120 floor. |
| medium | 7–27 (raw) | 21–81 | **7–36** widened | The ideal raw band is 7–27, but that only yields 21 integers. Apply the same single-parameter widening rule to reach 30 candidates; Hutson's TRIX(15) still lands mid-band and the widened top remains below long's 120-bar floor in effective-lookback terms. |
| long | 40–84 (raw) | 120–252 | **40–84**, sub-sampled | Effective lookback 6 mo – 1 yr. Slow momentum confirmation. |

### 9. ADX — `adx_trend`, parameters `period`, `adx_threshold`

**Mechanics.** Wilder (1978) ADX measures trend *strength* via smoothed directional movement, bounded 0–100. Period controls the smoothing; `adx_threshold` (typically 20–25) is the cutoff for "trending market." Like RSI, ADX is bounded so it does not tolerate huge periods well — past N≈50 it becomes too smooth to discriminate.

**Anchors.** Wilder default N=14, threshold 20 or 25.

| Horizon | period | thresholds | Why |
|---------|--------|------------|-----|
| short | 5–14 (10 vals) | 20, 25, 30 | Wilder default at top. Cartesian = 30. |
| medium | 14–30 (10 vals) | 20, 25, 30 | Standard swing-trade trend filter. Cartesian = 30. |
| long | 25–50 (10 vals) | 25, 30, 35 | Slower smoothing → require more confident trends → higher threshold. Cartesian = 30. Past period 50 ADX flatlines. |

**Compromise on long.** Period 25–50 corresponds to effective trend assessments of ~1–2 months, not the literal 6+ month thesis. ADX simply cannot be stretched to 6 months without losing all discriminative power. The justification is: ADX-long acts as a *strength filter for long-thesis trades* (assess whether the market is in a trending regime at all), not as a 6-month signal in isolation.

### 10. TSI — `tsi_zero`, parameters `long_period`, `short_period`

**Mechanics.** Blau (1991) TSI is doubly-smoothed momentum. The `long_period` is the first smoothing pass and dominates the horizon; `short_period` is the second pass that controls trigger noise.

**Anchors.** Blau default (long=25, short=13), aimed at swing trading → `medium`.

| Horizon | long_period | short_period | Why |
|---------|-------------|--------------|-----|
| short | 8–18 | 4–10 | Long ≈ 2–4 weeks → reactive. |
| medium | 20–40 | 10–18 | Blau (25, 13) lives here. |
| long | 45–80 | 15–30 | Slow structural momentum. Long > 80 stops generating signals. Same caveat as ADX — TSI cannot literally span 6 months, but acts as a strength filter for long-thesis trades. |

**Constraint** `long_period > short_period`. Cartesian → filter → first 30.

### 11. RSI — `rsi_level`, parameters `period`, `oversold`, `overbought`

**Mechanics.** Wilder (1978): RSI = 100 − 100/(1+RS) where RS = avg_gain(N)/avg_loss(N). RSI measures the recent balance of up vs down moves over N bars. Wilder chose N=14 to represent "half a market cycle" of two weeks.

**The oscillator caveat (critical).** RSI is fundamentally a short-horizon indicator. As N grows, gains and losses average out and RSI converges toward 50 — past N≈50 "overbought/oversold" loses meaning. **You cannot stretch RSI period the way you stretch SMA period.** To express a longer horizon, the trick is: increase the period AND widen the thresholds, so a long-horizon signal fires only on truly extreme readings that take months to resolve.

**Anchors.** Wilder default N=14. Cardwell variant N=21 for swing trades.

| Horizon | period | thresholds | Why |
|---------|--------|------------|-----|
| short | 5–14 (10 vals) | (30,70), (25,75), (20,80) | Wilder default at top. Cartesian = 30. |
| medium | 14–28 (10 vals) | (25,75), (20,80), (15,85) | Cardwell RSI(21) mid-band. Cartesian = 30. |
| long | 21–50 (10 vals) | (20,80), (15,85), (10,90) | Slower oscillator + extreme thresholds → fires only on rare deeply-extreme readings. Period 50 is the practical ceiling; past that even (10,90) fires too rarely. |

**Same compromise as ADX/TSI.** RSI-long is a *pullback timer for long-thesis positions*, not a 6-month standalone signal. This is acknowledged in the literature — Cardwell uses RSI as a positive-/negative-momentum filter, not as a primary horizon driver.

### 12. Stochastic — `stoch_level`, parameters `k_period`, `d_period`

**Mechanics.** Lane (1984): %K = (close − low(k)) / (high(k) − low(k)) × 100. %D = SMA(d) of %K. The `k_period` is the lookback for the high-low range; `d_period` is just smoothing. Same horizon caveat as RSI — bounded oscillator, cannot be stretched arbitrarily.

| Horizon | k_period | d_period | Why |
|---------|----------|----------|-----|
| short | 5–14 (10 vals) | 3, 5, 7 | Lane's classical (14, 3) at the top. Cartesian = 30. |
| medium | 14–28 (10 vals) | 3, 5, 7 | Slower stretches for swing pullbacks. Cartesian = 30. |
| long | 21–50 (10 vals) | 5, 7, 9 | Long-thesis pullback timing. Heavier d-smoothing reduces noise at longer k. Cartesian = 30. |

### 13. CCI — `cci_level`, parameter `period`

**Mechanics.** Lambert (1980): CCI = (typical_price − SMA(typical_price, N)) / (0.015 × mean_deviation(N)). Designed for commodities cycles. CCI is **unbounded** (~±300) and tolerates longer periods better than RSI because the mean-deviation divisor scales with N — so CCI(100) is still meaningful (deviation from the 100-bar mean in normalized units).

**Anchors.** Lambert default N=20.

| Horizon | Slot-filled band | Why |
|---------|-------------------|-----|
| short | **5–34** | Fast cycle detection, Lambert default at top. Same widening pattern as SMA. |
| medium | **22–80** | Slower cycle detection. |
| long | **120–250** | CCI tolerates longer periods than the bounded oscillators because of its scale-free divisor. 250 cap matches SMA. |

CCI is the **only oscillator-type indicator** that can use the full SMA-class long band (120–250). RSI, MFI, Stochastic cannot.

### 14. MFI — `mfi_level`, parameters `period`, `oversold`, `overbought`

**Mechanics.** Quong & Soudack (1989): MFI is RSI applied to *money flow* (typical_price × volume) instead of raw price changes. Same horizon constraints as RSI — bounded, period 5–50 reasonable.

| Horizon | period | thresholds |
|---------|--------|------------|
| short | 5–14 (10 vals) | (20,80), (15,85), (10,90) |
| medium | 14–28 (10 vals) | (20,80), (15,85), (10,90) |
| long | 21–50 (10 vals) | (20,80), (15,85), (10,90) |

Same logic as RSI: longer period + wider thresholds for long horizon. Same compromise applies (long-MFI is a pullback timer, not a standalone 6-month signal).

### 15. UO — `uo_level`, parameters `period_1`, `period_2`, `period_3`

**Mechanics.** Williams (1985): combines three timeframes via weighted sum. The longest period dominates. Williams default (7, 14, 28) — a 1:2:4 ratio designed to detect agreement across timeframes.

**Convention.** Preserve the ~1:2:4 ratio so the three timeframes span enough range to detect cross-timeframe agreement; otherwise UO degrades into a single oscillator.

| Horizon | period_1 | period_2 | period_3 | Why |
|---------|----------|----------|----------|-----|
| short | 4–8 | 9–14 | 18–28 | Faster Williams variants. |
| medium | 7–14 | 14–28 | 28–56 | Williams default (7, 14, 28) lives here. |
| long | 14–25 | 25–50 | 50–100 | Stretched, ratio preserved. Long is bounded by the same oscillator caveat — UO cannot reach 6 months without losing discrimination. |

**Constraint** `period_1 < period_2 < period_3`.

### 16. OBV — `obv_trend`, parameter `ema_period`

**Mechanics.** Granville (1963): OBV is a running cumulative sum of signed volume. **OBV alone has no horizon** — it is path-dependent on all history. Horizon is encoded by comparing OBV to its own EMA(N): if OBV > EMA(OBV, N), buying pressure has accelerated relative to its N-bar trend.

**Period → horizon mapping.** Identical to EMA on price.

| Horizon | Slot-filled band |
|---------|-------------------|
| short | 5–34 |
| medium | 21–80 |
| long | 120–250 |

### 17. CMF — `cmf_flow`, parameter `period`

**Mechanics.** Chaikin (1986): CMF = sum(money_flow_volume, N) / sum(volume, N), bounded [-1, +1]. Mathematically a bounded oscillator, but more tolerant of longer periods than RSI because it is a sum-of-flows ratio rather than a gain/loss balance.

**Anchors.** Chaikin default N=20–21.

| Horizon | Slot-filled band | Why |
|---------|-------------------|-----|
| short | **5–34** | Reactive flow reading; Chaikin default at top. |
| medium | **22–80** | Swing-scale accumulation/distribution. |
| long | **80–150** widened | Slow flow regime. Caps at 150 not 250 because CMF is bounded; past 150 the indicator becomes too smooth. **Note:** this puts the CMF long band partially inside the 80–120 dead zone, because CMF cannot honestly span 6 months — same compromise as RSI. CMF-long is a flow-regime filter, not a structural signal. |

### 18. AD — `ad_trend`, parameter `ema_period`

**Mechanics.** Williams (1972) Accumulation/Distribution Line is a running cumulative of `((close-low) − (high-close)) / (high-low) × volume`. Like OBV, it is path-dependent and has no intrinsic horizon — horizon comes from the EMA reference applied to the cumulative series. **Same mapping as OBV.**

| Horizon | Slot-filled band |
|---------|-------------------|
| short | 5–34 |
| medium | 21–80 |
| long | 120–250 |

### 19. VWAP — `vwap_dev`, parameters `period`, `threshold_pct`

**Mechanics.** Berkowitz (1988): rolling N-bar VWAP. Signal fires when price deviates by `threshold_pct` from VWAP. The N is the averaging window — same horizon meaning as SMA.

**Threshold scaling.** Long-horizon VWAP deviations are statistically larger (more cumulative drift), so the threshold must widen with horizon to maintain meaningful signal cadence.

| Horizon | period (10 vals) | threshold_pct | Why |
|---------|------------------|---------------|-----|
| short | 5–20 | 0.5, 1.0, 2.0 | Intraday-style deviation. Cartesian = 30. |
| medium | 22–80 (sub-sampled) | 0.5, 1.0, 2.0 | Swing-scale deviation. Cartesian = 30. |
| long | 120–250 (sub-sampled) | 1.0, 2.0, 3.0 | Wider thresholds for structural divergences. Cartesian = 30. |

### 20. FI (Force Index) — `fi_trend`, parameter `period`

**Mechanics.** Elder (1993): FI = (close − prev_close) × volume, smoothed by EMA(N). Same horizon meaning as EMA on price. Elder explicitly recommended FI(2) as a short trigger and FI(13) for swing-trade confirmation.

**Anchors.** Elder FI(2), FI(13).

| Horizon | Slot-filled band | Why |
|---------|-------------------|-----|
| short | **2–31** | Lower bound 2 preserves Elder's reactive FI(2) trigger — the only family where short starts below 5. Upper widened to 31 for 30 slots. |
| medium | 21–80 | FI(13) at the bottom; standard EMA-on-flow horizon. |
| long | 120–250 | Slow flow trend. |

---

## Decisions on Open Issues

| Issue | Decision | Reason |
|-------|----------|--------|
| Variant ID breakage | **Accept**. Recalibration changes content-hashed IDs. No aliasing layer. | Cleanest. The pipeline is meant to discover viable variants from scratch each run. Persisted variant IDs from prior runs become orphans and that is fine; nothing in the runtime contract requires cross-recalibration ID stability. |
| Oscillator long ceiling (RSI, MFI, Stochastic, UO) | **Cap period at 50** | Past 50 the bounded oscillator math collapses signal information. Going to 60–80 buys nothing and adds noise. Long-oscillator behavior is a *pullback timer for long-thesis positions*, not a structural signal — this compromise is documented per family. |
| PSAR direction | **`short` is most flip-prone** (high `af_step` / `af_max`); `long` is slowest. | PSAR has no period — horizon is encoded purely by AF sensitivity. Wilder's "swing trader's stop" defaults sit in `medium`. |
| FI lower bound | **Keep 2** in the short band. | Preserves Elder's classical FI(2) trigger — the only family where the short range goes below 5. Documented as an explicit exception. |

---

## Files To Modify

| # | File | Change |
|---|------|--------|
| 1 | [core/quant_core/signal_engine/candidates.py](../../core/quant_core/signal_engine/candidates.py) | Replace all `_*_PARAMS` / `_*_PERIODS` / `_*_WINDOWS` dicts (lines 92–201) with the new grids. Add a `_dense_int_grid(low, high, n=30)` helper that builds an integer grid by widening upper bound until n unique values are reached. Keep `register_family`, `_make_variant`, `_take_first_n`, `variant_min_history`, generator function shapes — only the data and one helper change. |
| 2 | [core/tests/test_signal_engine.py](../../core/tests/test_signal_engine.py) | Update tests asserting specific period values to match new grids. **Keep** structural invariants: 30 candidates per (family, horizon), deterministic ordering, fast<slow / tenkan<kijun<senkou_b / period_1<period_2<period_3. Add new parametric test asserting `len(generate_candidates(family, horizon)) == 30` for every pair. Add bar-budget assertion: `max(variant_min_history(c) for c in candidates) < HORIZON_PARAMS[horizon]["train"]`. |
| 3 | [frontend/components/strategy/indicator-config.ts](../../frontend/components/strategy/indicator-config.ts) | Update default seed values per indicator so they sit inside the new `medium` band (it's the canonical default horizon in the UI). |
| 4 | [frontend/lib/strategy-v2.ts](../../frontend/lib/strategy-v2.ts) | Align horizon-keyed defaults if any exist. Verify `HorizonKey` values still match `short`/`medium`/`long`. |
| 5 | [services/api/app/strategy_v2.py](../../services/api/app/strategy_v2.py) | Align indicator default normalization with new bands. |
| 6 | [docs/signal-generation/02-candidate-universe.md](./02-candidate-universe.md) | Document the recalibrated grids and the horizon → bars mapping table at the top of this document. |
| 7 | [docs/strategy-layer/05-signal-construction-layer.md](../strategy-layer/05-signal-construction-layer.md) | Update the "Default indicator search spaces" table at lines 197–202 (currently shows the old SMA/RSI/MACD/OBV grids) to match the 20-indicator recalibrated grids. |

## Out Of Scope (DO NOT TOUCH)

- `HORIZON_PARAMS` in [core/quant_core/signal_engine/domain.py](../../core/quant_core/signal_engine/domain.py) — train/test/step window sizes. These define the OOS evaluation geometry, not the indicator parameters.
- `evaluate_variant_oos`, robustness scoring, survivor filter, redundancy reduction, ensemble math — Layers B through G stay identical.
- Cooldown defaults, time-stop defaults, entry/exit thresholds, Kelly/ATR/RR presets — these are downstream of the signal engine.
- Family-signal-type taxonomy — `FAMILY_SIGNAL_TYPE` and `CATEGORY_FAMILIES` in [domain.py](../../core/quant_core/signal_engine/domain.py).
- API routes, request/response schemas, function signatures.

## Implementation Steps (for Codex)

1. **Read the existing candidate grids** in [candidates.py:92-201](../../core/quant_core/signal_engine/candidates.py#L92-L201) to understand the data shape per family.
2. **Add a helper** `_dense_int_grid(low: int, high: int, n: int = 30) -> list[int]` that:
   - Starts from `list(range(low, high + 1))`.
   - If `len < n`, increments `high` by 1 and extends until `len == n`.
   - Returns the sorted unique list.
3. **Replace each grid** in lexical order:
   - Trend filters (SMA, EMA, OBV-EMA, AD, FI): use `_dense_int_grid` with the bands above. Note FI short starts at 2.
   - EMA Cross, MACD, Ichimoku, UO, TSI: rebuild base grids, Cartesian product, filter, sort canonically, take 30.
   - PSAR: hand-write the new grids (the bug fix is the entire point — short, medium, long must be different).
   - RSI, MFI, ADX, Stochastic: period × threshold/d-period Cartesian.
   - ROC, TRIX, CCI, CMF, VWAP: per-indicator bands as documented.
4. **Run tests** after each family change: `pytest core/tests/test_signal_engine.py::test_<family> -q`. Iterate until green.
5. **Update test fixtures** that hard-code old period values. Keep structural invariant tests intact.
6. **Add the new invariant tests** described in the Files To Modify table (count = 30, bar budget).
7. **Update frontend defaults** to fall inside the new `medium` band.
8. **Update docs** ([02-candidate-universe.md](./02-candidate-universe.md), [05-signal-construction-layer.md](../strategy-layer/05-signal-construction-layer.md)) to reflect the new grids.
9. **Run end-to-end smoke**: pick one symbol, call `run_family_ensemble_full(family, close, ...)` for each of the 20 families × 3 horizons. Confirm each returns an `EnsemblePipelineDetail` with exactly 30 tested variants.
10. **Frontend build check**: `cd frontend && npx tsc --noEmit && npm run build`.

## Verification Checklist

- [ ] `pytest core/tests/test_signal_engine.py -q` green.
- [ ] Parametric test asserts `len(generate_candidates(f, h)) == 30` for all (f, h).
- [ ] Bar-budget test passes for all (f, h): max warmup < `HORIZON_PARAMS[h]["train"]`.
- [ ] Determinism test passes (same call → same variant IDs).
- [ ] Anchor checks: `(12, 26, 9)` MACD lives in medium grid; `(9, 26, 52)` Ichimoku lives in medium grid; `(0.02, 0.20)` PSAR lives in medium grid; `RSI(14)` lives in short grid; `SMA(50)` lives in medium grid; `SMA(200)` lives in long grid; `(7, 14, 28)` UO lives in medium grid; `(25, 13)` TSI lives in medium grid; `Wilder ADX(14)` lives in short grid.
- [ ] PSAR `short` ≠ `medium` ≠ `long` (bug fix verified).
- [ ] Smoke run of all 20 families × 3 horizons returns valid `EnsemblePipelineDetail`.
- [ ] `cd frontend && npx tsc --noEmit && npm run build` green.

## Notes For Codex

- **Do not invent values**. Every range in this document is justified above. If you find a constraint that forces deviation (e.g., a parameter combination violates `variant_min_history < train_window`), report the conflict in your PR description rather than silently tightening the band.
- **Preserve the deterministic ordering**. The `_take_first_n` slice depends on stable sort order. Use canonical sort keys: for two-param families `(slow, fast)`; for three-param families `(third, second, first)`.
- **The 80–120 bar dead zone is intentional**. Do not "smooth it over" by extending medium upward or long downward. It reflects the user's horizon definitions verbatim.
- **The oscillator-long compromise is intentional**. RSI/MFI/Stochastic/UO/CMF/ADX/TSI cannot honestly span 6 months because of bounded math. Their long bands are documented as "filters for long-thesis positions" rather than 6-month standalone signals. Do not try to "fix" this by stretching periods past 50 — it makes the indicator worse.
- **Anchor every band on a literature default** (Wilder, Murphy, Lane, Hosoda, Appel, Lambert, Williams, Blau, Elder, Chaikin). If a band would not contain its canonical default, the band is wrong — recheck.
