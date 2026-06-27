# Institutional screens — implementation specification

> This document is the **implementation contract** for 5 new screening methods that complement the existing 6-pillar scoring and 7 valuation models. Codex implements directly from this spec.

## Why these 5 screens

The existing engine answers "what's fair value?" (7 valuation models) and "how does this rank cross-sectionally?" (6 pillars). It does not answer:

- **"What's the cheapest growth name in my universe?"** — handled by PEG / GARP.
- **"Which firms simultaneously have high quality AND low price?"** — handled by Magic Formula.
- **"Could this firm go bankrupt within 2 years?"** — handled by Altman Z-score.
- **"Is this firm earning more than its cost of capital?"** — handled by EVA.
- **"Is this PE expensive given the firm's actual fundamentals?"** — handled by regression-adjusted multiples.

These five screens are well-documented institutional tools. They live separately from the 6 pillars (do NOT enter `OVERALL_WEIGHTS`) and persist into `snapshot.diagnostics["screens"]`.

## Architecture

### Module location

`core/quant_core/fundamentals/screens.py` — single file containing 5 pure functions. No DB writes, no I/O. Each function takes `snapshot` (and where applicable `peer_snapshots`, `history`, `assumptions`) and returns a JSON-serializable dict.

### Public API

```python
def magic_formula(
    snapshot: FundamentalSnapshot,
    peer_snapshots: list[FundamentalSnapshot],
    sectors: dict[str, str | None] | None = None,
    *,
    peer_min_count: int = 3,
) -> dict: ...

def peg_garp(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
) -> dict: ...

def altman_z(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    sector: str | None,
) -> dict: ...

def eva(
    snapshot: FundamentalSnapshot,
    history: list[AnnualMetricRow],
    assumptions: dict[str, float],
    sector: str | None,
) -> dict: ...

def regression_adjusted_multiples(
    snapshot: FundamentalSnapshot,
    peer_snapshots: list[FundamentalSnapshot],
    sectors: dict[str, str | None] | None = None,
    *,
    cohort_min_count: int = 8,
) -> dict: ...
```

### Integration with scoring pipeline

In `core/quant_core/fundamentals/scoring.py`, modify `score_fundamental_snapshots(...)` to call all 5 screens after Phase B per-symbol assembly:

```python
from .screens import magic_formula, peg_garp, altman_z, eva, regression_adjusted_multiples

# Inside the per-symbol loop in score_fundamental_snapshots:
screens = {
    "magic_formula": magic_formula(
        snapshot, snapshots, sectors=sectors, peer_min_count=peer_min_count,
    ),
    "peg_garp": peg_garp(snapshot, symbol_history),
    "altman_z": altman_z(snapshot, symbol_history, sectors.get(snapshot.symbol)),
    "eva": eva(snapshot, symbol_history, default_assumptions, sectors.get(snapshot.symbol)),
    "regression_adj": regression_adjusted_multiples(
        snapshot, snapshots, sectors=sectors, cohort_min_count=8,
    ),
}
snapshot.diagnostics["screens"] = screens
```

`default_assumptions` is the global `DEFAULT_ASSUMPTIONS` from `valuation.py`. The scoring pipeline only needs `wacc` and `tax_rate` keys for EVA.

### Re-export

Update `core/quant_core/fundamentals/__init__.py`:

```python
from .screens import (
    magic_formula,
    peg_garp,
    altman_z,
    eva,
    regression_adjusted_multiples,
)

__all__ = [
    ...,
    "magic_formula",
    "peg_garp",
    "altman_z",
    "eva",
    "regression_adjusted_multiples",
]
```

## Output schema

Every screen returns the same top-level shape:

```python
{
    "score": float | None,            # 0-100; None when computation impossible
    "scope": "sector" | "market" | "global" | None,
    "warnings": list[str],
    "methodology": str,               # one-line prose
    # ... screen-specific fields below
}
```

The `score` is normalized 0-100 (higher = better) so screens are visually comparable.

## Screen 1 — Magic Formula (Greenblatt)

### Methodology

Joel Greenblatt's *Little Book That Beats the Market* (2005). Two-factor ranking:
- **ROC (Return on Capital):** `EBIT / (Net Working Capital + Net PPE)` — quality / capital efficiency.
- **Earnings Yield:** `EBIT / Enterprise Value` — cheapness.

Rank each symbol on both, sum the ranks. Top firms have BOTH high ROC AND high earnings yield.

### Inputs and fallbacks

| Input | Source (priority order) | Required? |
|---|---|---|
| EBIT | `snapshot.metrics["EBIT"]` → fall back: `Resultat_Exploitation` from history | Yes |
| Total_Assets | `snapshot.metrics["Total_Assets"]` → fall back: latest from history | Yes |
| Current_Assets | `snapshot.metrics["Current_Assets"]` → fall back: latest from history | Yes |
| Current_Liabilities | `snapshot.metrics["Current_Liabilities"]` → fall back: latest from history | Yes |
| Cash_and_Equivalents | `snapshot.metrics["Cash_and_Equivalents"]` → fall back: from history | No (assume 0) |
| Total_Debt | `snapshot.metrics["Total_Debt"]` → compute `NetDebt + Cash` if available | Yes |
| MarketCap_Calc | `snapshot.metrics["MarketCap_Calc"]` | Yes |

