# Calendar Alignment & Lag Rules

## Overview

Macroeconomic factor time series and equity returns have **different session structures** and **different data-point timings**. Aligning them without look-ahead bias is the foundation of defensible backtests. This chapter documents session timings, lag semantics, and adversarial edge cases.

## Session Timings (UTC)

### Equity Markets

| Market | Symbol | Session Open (UTC) | Session Close (UTC) | Notes |
|--------|--------|-------------------|-------------------|-------|
| MASI (Morocco) | ATW, BCP, BMCE, IAM, CDM, ADDH, COSU, WAA | 10:00 | 17:35 | TZ: GMT+0 (no DST) |
| S&P 500 (US) | (macro factor source) | 14:30 | 21:00 | TZ: ET (UTC-5 or UTC-4 with DST) |
| EUROSTOXX | (macro factor source) | 08:00 | 16:30 | TZ: CET (UTC+1 or UTC+2 with DST) |

### Macro Factor Data-Point Timing

| Factor | Source | Frequency | Timing (UTC) | Notes |
|--------|--------|-----------|-------------|-------|
| VIX | CBOE (US) | Daily | ~21:00 (US close) | Close-to-close; published after market close |
| DXY | ICE (US) | Daily | ~21:00 | Close-to-close; FX markets 24/5 |
| BRENT | ICE (NYMEX) | Daily | ~21:00 | Close-to-close (NYMEX close) |
| SP500 | CME (US) | Daily | ~21:00 | Close-to-close |
| US10Y | Bloomberg/FRED | Daily | ~17:00 or 21:00 | End-of-US-session or end-of-NY-session |
| EURUSD | LSEG/Reuters | Daily | 21:00 or 22:00 (FX close) | Typically 22:00 UTC |

---

## Lag Rules

### Semantics

A **lag rule** specifies when a factor observation becomes **usable** for predicting the next equity return. Three common rules:

#### 1. `precede_open` (Default)

**Definition**: A factor observation from day *t* (available after its session close) is aligned to equity returns on day *t+1*.

**Intuition**: The factor "precedes" the next trading day's open, giving it time to influence sentiment before market open.

**Example**:
```
Day T (after market close):    VIX closes at 18.5
Day T+1 (market open):         MASI opens; VIX=18.5 is usable
Day T+1 (return):              MASI closes; we measure return
Signal:                         vix_zscore(VIX=18.5) → +1
Prediction target:             MASI return on T+1
```

**Look-ahead risk**: None. The factor is known before T+1's open.

#### 2. `previous_close` (Conservative)

**Definition**: A factor from day *t-1* is aligned to equity returns on day *t*.

**Intuition**: The most conservative: factor is known by close of *t-1*, so by *t* open, we have 24h to react.

**Example**:
```
Day T-1 (close):      VIX closes at 18.5
Day T (open):         MASI opens; we already know VIX=18.5 (from yesterday)
Day T (return):       MASI closes; measure return
Signal:               vix_zscore(VIX=18.5) → +1
Prediction target:    MASI return on T
```

**Look-ahead risk**: None. Factor is from prior close.

#### 3. `contemporaneous` (Biased)

**Definition**: A factor from day *t* is aligned to equity returns on day *t*.

**Intuition**: Intraday alignment; assumes intraday factor updates and synchronous market impact.

**Example**:
```
Day T (intraday):   VIX and MASI both updating; same-day correlation
```

**Look-ahead risk**: HIGH. If the factor is updated mid-day or at close, aligning it to the same day's equity return introduces look-ahead bias. **Not recommended for daily backtests.**

---

## Implementation: `align_factor_to_target()`

Located in `core/quant_core/research/alignment.py`:

```python
def align_factor_to_target(
    factor: pd.Series,
    target: pd.Series,
    lag_rule: str = "precede_open",  # "precede_open" | "previous_close" | "contemporaneous"
    max_staleness: int = 3
) -> pd.Series:
    """
    Align factor to target, respecting lag rule and max staleness.
    
    Returns aligned factor series with:
    - NaN where insufficient data
    - NaN where staleness > max_staleness
    """
```

### Parameters

- **factor**: Daily macro factor series (DatetimeIndex, values).
- **target**: Daily equity return series (DatetimeIndex, values).
- **lag_rule**: One of `{"precede_open", "previous_close", "contemporaneous"}`.
- **max_staleness**: Maximum gap (in days) between factor and target observation. Prevents using stale data across gaps (e.g., weekends, holidays).

### Max Staleness Rule

If the factor's last observation is more than `max_staleness` days old, the aligned result is NaN.

**Example**:
```
max_staleness=3
factor dates:    [2026-04-20, 2026-04-21, 2026-04-22]
target dates:    [2026-04-20, 2026-04-21, 2026-04-22, 2026-04-23, 2026-04-24, 2026-04-25]
                                                      (Fri)     (Sat)     (Sun)

On 2026-04-24 (Saturday, no equities trading):
  staleness = 2 days (last factor = 04-22)
  max_staleness=3 → OK, use factor from 04-22

On 2026-04-25 (Sunday):
  staleness = 3 days → borderline
  
If target trading resumes Monday 2026-04-28:
  staleness = 6 days (factor from 04-22, now using on 04-28)
  max_staleness=3 → FAIL, output NaN for 04-28
```

