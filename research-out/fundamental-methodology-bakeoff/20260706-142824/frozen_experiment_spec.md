# Frozen Experiment Specification

Generated: 2026-07-06T14:29:58.946801+00:00

## Specification

```json
{
  "methodology_version": "fundamental_methodology_bakeoff_v1_2026_07_06",
  "run_id": "20260706-142824",
  "config": {
    "primary_horizon": "6m",
    "horizons": [
      "1m",
      "3m",
      "6m",
      "12m"
    ],
    "rebalance_frequency": "monthly panel dates",
    "portfolio": "top tercile minus bottom tercile, equal-weight, same rules for all methods",
    "cost_bps": 33.0,
    "stress_cost_bps": 75.0,
    "valuation_sample_step": 3,
    "valuation_assumptions": "valuation.py default base assumptions treated as fixed methodology parameters",
    "common_sample_rule": "drop stock-date rows missing any of A/B/C/D primary signals"
  },
  "signals": {
    "classical_characteristics": "A composite: z(B/M) + z(profitability approximation) - z(asset growth), >=2 components",
    "intrinsic_valuation": "B systematic PIT valuation gap from valuation engine base scenario, fixed default assumptions",
    "fundamental_momentum": "C accounting change/improvement composite; no analyst revisions due lack of true revision history",
    "residual_value": "D cheapness residual from log(P/B) explained by ROE, revenue growth, and size",
    "book_to_market": "A1 PIT book equity / PIT market cap",
    "profitability": "A3 profitability approximation: financial ROE, non-financial operating profit/book or ROA fallback",
    "investment_conservative": "A4 negative asset growth for non-financials",
    "op_margin_change": "C delta operating margin",
    "roe_change": "C delta ROE",
    "roa_change": "C delta ROA",
    "cashflow_conversion_change": "C delta CFO/net-income conversion",
    "revenue_growth": "C latest revenue growth",
    "earnings_growth": "C latest positive-base earnings growth",
    "sfc_custom_v2": "Legacy benchmark current SFC core score"
  },
  "signal_directions": {
    "book_to_market": "higher is better",
    "profitability": "higher is better",
    "investment_conservative": "lower asset growth is better",
    "intrinsic_valuation": "higher fair-value gap is better",
    "fundamental_momentum": "improvement is better",
    "residual_value": "lower valuation than fundamentals predict is better"
  },
  "database_audit": {
    "fundamental_annual_metric": "164138",
    "fundamental_period_metric": "142458",
    "fundamental_consensus_estimate": "357",
    "fundamental_ensemble_result": "2139",
    "fundamental_valuation_result": "14973",
    "market_data_store": "91",
    "stock_master": "73",
    "fundamental_cross_section_score": "71",
    "consensus_range": "(datetime.date(2026, 5, 25), datetime.date(2026, 6, 28), 37)",
    "persisted_valuation_range": "(datetime.datetime(2026, 5, 26, 11, 42, 7, 991269, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 7, 6, 13, 23, 39, 749920, tzinfo=datetime.timezone.utc), 73, 36)"
  },
  "config_hash": "abbedbc09ce113b1"
}
```