### Computation

```python
def magic_formula(snapshot, peer_snapshots, sectors=None, *, peer_min_count=3):
    warnings = []

    # 1. Resolve inputs
    ebit = _positive(snapshot.metrics.get("EBIT"))
    total_assets = _positive(snapshot.metrics.get("Total_Assets"))
    current_assets = _num(snapshot.metrics.get("Current_Assets")) or 0.0
    current_liabilities = _num(snapshot.metrics.get("Current_Liabilities")) or 0.0
    cash = _num(snapshot.metrics.get("Cash_and_Equivalents")) or 0.0
    total_debt = _num(snapshot.metrics.get("Total_Debt"))
    if total_debt is None:
        net_debt = _num(snapshot.metrics.get("NetDebt"))
        if net_debt is not None:
            total_debt = net_debt + cash
    market_cap = _positive(snapshot.metrics.get("MarketCap_Calc"))

    # 2. Eligibility gate
    if ebit is None or ebit <= 0:
        return _screen_unavailable("missing_ebit", "Magic Formula", warnings)
    if total_assets is None or market_cap is None:
        return _screen_unavailable("missing_balance_sheet_or_market_cap", "Magic Formula", warnings)

    # 3. ROC computation
    net_working_capital = max(0.0, current_assets - current_liabilities - cash)
    # Net PPE proxy: TA - CA - Goodwill (if available) - other intangibles
    # If Intangibles missing, use TA - CA as approximation (overstates PPE slightly).
    intangibles = _num(snapshot.metrics.get("Goodwill")) or 0.0
    net_ppe = max(0.0, total_assets - current_assets - intangibles)
    invested_op_capital = net_working_capital + net_ppe
    if invested_op_capital <= 0:
        return _screen_unavailable("invested_capital_non_positive", "Magic Formula", warnings)
    roc = ebit / invested_op_capital

    # 4. Earnings Yield computation
    enterprise_value = market_cap + (total_debt or 0.0) - cash
    if enterprise_value <= 0:
        return _screen_unavailable("enterprise_value_non_positive", "Magic Formula", warnings)
    earnings_yield = ebit / enterprise_value

    # 5. Cross-sectional ranks
    peer_data = _gather_peers_for_magic_formula(peer_snapshots, sectors, snapshot.symbol)
    roc_values = {sym: data["roc"] for sym, data in peer_data.items() if data["roc"] is not None}
    ey_values = {sym: data["ey"] for sym, data in peer_data.items() if data["ey"] is not None}
    roc_values[snapshot.symbol] = roc
    ey_values[snapshot.symbol] = earnings_yield

    # Sector vs market scope
    target_sector = (sectors or {}).get(snapshot.symbol)
    sector_peer_count = sum(
        1 for sym in roc_values if sym != snapshot.symbol and (sectors or {}).get(sym) == target_sector
    )
    scope = "sector" if (target_sector and sector_peer_count >= peer_min_count) else "market"

    if scope == "sector":
        roc_cohort = {sym: v for sym, v in roc_values.items() if (sectors or {}).get(sym) == target_sector}
        ey_cohort = {sym: v for sym, v in ey_values.items() if (sectors or {}).get(sym) == target_sector}
    else:
        roc_cohort = roc_values
        ey_cohort = ey_values

    roc_rank = _percentile_rank(roc_cohort, snapshot.symbol, lower_is_better=False)  # 0-100
    ey_rank = _percentile_rank(ey_cohort, snapshot.symbol, lower_is_better=False)

    if roc_rank is None or ey_rank is None:
        return _screen_unavailable("insufficient_cohort", "Magic Formula", warnings)

    score = (roc_rank + ey_rank) / 2.0

    return {
        "score": round(score, 2),
        "scope": scope,
        "warnings": warnings,
        "methodology": "Greenblatt Magic Formula: rank by (ROC + Earnings Yield) within sector when ≥3 peers, else market.",
        "roc": roc,
        "earnings_yield": earnings_yield,
        "roc_rank": roc_rank,
        "ey_rank": ey_rank,
        "components": {
            "ebit": ebit,
            "net_working_capital": net_working_capital,
            "net_ppe_proxy": net_ppe,
            "invested_op_capital": invested_op_capital,
            "enterprise_value": enterprise_value,
            "market_cap": market_cap,
            "total_debt": total_debt,
            "cash": cash,
        },
    }
```

### Helper functions

```python
def _percentile_rank(values: dict[str, float], target: str, *, lower_is_better: bool) -> float | None:
    if target not in values or len(values) < 3:
        return None
    sorted_items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(sorted_items)
    for rank, (sym, _) in enumerate(sorted_items):
        if sym == target:
            pct = 100.0 * rank / (n - 1)
            return 100.0 - pct if lower_is_better else pct
    return None


def _gather_peers_for_magic_formula(peer_snapshots, sectors, target_symbol):
    out = {}
    for peer in peer_snapshots:
        if peer.symbol == target_symbol:
            continue
        try:
            sub = magic_formula(peer, [], sectors=sectors, peer_min_count=999)  # disable ranking
        except Exception:
            continue
        if isinstance(sub, dict) and sub.get("score") is not None:
            out[peer.symbol] = {"roc": sub.get("roc"), "ey": sub.get("earnings_yield")}
    return out
```

