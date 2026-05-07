# Phase 1: Factor-Only Trading Signals

## Overview

This chapter documents the six pre-registered trading signals derived from macroeconomic factors. Each rule is frozen in `docs/research/phase1_pre_registration.yaml` with exact parameter values determined before any out-of-sample evaluation. The signals are evaluated through the existing `evaluate_signal()` harness and appear in the analytics research panel.

## 1. VIX Z-Score (Ilmanen 2011)

**Factor**: VIX (Volatility Index)  
**Rule**: Treat VIX as a risk-on/off gate via standardized score  
**Citation**: Ilmanen, A. (2011). *Expected Returns*, Ch. 15

### Signal Definition

```
z20 = (VIX - mean(VIX, 20d)) / std(VIX, 20d)
if z20 < -1.0  →  +1  (compressed volatility, risk-on)
if z20 > +2.0  →  -1  (elevated volatility, risk-off)
else           →   0
```

### Parameters

- **window**: 20 days
- **z_long**: -1.0 (entry for long positioning)
- **z_short**: +2.0 (entry for short positioning)

### Rationale

Low VIX (compressed z-score) indicates complacency and risk appetite, favoring long positioning in risky assets (equities, commodities, EM). High VIX (extreme positive z-score) indicates fear and flight-to-safety, favoring short or hedged positions. The asymmetric thresholds (-1 vs +2) reflect empirical volatility clustering: prolonged low-vol regimes are common, while VIX spikes are sharp but mean-reverting.

---

## 2. DXY Momentum (Hau & Rey 2006)

**Factor**: DXY (US Dollar Index)  
**Rule**: Momentum-driven carry and EM currency channel  
**Citation**: Hau, H. & Rey, H. (2006). "Exchange Rates, Equity Prices, and Capital Flows." *Journal of Finance*

### Signal Definition

```
mom20 = return(DXY, 20d)
if mom20 < 0   →  +1  (DXY falling, EM tailwind)
if mom20 >= 0  →  -1  (DXY rising, EM headwind)
```

### Parameters

- **window**: 20 days

### Rationale

A falling dollar strengthens emerging-market local currencies, reducing debt burdens (much EM corporate debt is USD-denominated) and improving competitiveness. A rising dollar tightens EM financial conditions and depresses commodity prices. This signal applies to all sectors globally, though it is particularly material for mining and commodities exports.

---

## 3. Brent Direction (Commodity Channel)

**Factor**: BRENT (Brent Crude Oil, USD/bbl)  
**Rule**: Directional momentum in commodity/energy prices  
**Citation**: Economic channel linkage (materials, mining, chemicals)

### Signal Definition

```
mom5 = return(BRENT, 5d)
if mom5 > 0   →  +1  (rising oil, tailwind for energy/materials)
if mom5 <= 0  →  -1  (falling oil, headwind for extractive sectors)
```

### Parameters

- **window**: 5 days
- **channel_filter**: [materials, mining, chemicals]

### Rationale

Oil price movements directly affect input costs and demand for extractive and chemically-intensive sectors. Rising Brent indicates strong industrial demand and inflation expectations, benefiting commodity producers. Falling Brent signals recessionary risk or demand destruction.

**Channel gating**: This signal is filtered to materials, mining, and chemicals sectors only. For banks, telecom, or consumer stocks, the signal is marked `applicable=false` and metrics are zeroed in the evaluation output.

---

## 4. SP500 + VIX Confirmation (Ilmanen 2011)

**Factor**: SP500, VIX  
**Rule**: Dual-condition risk-sentiment gate  
**Citation**: Ilmanen, A. (2011). *Expected Returns*, Ch. 15

### Signal Definition

```
mom5_sp500 = return(SP500, 5d)
z20_vix = (VIX - mean(VIX, 20d)) / std(VIX, 20d)

if (mom5_sp500 > 0) AND (z20_vix < +1.0)  →  +1  (momentum + low volatility)
else                                      →   0
```

### Parameters

- **sp500_window**: 5 days
- **vix_window**: 20 days
- **vix_z_cap**: +1.0 (VIX z-score ceiling for confirmation)

### Rationale

This is a **confirmation filter**: we only go long risk when **both** US equities show positive momentum **and** volatility is not elevated. This avoids catching falling knives (spike reversals in VIX) and requires dual validation. The VIX cap of +1.0 is looser than the dedicated VIX-short threshold (+2.0), reflecting the role of confirmation rather than standalone signal.

---

## 5. US 10Y Yield Shock (Campbell & Shiller 1988)

**Factor**: US10Y (US 10-Year Treasury Yield, %)  
**Rule**: Duration shock detector for fixed-income and rate-sensitive sectors  
**Citation**: Campbell, J. Y. & Shiller, R. J. (1988). "Stock Prices, Earnings, and Expected Dividends." *Journal of Finance*

### Signal Definition

```
Δ5d_yield = yield(day) - yield(day-5d)  [in percentage points]
if |Δ5d_yield| > 0.20  [i.e., 20 basis points]
   →  -1  (tightening shock, headwind for duration)
else
   →   0
```

### Parameters

- **window**: 5 days
- **shock_threshold_bp**: 20 basis points (0.20 percentage points)

### Rationale

Rapid upward movements in long-term yields signal unexpected tightening or inflation concerns, hurting bond prices and duration-sensitive sectors (banks, insurance, real estate). A 20 bp move in 5 days is material and triggers a defensive stance. Note the convention: US10Y is stored in **percent** (e.g., 4.5 = 4.5%), so 20 bp = 0.20.

**Channel gating**: This signal applies to banks, insurance, and real_estate sectors. Other sectors are marked `applicable=false`.

---

## 6. EUR/USD Momentum (MAD Peg Channel)

**Factor**: EURUSD (EUR/USD Exchange Rate)  
**Rule**: Momentum in currency pair anchoring MASI-traded equities  
**Citation**: Regional context (Moroccan Dirham pegs to EUR ~60%, USD ~40%)

### Signal Definition

```
mom20 = return(EURUSD, 20d)
if mom20 > 0   →  +1  (EUR strengthening, MAD appreciation)
if mom20 <= 0  →  -1  (EUR weakening, MAD depreciation)
```

### Parameters

- **window**: 20 days

### Rationale

The Moroccan Dirham (MAD) follows a quasi-peg with ~60% weight on EUR and ~40% weight on USD. EURUSD movements directly translate to MAD currency strength. A rising EUR benefits MAD-denominated companies with EUR revenue exposure and helps foreign investors' realized returns. This signal applies globally but is particularly material for Morocco-listed exporters and multinationals.

---

## Summary

| Signal | Factor(s) | Window | Rule | Channel |
|--------|-----------|--------|------|---------|
| vix_zscore | VIX | 20d | z-score gates | all |
| dxy_momentum | DXY | 20d | 20d return | all |
| brent_direction | BRENT | 5d | 5d direction | materials, mining, chemicals |
| sp500_vix_confirmation | SP500, VIX | 5d/20d | dual condition | all |
| us10y_shock | US10Y | 5d | Δ > 20 bp | banks, insurance, real_estate |
| eurusd_momentum | EURUSD | 20d | 20d direction | all |

All signals output values in {-1, 0, +1} and are compatible with the existing `evaluate_signal()` harness in `core/quant_core/research/evaluate.py`.
