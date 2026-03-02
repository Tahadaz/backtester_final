# SMA Defaults Discovery

## What it does
`Defaults Discovery` runs walk-forward optimization on `sma_price` and produces **exactly 9** defaults (small to large), one per bucket.

The default daily-equity buckets are:

- `B1: 3-7`
- `B2: 8-12`
- `B3: 13-20`
- `B4: 21-30`
- `B5: 31-45`
- `B6: 46-70`
- `B7: 71-110`
- `B8: 111-170`
- `B9: 171-250`

## Methodology
For each walk-forward window:

1. Slice `train` (and optional next `test`) bars.
2. For each bucket, evaluate every integer `n` in `[low, high]`.
3. Compute robust objective:
   - `score = sharpe - drawdown_weight * max_drawdown - turnover_weight * turnover`
4. Pick `best_n*` per bucket by max train score.
5. If test mode is enabled, report metrics on test slice for the chosen `best_n*`.

Aggregation per bucket:

1. Collect all `best_n*` values across windows.
2. If mode frequency >= `mode_threshold`, use mode; otherwise use median.
3. Optional snap to "nice" values inside bucket.

Final defaults are enforced to be strictly increasing across buckets.

## Why turnover penalty exists
Without turnover penalization, optimization tends to over-select very short SMA windows that trade frequently. Penalizing turnover stabilizes selected windows and reduces fragile/high-churn defaults.

## API

- `POST /defaults/sma/discover`
- `GET /defaults/runs?limit=20`
- `GET /defaults/runs/{id}`
- `DELETE /defaults/runs/{id}`
- `POST /defaults/runs/{id}/apply`
- `GET /defaults/strategy/sma/default-sets`
- `GET /defaults/strategy/sma/default-sets/latest`

## Example result JSON schema

```json
{
  "meta": {
    "train_window": 504,
    "step_size": 21,
    "use_test_window": true,
    "test_window": 63
  },
  "warnings": [],
  "window_count": 48,
  "defaults": [5, 10, 14, 25, 40, 60, 90, 125, 200],
  "bucket_reports": [
    {
      "bucket_id": "B1",
      "bucket_label": "3-7",
      "chosen_default_n": 5,
      "win_rate": 0.42,
      "stability_std": 1.21,
      "avg_score": 0.73,
      "avg_turnover": 0.09,
      "avg_drawdown": 0.14,
      "sample_count": 48
    }
  ],
  "walk_forward_winners": [
    {
      "window_index": 0,
      "bucket_id": "B1",
      "best_n": 5,
      "train_score": 0.81,
      "test_score": 0.67
    }
  ],
  "selection_matrix": [
    {
      "window_index": 0,
      "selections": {
        "B1": 5,
        "B2": 10
      }
    }
  ]
}
```

## UI

- New page: `/defaults-discovery`
- New Run integration (SMA):
  - `Manual defaults`
  - `Latest discovered defaults`
  - `Choose discovery run...`