**Note:** the recursive call uses `peer_min_count=999` so ranking is skipped during the per-peer computation (we just want ROC and EY values, not ranks). Reference implementation should optimize this by extracting an inner helper that computes only ROC and EY without ranking.

### Score interpretation

| Score | Interpretation |
|---|---|
| 80-100 | Top quintile — high ROC AND high earnings yield (the Greenblatt sweet spot) |
| 60-80 | Strong on one factor, decent on the other |
| 40-60 | Average — neither cheap nor exceptional quality |
| 20-40 | Weak on both factors |
| 0-20 | Expensive low-quality — avoid |

### Reference

Greenblatt, J. (2005). *The Little Book That Beats the Market*. Wiley.

---

## Screen 2 — PEG ratio + GARP scoring

### Methodology

Peter Lynch's "Price/Earnings to Growth" ratio. A stock at PER 20 growing 20% (PEG=1) is cheaper than PER 12 growing 4% (PEG=3). GARP = Growth At Reasonable Price.

### Inputs

| Input | Source |
|---|---|
| PE ratio (PER) | `snapshot.metrics["PER"]` |
| Earnings growth | `snapshot.metrics["NetIncome_Growth"]` (primary) → `EBIT_Growth` → 3y trailing from history |

### Computation

```python
def peg_garp(snapshot, history):
    warnings = []
    per = _positive(snapshot.metrics.get("PER"))
    if per is None:
        return _screen_unavailable("missing_per", "PEG / GARP", warnings)

    # Resolve growth with fallback chain
    growth_source = None
    growth = _ratio(snapshot.metrics.get("NetIncome_Growth"))
    if growth is not None:
        growth_source = "NetIncome_Growth"
    else:
        growth = _ratio(snapshot.metrics.get("EBIT_Growth"))
        if growth is not None:
            growth_source = "EBIT_Growth"
            warnings.append("using_ebit_growth_proxy")
        else:
            # 3y trailing NetIncome CAGR
            ni_series = _metric_series(history, "Resultat_net", "Clean_Resultat_net")
            if len(ni_series) >= 4 and ni_series[0] > 0:
                growth = (ni_series[-1] / ni_series[0]) ** (1.0 / (len(ni_series) - 1)) - 1.0
                growth_source = "trailing_3y_cagr"
                warnings.append("using_trailing_growth")
            else:
                return _screen_unavailable("missing_growth", "PEG / GARP", warnings)

    growth_pct = max(0.01, growth * 100.0)  # floor at 1% to prevent division-by-zero / inflation
    peg = per / growth_pct

    # GARP score from PEG bins
    if peg <= 0.75:
        score = 100.0
        zone = "very_cheap_growth"
    elif peg <= 1.00:
        score = 80.0
        zone = "cheap_growth"
    elif peg <= 1.50:
        score = 60.0
        zone = "reasonable_growth"
    elif peg <= 2.00:
        score = 40.0
        zone = "fairly_priced"
    elif peg <= 3.00:
        score = 20.0
        zone = "expensive_growth"
    else:
        score = 0.0
        zone = "very_expensive"

    return {
        "score": score,
        "scope": None,  # PEG is per-symbol, not cross-sectional
        "warnings": warnings,
        "methodology": "Peter Lynch PEG = PE / earnings_growth%; GARP zone scoring.",
        "peg": round(peg, 3),
        "per": per,
        "growth_used": growth,
        "growth_source": growth_source,
        "zone": zone,
    }
```

### Score interpretation

PEG ≤ 1.0 is the classic Lynch sweet spot. PEG > 2.0 = paying a premium for growth.

### Reference

Lynch, P. (1989). *One Up On Wall Street*. Simon & Schuster.

---

## Screen 3 — Altman Z-score

### Methodology

Edward Altman's bankruptcy prediction model (1968). Five-factor weighted sum:

```
Z = 1.2 × (WC/TA) + 1.4 × (RE/TA) + 3.3 × (EBIT/TA) + 0.6 × (MktCap/TL) + 1.0 × (Sales/TA)
```

Zones:
- **Z > 2.99**: Safe (low distress probability)
- **1.81 < Z ≤ 2.99**: Grey zone
- **Z ≤ 1.81**: Distress (high probability of bankruptcy within 2 years)

For financials (banks, insurers), use the Z'' emerging-market variant (4-factor, no Market Cap term):

```
Z'' = 6.56 × (WC/TA) + 3.26 × (RE/TA) + 6.72 × (EBIT/TA) + 1.05 × (BookEquity/TL)
```

Z'' zones: > 2.60 safe, 1.10 < Z ≤ 2.60 grey, ≤ 1.10 distress.

### Inputs

| Input | Source |
|---|---|
| Working Capital | `Current_Assets - Current_Liabilities` from snapshot or history |
| Retained Earnings | `snapshot.metrics["Retained_Earnings"]` or history (**workbook spec update needed**) |
| EBIT | `snapshot.metrics["EBIT"]` |
| Total Assets | `snapshot.metrics["Total_Assets"]` |
| Total Liabilities | `snapshot.metrics["Total_Liabilities"]` (**workbook spec update needed**) |
| Market Cap | `snapshot.metrics["MarketCap_Calc"]` |
| Sales | `snapshot.metrics["Chiffre_daffaires"]` or latest from history |
| Book Equity | `Total_Assets - Total_Liabilities` |