**Rationale**: Prevents using weekend/holiday factor data for the next trading day if the gap is too large. A 3-day gap spans a typical long weekend; 6 days suggests a structural break.

---

## Adversarial Cases

### Case 1: US Holiday (MASI Open, US Close)

**Scenario**: Thanksgiving (US holiday, NYSE closed) but MASI opens as normal.

```
Nov 27 (Wednesday, US Thanksgiving):
  - MASI: trading as normal, open 10:00 UTC, close 17:35 UTC
  - NY:   market closed (no VIX, BRENT update from US)
  
Nov 28 (Friday after Thanksgiving):
  - MASI: trading
  - US:   market open; VIX closes at 21:00 UTC
```

**Alignment with lag_rule="precede_open"**:
```
Nov 27:     VIX: no update (US closed). staleness → NaN
Nov 28:     VIX: updated (US open). Use for Nov 29 MASI (precede_open)
```

**Mitigation**: `max_staleness=3` ensures we don't use a VIX from Nov 26 for Nov 29 MASI returns.

### Case 2: Daylight Saving Time (US)

**Scenario**: US transitions from ET to EDT (spring forward, 2nd Sunday in March).

```
March 13, 2026 (EDT begins):
  - Before: ET = UTC-5
  - After:  EDT = UTC-4 (clocks jump forward 2:00 AM → 3:00 AM)
  - MASI:   unaffected (Morocco does not observe DST)

US market close shifts by 1 hour UTC:
  - Before EDT: 21:00 UTC (16:00 EDT)
  - After EDT:  20:00 UTC (16:00 EDT)
```

**Data handling**: If factor series timestamps are in UTC, the DST transition appears as a 1-hour shift. Resampling or alignment must account for this. The `align_factor_to_target()` function assumes both series are in UTC and handles DST via calendar-aware resampling.

### Case 3: Eid al-Fitr (Morocco-Specific)

**Scenario**: Eid is an Islamic holiday (lunar calendar, varies yearly). MASI is closed, but US markets are open.

```
April 10, 2026 (Eid al-Fitr, predicted):
  - MASI:   CLOSED (no MASI trading)
  - US:     open; VIX, BRENT updated
  - EUR:    open; EURUSD updated
  
April 11, 2026:
  - MASI:   trading resumes
  - US:     trading as normal
```

**Alignment with lag_rule="precede_open"**:
```
April 10:     MASI returns: NaN (market closed)
              VIX, BRENT:  updated
              
April 11:     MASI returns: real (market open)
              Factors from April 10 precede April 11 open → use
              Staleness = 1 day → OK
```

**Mitigation**: `max_staleness=3` handles the Eid gap as long as the break is ≤3 days.

### Case 4: Data Point Timing Ambiguity

**Scenario**: A factor's "date" label is ambiguous — is it the open-time or close-time observation?

**Example**: 
- VIX published at 16:00 ET (intraday snapshot) vs. 16:30 ET (close)
- If labeled as "April 20" but published mid-day, using it for April 21 is look-ahead.

**Mitigation**:
1. **Explicit source documentation**: For each factor, document when the data point is known (e.g., "FRED US10Y is end-of-NY-session, posted same day around 17:00 UTC").
2. **Conservative default**: If in doubt, apply `previous_close` lag rule (use April 20 VIX for April 21 return).
3. **Audit**: Compare `lag_rule="contemporaneous"` vs. `lag_rule="precede_open"` results. If they differ significantly, there is likely a look-ahead bias in the contemporaneous version.

---

## Proof of No Look-Ahead

For Phase 1 evaluation, we use `lag_rule="precede_open", max_staleness=3`:

1. **Precede-open semantics**: Factor from day *t* is known by start of day *t+1*; return is measured at close of *t+1*. No look-ahead.
2. **Staleness gate**: If factor is older than 3 days, output is NaN; prevents using stale data across gaps.
3. **UTC timestamps**: All series are aligned to UTC; DST transitions are handled by calendar-aware resampling.

**Auditable invariant**: For every (date, factor, return) triple in the evaluation:
```
factor_date + lag_offset <= return_date
lag_offset = +1 (precede_open) or 0 (previous_close)
factor.timestamp < target.open_timestamp_next_day
```

---

## Practical Implications

### For Backtests

- **Do not use contemporaneous alignment** for daily signals; it introduces subtle look-ahead bias.
- **Always specify lag_rule and max_staleness** in experiment configs.
- **Log warnings** if any target return has NaN factor (due to staleness or missing data).

### For Live Trading

- **Precede_open rule ensures execution timing**: The factor is known before market open, giving time for position setup before 10:00 UTC MASI open.
- **Borrow external factor updates**: VIX, DXY, BRENT, EURUSD, US10Y are published by ~21:00 UTC on trading days; MASI opens next day at 10:00 UTC. Window is **13 hours** to compute signals and submit orders.
- **Holiday logic**: If a factor has not updated in 3+ days (e.g., long weekend), do not trade that day; wait for fresh data.

---

## References

- Implementation: `core/quant_core/research/alignment.py:align_factor_to_target()`
- Integration in eval harness: `core/quant_core/research/evaluate.py:evaluate_signal()` calls alignment internally.
- Macro ingestion: `services/worker/tasks/ingest_market_data.py` (creates factor series with UTC timestamps).
