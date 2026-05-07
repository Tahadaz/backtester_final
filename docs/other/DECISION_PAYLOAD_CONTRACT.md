# Decision Payload Data Contract

## Run pipeline output (`decision_support`)

```json
{
  "schema_version": 1,
  "inputs_by_kind": {
    "ma_cross": {
      "symbols": ["IAM"],
      "decision_inputs": {
        "symbols": {
          "IAM": {
            "bars": [],
            "features": [],
            "signals": []
          }
        },
        "returns": []
      },
      "trade_ledger": []
    }
  },
  "walk_forward_rows": [],
  "walk_forward_oos_summary_by_kind": {
    "ma_cross": {
      "n_folds": 6,
      "objective_mean": 0.12,
      "objective_median": 0.1,
      "is_oos_gap_median": 0.15,
      "n_obs": 120,
      "total_return": 0.2,
      "cagr": 0.11,
      "sharpe": 1.05,
      "max_drawdown": -0.18
    }
  }
}
```

## API response: list/get decisions

Top-level fields:

- `run_id`, `symbol`, `strategy_kind`, `trial_id`, `rank`
- `params_hash`, `params_json`
- `opportunity_score`, `confidence_score`, `status`
- `opportunity_subscores`, `confidence_subscores`
- `decision_page`
- `explain`
- `computed_at`

`decision_page` contract:

- `symbol`, `strategy_kind`, `trial_id`
- `direction`: `long | short | neutral`
- `status`: `trade | watch | no_trade`
- `when_to_act`: string array (trigger lines)
- `levels`: `support`, `resistance`, `entry`, `stop`, `target`
- `invalidation`
- `risk`: `rr`, `risk_per_share`, `reward_per_share`, `score`, `invalidation`
- `opportunity`: `{ total, layers }`
- `confidence`: `{ total, layers }`
- `opportunity_score`, `confidence_score`
- `explain`
- `generated_at`

Each layer payload under `opportunity.layers` / `confidence.layers`:

- `score`
- `weight`
- `inputs` (free-form numeric/context inputs)
- `thresholds` (free-form thresholds)
- `explain`