### Computation

```python
def altman_z(snapshot, history, sector):
    warnings = []
    ta = _positive(snapshot.metrics.get("Total_Assets"))
    if ta is None:
        ta = _latest_metric(history, "Total_Assets")
    if ta is None or ta <= 0:
        return _screen_unavailable("missing_total_assets", "Altman Z", warnings)

    # Working capital
    ca = _num(snapshot.metrics.get("Current_Assets")) or _latest_metric(history, "Current_Assets") or 0.0
    cl = _num(snapshot.metrics.get("Current_Liabilities")) or _latest_metric(history, "Current_Liabilities") or 0.0
    wc = ca - cl

    # Retained earnings
    re = _num(snapshot.metrics.get("Retained_Earnings"))
    if re is None:
        re = _latest_metric(history, "Retained_Earnings", "Reserves")
    if re is None:
        warnings.append("missing_retained_earnings")
        re = 0.0

    # EBIT
    ebit = _positive(snapshot.metrics.get("EBIT"))
    if ebit is None:
        ebit = _latest_metric(history, "EBIT", "Resultat_Exploitation")
    if ebit is None:
        return _screen_unavailable("missing_ebit", "Altman Z", warnings)

    # Total liabilities
    tl = _num(snapshot.metrics.get("Total_Liabilities"))
    if tl is None:
        tl = _latest_metric(history, "Total_Liabilities")
    if tl is None or tl <= 0:
        return _screen_unavailable("missing_total_liabilities", "Altman Z", warnings)

    # Market cap (for non-financial variant)
    mkt_cap = _positive(snapshot.metrics.get("MarketCap_Calc"))

    # Sales
    sales = _latest_metric(history, "Chiffre_daffaires", "Clean_Chiffre_daffaires")
    if sales is None or sales <= 0:
        return _screen_unavailable("missing_sales", "Altman Z", warnings)

    # Book equity
    book_equity = ta - tl

    # Pick variant based on sector
    is_fin = _is_financial(sector)
    if is_fin:
        # Z'' emerging-market 4-factor variant
        wc_ta = wc / ta
        re_ta = re / ta
        ebit_ta = ebit / ta
        equity_tl = book_equity / tl
        z = 6.56 * wc_ta + 3.26 * re_ta + 6.72 * ebit_ta + 1.05 * equity_tl
        components = {"wc_ta": wc_ta, "re_ta": re_ta, "ebit_ta": ebit_ta, "equity_tl": equity_tl}
        if z > 2.60:
            zone = "safe"
        elif z > 1.10:
            zone = "grey"
        else:
            zone = "distress"
        variant = "Z''"
        # Score: linearly map Z'' [0, 5] -> [0, 100]
        score = max(0.0, min(100.0, z * 20.0))
    else:
        # 5-factor manufacturing variant
        if mkt_cap is None:
            return _screen_unavailable("missing_market_cap", "Altman Z", warnings)
        wc_ta = wc / ta
        re_ta = re / ta
        ebit_ta = ebit / ta
        mkt_tl = mkt_cap / tl
        sales_ta = sales / ta
        z = 1.2 * wc_ta + 1.4 * re_ta + 3.3 * ebit_ta + 0.6 * mkt_tl + 1.0 * sales_ta
        components = {
            "wc_ta": wc_ta, "re_ta": re_ta, "ebit_ta": ebit_ta,
            "mkt_tl": mkt_tl, "sales_ta": sales_ta,
        }
        if z > 2.99:
            zone = "safe"
        elif z > 1.81:
            zone = "grey"
        else:
            zone = "distress"
        variant = "Z"
        # Score: (Z - 1.0) × 25, clamped to [0, 100]
        score = max(0.0, min(100.0, (z - 1.0) * 25.0))

    return {
        "score": round(score, 2),
        "scope": None,
        "warnings": warnings,
        "methodology": "Altman Z-score for distress probability; financials use Z'' emerging-market variant.",
        "z_value": round(z, 3),
        "variant": variant,
        "zone": zone,
        "components": components,
    }
```

### Score interpretation

| Zone | Z (mfg) | Z'' (fin) | Action |
|---|---|---|---|
| safe | > 2.99 | > 2.60 | low distress probability |
| grey | 1.81–2.99 | 1.10–2.60 | watch list — re-check quarterly |
| distress | ≤ 1.81 | ≤ 1.10 | high probability of distress within 2y |

### Reference

- Altman, E. I. (1968). "Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy." *Journal of Finance* 23(4): 589-609.
- Altman, E. I., Hartzell, J., Peck, M. (1995). "Emerging Markets Corporate Bonds: A Scoring System." *Salomon Brothers Inc*.

---

## Screen 4 — EVA (Economic Value Added)

### Methodology

Stern Stewart's framework. A firm creates economic value when ROIC exceeds WACC. EVA quantifies the spread × capital base.

```
NOPAT             = EBIT × (1 − tax_rate)
Invested Capital  = Total Debt + Book Equity                    # capital base
ROIC              = NOPAT / Invested Capital
ROIC_spread       = ROIC − WACC                                  # positive = value-creating
EVA (monetary)    = ROIC_spread × Invested Capital
EVA margin        = EVA / Revenue
```

### Inputs

| Input | Source |
|---|---|
| EBIT | snapshot or history |
| Tax rate | `assumptions["tax_rate"]` (default 30%) |
| Total Debt | `snapshot.metrics["Total_Debt"]` or `NetDebt + Cash` |
| Book Equity | `Total_Assets − Total_Liabilities` |
| WACC | `assumptions["wacc"]` |
| Revenue | `snapshot.metrics["Chiffre_daffaires"]` or history |

### Computation

```python
def eva(snapshot, history, assumptions, sector):
    warnings = []

    # EVA is not applicable for financials (banks' capital structure is regulatory)
    if _is_financial(sector):
        return {
            "score": None,
            "scope": None,
            "warnings": ["eva_not_applicable_for_financials"],
            "methodology": "Economic Value Added — skipped for financial sector firms.",
            "applicable": False,
        }

    ebit = _positive(snapshot.metrics.get("EBIT")) or _latest_metric(history, "EBIT", "Resultat_Exploitation")
    if ebit is None:
        return _screen_unavailable("missing_ebit", "EVA", warnings)

    tax_rate = float(assumptions.get("tax_rate", 0.30))
    nopat = ebit * (1.0 - tax_rate)

    total_debt = _num(snapshot.metrics.get("Total_Debt"))
    if total_debt is None:
        net_debt = _num(snapshot.metrics.get("NetDebt"))
        cash = _num(snapshot.metrics.get("Cash_and_Equivalents")) or 0.0
        if net_debt is not None:
            total_debt = net_debt + cash
    if total_debt is None:
        total_debt = 0.0
        warnings.append("missing_debt_assumed_zero")

    ta = _positive(snapshot.metrics.get("Total_Assets")) or _latest_metric(history, "Total_Assets")
    tl = _num(snapshot.metrics.get("Total_Liabilities")) or _latest_metric(history, "Total_Liabilities")
    if ta is None or tl is None:
        return _screen_unavailable("missing_balance_sheet", "EVA", warnings)
    book_equity = ta - tl

    invested_capital = total_debt + book_equity
    if invested_capital <= 0:
        return _screen_unavailable("invested_capital_non_positive", "EVA", warnings)

    roic = nopat / invested_capital
    wacc = float(assumptions.get("wacc", 0.0851))
    roic_spread = roic - wacc
    eva_value = roic_spread * invested_capital

    revenue = _latest_metric(history, "Chiffre_daffaires", "Clean_Chiffre_daffaires")
    eva_margin = eva_value / revenue if revenue and revenue > 0 else None

    # Score from ROIC spread:
    # spread = 0% → score 50 (neutral)
    # spread = +5% → score 100 (strong value creation)
    # spread = -5% → score 0 (value destruction)
    score = max(0.0, min(100.0, 50.0 + roic_spread * 1000.0))

    return {
        "score": round(score, 2),
        "scope": None,
        "warnings": warnings,
        "methodology": "EVA: ROIC vs WACC spread × invested capital.",
        "nopat": nopat,
        "roic": roic,
        "wacc_used": wacc,
        "roic_spread": roic_spread,
        "eva_value": eva_value,
        "eva_margin": eva_margin,
        "invested_capital": invested_capital,
        "components": {
            "ebit": ebit,
            "tax_rate": tax_rate,
            "total_debt": total_debt,
            "book_equity": book_equity,
            "revenue": revenue,
        },
        "applicable": True,
    }
```

### Score interpretation

| ROIC spread | Score | Reading |
|---|---|---|
| > +5% | 100 | strong value creator |
| 0% to +5% | 50–100 | modest value creation |
| 0% | 50 | break-even |
| −5% to 0% | 0–50 | mild value destruction |
| < −5% | 0 | value destroyer (capital better elsewhere) |

### Reference

- Stewart, G. B. (1991). *The Quest for Value*. Harper Business.
- Damodaran, A. (2012). *Investment Valuation*, Ch 32.

---

## Screen 5 — Regression-adjusted multiples

### Methodology

Standard practice in institutional research: a stock's PE shouldn't be compared directly to a peer's PE if their growth, ROE, or size differs. Instead, fit a cross-sectional regression of the multiple on its fundamental drivers, then compare actual to predicted.

For each multiple `m` ∈ {PER, P/B, EV/EBITDA, P/S}:
```
Fit OLS: m_i = β0 + β1 × Growth_i + β2 × ROE_i + β3 × log(MarketCap_i) + β4 × Debt_to_Equity_i + ε_i
Predict: m_pred = β0 + β1 × Growth + β2 × ROE + β3 × log(MktCap) + β4 × Lev
Residual: actual − predicted
Richness (z-score normalized): residual / cohort_residual_stdev
```

Positive richness = expensive vs predicted; negative = cheap vs predicted.

### Inputs (per-symbol from cohort)

For every peer:
- PER, Price_to_Book, EV_to_EBITDA, Price_to_Sales (4 dependent variables)
- NetIncome_Growth, ROE, MarketCap_Calc, Debt_to_Equity (4 independent variables)

### Computation

```python
import numpy as np

def regression_adjusted_multiples(snapshot, peer_snapshots, sectors=None, *, cohort_min_count=8):
    warnings = []
    multiples = ("PER", "Price_to_Book", "EV_to_EBITDA", "Price_to_Sales")

    # Build cohort (target's sector first; fall back to market if too thin)
    target_sector = (sectors or {}).get(snapshot.symbol)
    candidates = [snapshot, *peer_snapshots]
    sector_cohort = [
        s for s in candidates if (sectors or {}).get(s.symbol) == target_sector
    ] if target_sector else []
    cohort = sector_cohort if len(sector_cohort) >= cohort_min_count else candidates
    scope = "sector" if cohort is sector_cohort else "market"

    if len(cohort) < cohort_min_count:
        return _screen_unavailable("insufficient_cohort_for_regression", "Regression-adj. multiples", warnings)

    # Build the design matrix
    def build_xy(cohort, dep_metric):
        rows = []
        for s in cohort:
            m = _positive(s.metrics.get(dep_metric))
            g = _ratio(s.metrics.get("NetIncome_Growth"))
            r = _ratio(s.metrics.get("ROE"))
            mc = _positive(s.metrics.get("MarketCap_Calc"))
            lev = _num(s.metrics.get("Debt_to_Equity"))
            if any(v is None for v in (m, g, r, mc, lev)):
                continue
            rows.append((s.symbol, m, g, r, np.log(mc), lev))
        return rows

    output = {
        "score": None,
        "scope": scope,
        "warnings": warnings,
        "methodology": "Cross-sectional regression: m = β0 + β1·Growth + β2·ROE + β3·log(Size) + β4·Lev. Richness = residual standardized.",
        "regression_richness": {},
        "coefficients": {},
    }

    richness_values = []
    for dep_metric in multiples:
        rows = build_xy(cohort, dep_metric)
        if len(rows) < cohort_min_count:
            output["regression_richness"][dep_metric] = None
            warnings.append(f"insufficient_cohort_for_{dep_metric}")
            continue
        names = [r[0] for r in rows]
        y = np.array([r[1] for r in rows])
        X = np.column_stack([
            np.ones(len(rows)),
            [r[2] for r in rows],
            [r[3] for r in rows],
            [r[4] for r in rows],
            [r[5] for r in rows],
        ])
        coefs, residuals, rank, sv = np.linalg.lstsq(X, y, rcond=None)
        y_pred = X @ coefs
        resids = y - y_pred
        resid_std = float(np.std(resids, ddof=1)) if len(resids) > 1 else 0.0
        ss_res = float(np.sum(resids ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

        if snapshot.symbol in names:
            i = names.index(snapshot.symbol)
            actual = y[i]
            predicted = float(y_pred[i])
            residual = float(actual - predicted)
            richness = residual / resid_std if resid_std > 0 else 0.0
        else:
            actual = predicted = residual = richness = None

        output["regression_richness"][dep_metric] = {
            "actual": float(actual) if actual is not None else None,
            "predicted": predicted,
            "residual": residual,
            "richness_z": float(richness) if richness is not None else None,
        }
        output["coefficients"][dep_metric] = {
            "intercept": float(coefs[0]),
            "growth": float(coefs[1]),
            "roe": float(coefs[2]),
            "log_size": float(coefs[3]),
            "leverage": float(coefs[4]),
            "r_squared": round(r_squared, 4),
            "cohort_size": len(rows),
        }
        if richness is not None:
            richness_values.append(richness)

    if richness_values:
        # Score: sign-flip mean richness (cheap = positive score)
        mean_richness = float(np.mean(richness_values))
        output["score"] = max(0.0, min(100.0, 50.0 - mean_richness * 20.0))
    return output
```

### Score interpretation

| Mean richness (z) | Score | Reading |
|---|---|---|
| −2.0 | ~90 | very cheap vs predicted |
| −1.0 | ~70 | cheap vs predicted |
| 0 | 50 | priced as fundamentals suggest |
| +1.0 | ~30 | expensive vs predicted |
| +2.0 | ~10 | very expensive vs predicted |

### Reference

- Damodaran, A. (2012). *Investment Valuation*, Ch 18 ("Comparable Firms and Pricing").
- Bloomberg's RV (Relative Value) model is conceptually identical.

---

## Data dependencies — workbook spec updates

The screens introduce new required metrics. Update `docs/fundamentals-layer/03-workbook-spec.md` to add:

| Metric name | Where it lives in v3 vocab today | Action |
|---|---|---|
| `Retained_Earnings` | Missing | **Add to canonical vocabulary.** Maps to French `Reserves_consolidees` or `Capitaux_propres_part_groupe` (less retained, more equity). Workbook author should produce a `Retained_Earnings` column in `Factor_Summary_10Y`. |
| `Total_Liabilities` | Missing | **Add.** Maps to `Total_Passif − Capitaux_propres`. |
| `Total_Debt` | Partial (via `NetDebt` + `Cash`) | **Add explicit column** to avoid ambiguity. |
| `Cash_and_Equivalents` | Partial (in some yfinance imports) | **Confirm in workbook.** |
| `Goodwill` | Optional | If absent, Net PPE proxy in Magic Formula is approximate. |
| `Resultat_Exploitation` | Fallback for EBIT | Already present in some imports. |

For backwards compatibility:
- Existing snapshots without these metrics produce `score=None` per screen with a warning.
- The scoring pipeline continues without raising.

## API exposure

### 1. Extend `FundamentalStockDetailOut`

Add a top-level `screens` block under `diagnostics`:

```typescript
// frontend/lib/api.ts
export type FundamentalScreens = {
    magic_formula: {
        score: number | null
        scope: "sector" | "market" | null
        warnings: string[]
        methodology: string
        roc: number | null
        earnings_yield: number | null
        roc_rank: number | null
        ey_rank: number | null
        components: Record<string, number>
    } | null
    peg_garp: {
        score: number | null
        peg: number
        per: number
        growth_used: number
        growth_source: string
        zone: "very_cheap_growth" | "cheap_growth" | "reasonable_growth" | "fairly_priced" | "expensive_growth" | "very_expensive"
        warnings: string[]
        methodology: string
    } | null
    altman_z: {
        score: number | null
        z_value: number
        variant: "Z" | "Z''"
        zone: "safe" | "grey" | "distress"
        components: Record<string, number>
        warnings: string[]
        methodology: string
    } | null
    eva: {
        score: number | null
        applicable: boolean
        nopat: number | null
        roic: number | null
        wacc_used: number | null
        roic_spread: number | null
        eva_value: number | null
        eva_margin: number | null
        invested_capital: number | null
        components: Record<string, number | null>
        warnings: string[]
        methodology: string
    } | null
    regression_adj: {
        score: number | null
        scope: "sector" | "market" | null
        regression_richness: Record<string, {
            actual: number
            predicted: number
            residual: number
            richness_z: number
        } | null>
        coefficients: Record<string, {
            intercept: number
            growth: number
            roe: number
            log_size: number
            leverage: number
            r_squared: number
            cohort_size: number
        }>
        warnings: string[]
        methodology: string
    } | null
}
```

### 2. Extend `FundamentalUniverseRow`

```typescript
export type FundamentalUniverseRow = {
    // ... existing fields ...
    magic_formula_score: number | null
    peg_value: number | null
    altman_zone: "safe" | "grey" | "distress" | null
    eva_score: number | null
    regression_richness_avg: number | null
}
```

The Pydantic schema in `services/api/app/schemas/fundamentals.py` mirrors this.

### 3. New endpoint — single-screen ranked universe

```
GET /fundamentals/screens/{screen_name}?top=20&sector=Banques&market_region=masi
```

`screen_name` ∈ {magic_formula, peg_garp, altman_z, eva, regression_adj}.

Response: ranked list of symbols with the screen's full output for each.

```python
# services/api/app/routers/fundamentals.py
@router.get("/screens/{screen_name}")
def get_screen_ranking(
    screen_name: Literal["magic_formula", "peg_garp", "altman_z", "eva", "regression_adj"],
    top: int = 50,
    sector: str | None = None,
    market_region: str | None = None,
    scenario: str = "base",
    db: Session = Depends(get_db),
) -> list[dict]:
    # Filter snapshots, extract screens[screen_name], sort by score desc
    ...
```

## Frontend exposure (UPDATED — Claude Design integration)

> **Topology change vs original plan:** the Claude Design handoff ([20-claude-design-handoff.md](20-claude-design-handoff.md)) does NOT include a standalone Screens tab. The 5 screens are **embedded into the existing tabs** of the unified 5-tab fundamental view inside `/signals?mode=fundamental`. The standalone `<ScreenCard>` component is removed; each screen becomes a purpose-built card in its natural analytical home.

### Per-screen UI placement

| Screen | Tab | UI placement |
|---|---|---|
| **Altman Z-score** | **Qualité & ROE** | Card "Risque de défaut — Altman Z-score" below peer comparison bars. `<ZoneGauge>` (safe / grey / distress) with current Z marker + 5-factor components table + zone label chip. |
| **EVA (ROIC vs WACC)** | **Qualité & ROE** | Card "Création de valeur — ROIC vs WACC" below the Altman card. Dual horizontal bars (ROIC top + WACC bottom) + ROIC-spread label + EVA monetary + EVA margin sub-text. |
| **Magic Formula** | **Comparables** | Card "Magic Formula — Greenblatt" below the relative valuation tiles. Two bars (ROC + Earnings Yield) with sector ranks + composite Magic Formula score. |
| **PEG / GARP** | **Comparables** | Card "PEG · GARP" alongside the Magic Formula card. Zone chart with current marker + PEG value + zone label. |
| **Regression-adjusted multiples** | **Comparables** | Card "Multiples ajustés par régression" at the bottom of the tab. Per-multiple divergent bar chart (richness z-score) + coefficient inspector (collapsible). |

### Why this integration is better than a standalone Screens tab

- **Altman + EVA in Qualité:** both speak to firm-quality dimensions (distress probability and economic value creation). The analyst encounters them alongside DuPont decomposition and peer comparison — natural home.
- **Magic Formula + PEG + regression-adj in Comparables:** all three are relative-value summaries (Greenblatt rank, growth-adjusted value, fundamentals-adjusted multiples). They sit naturally beside the peer comparables table.
- The 5-tab structure stays clean — no "Screens" tab competing for the analyst's attention.

### Universe panel — sortable columns retain

The Universe screen (380px left rail) keeps the 5 new toggleable sort options:
- Magic Formula score
- PEG value
- Altman zone (safe / grey / distress filter chips)
- EVA score
- Regression richness avg (sign-flipped → high = cheap-vs-predicted)

These appear in the universe sort dropdown (`Upside / Score / Conviction / Mkt Cap / Magic Formula / PEG / Altman / EVA / Regression richness`) and optionally as toggleable columns via a column-toggle popover on the universe panel header.

### Components used per screen

| Screen card | Components used |
|---|---|
| Altman card | `<ZoneGauge>` (#14), components table (`.tbl`), zone chip |
| EVA card | Dual `.peer-bar` (one for ROIC, one for WACC), spread label, EVA monetary + margin texts |
| Magic Formula card | Two `.peer-bar` (ROC rank + Earnings Yield rank), composite score |
| PEG / GARP card | Zone chart (similar to `<ZoneGauge>` but 6 bins per `peg_garp` thresholds), current marker, PEG value |
| Regression-adjusted card | Divergent bar chart (custom SVG), per-multiple table, optional coefficient inspector |

Each card follows the standard `.card` styling from [17-ui-design-language.md](17-ui-design-language.md) §7 with a title in the header.

## Tests

### `core/tests/test_fundamentals_screens.py`

```python
def test_magic_formula_golden() -> None:
    # Synthetic snapshot with known ROC=14%, EY=8%, in cohort of 5 peers
    # Expected: roc_rank=80, ey_rank=80, score=80
    ...

def test_magic_formula_missing_inputs() -> None:
    # Missing EBIT → score=None, warning emitted
    ...

def test_peg_garp_zone_boundaries() -> None:
    # PEG=0.74 → very_cheap_growth, score=100
    # PEG=0.76 → cheap_growth, score=80
    # ... test each boundary
    ...

def test_altman_z_5_factor_safe_zone() -> None:
    # Manufacturing firm with Z=3.5 → zone="safe", score=62.5
    ...

def test_altman_z_emerging_variant_for_financial() -> None:
    # Bank with Z''=3.0 → variant="Z''", zone="safe", score=60
    ...

def test_altman_z_missing_retained_earnings() -> None:
    # RE missing → warning, score still computed with RE=0
    ...

def test_eva_skips_financials() -> None:
    # is_financial=True → applicable=False, score=None
    ...

def test_eva_value_creator() -> None:
    # ROIC=12%, WACC=8.51% → spread=3.49%, score ~ 84
    ...

def test_regression_adjusted_cohort_too_small() -> None:
    # cohort < 8 → score=None, warning insufficient_cohort
    ...

def test_regression_adjusted_per_richness() -> None:
    # Cohort with cleanly separable PER variation → richness_z matches expected
    ...
```

### Integration test

```python
def test_score_fundamental_snapshots_includes_screens() -> None:
    # Run full pipeline on synthetic cohort
    # Assert: every snapshot has snapshot.diagnostics["screens"]["magic_formula"] populated
    ...
```

## Sequenced execution

### PR-1 — `screens.py` with Magic Formula + PEG/GARP
- Both use existing canonical metrics.
- Wire into `score_fundamental_snapshots`.
- Tests + UI surfacing.

### PR-2 — Altman Z (with workbook spec update for Retained_Earnings + Total_Liabilities)
- Add to vocabulary.
- Backfill: existing imports without these → score=None cleanly.

### PR-3 — EVA
- Verify Total_Debt resolution.
- Add to `__init__.py` exports.

### PR-4 — Regression-adjusted multiples
- numpy lstsq implementation.
- Cohort gating.

### PR-5 — `/fundamentals/screens/{screen_name}` endpoint + universe-table columns
- Single-screen ranked endpoint.
- Universe-table columns + filter UI.

Each PR is independently shippable.

## Verification

After PR-5:
1. `/fundamentals/stocks/ATW` → `diagnostics.screens` populated with all 5 screens.
2. `/fundamentals/screens/magic_formula?top=10` → 10 ranked symbols.
3. UI: the 5 screens render in their integrated tab locations — Altman + EVA inside Qualité tab; Magic Formula + PEG + Regression-adj inside Comparables tab. No standalone Screens tab.
4. Filter universe table by `altman_zone=safe` → only safe-zone names visible.
5. For a bank: EVA card shows "not applicable" badge; other 4 screens populated.
6. For a symbol with missing Retained_Earnings: Altman score=None with warning displayed; other 4 screens still work.

## See also

- [04-pillars-and-scoring.md](04-pillars-and-scoring.md) — the 6-pillar system these screens complement.
- [06-valuation-models.md](06-valuation-models.md) — the 7 valuation models.
- [12-known-issues-and-limitations.md](12-known-issues-and-limitations.md) — v3 fix history.
- [13-methodology-and-sources.md](13-methodology-and-sources.md) — academic references.
- [18-ui-component-library.md](18-ui-component-library.md) — `<ScreenCard>` component spec.
