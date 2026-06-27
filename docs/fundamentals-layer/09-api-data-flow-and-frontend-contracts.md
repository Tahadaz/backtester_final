# API + frontend contracts

The fundamentals subsystem exposes a REST API consumed by `frontend/app/fundamentals/page.tsx` and shared via TypeScript types in `frontend/lib/api.ts`.

## Endpoints

All routes are mounted at `/fundamentals/*` via `services/api/app/routers/fundamentals.py`.

| Method | Path | Body / params | Returns | Auth |
|---|---|---|---|---|
| POST | `/fundamentals/import` | multipart `file` (Excel workbook) | `FundamentalImportOut` | admin |
| GET | `/fundamentals/imports/latest` | — | `FundamentalImportOut` (most recent succeeded) | session |
| GET | `/fundamentals/universe` | `?scenario=base&market_region=&sector=&search=` | `FundamentalUniverseRow[]` | session |
| GET | `/fundamentals/stocks/{symbol}` | `?scenario=base` | `FundamentalStockDetailOut` | session |
| GET | `/fundamentals/stocks/{symbol}/valuation` | `?scenario=base` | `ValuationResultOut[]` | session |
| GET | `/fundamentals/stocks/{symbol}/sensitivity` | `?scenario=base&axis_x=wacc&axis_y=terminal_growth&steps=5` | sensitivity matrix | session |
| GET | `/fundamentals/stocks/{symbol}/integrity` | — | latest `IntegrityReportOut` | session |
| GET/POST/DELETE | `/fundamentals/stocks/{symbol}/thesis` | `ThesisIn` for POST | current thesis / write new current / tombstone | session |
| GET | `/fundamentals/stocks/{symbol}/thesis/history` | — | thesis revision history | session |
| GET/POST | `/fundamentals/stocks/{symbol}/catalysts` | `CatalystIn` for POST | per-symbol catalysts | session |
| GET | `/fundamentals/calendar` | `?from=YYYY-MM-DD&to=YYYY-MM-DD&impact_tier=high,moderate` | coverage catalyst calendar | session |
| GET | `/fundamentals/{symbol}/assumptions/{scenario}` | â€” | resolved default + scenario + symbol override assumptions with provenance | session |
| GET/PUT/DELETE | `/fundamentals/{symbol}/assumptions/{scenario}/override` | `{overrides, note}` for PUT | current per-symbol scalar override / set new current / clear current | authenticated admin write |
| GET | `/fundamentals/stocks/{symbol}/pillar-history` | `?limit=12` | pillar score series + trend map | session |
| GET | `/fundamentals/stocks/{symbol}/tearsheet` | `?lang=fr&format=html` | printable HTML tear sheet | session |
| GET | `/fundamentals/stocks/{symbol}/ic-memo` | `?lang=fr` | printable HTML IC memo | session |
| GET | `/fundamentals/morning-note` | `?date=YYYY-MM-DD&symbols=ATW,IAM` | coverage HTML morning note | session |
| PUT | `/fundamentals/stocks/{symbol}/assumptions/{scenario}` | `AssumptionUpdateIn` | `AssumptionSetOut` with recomputed valuations | admin |
| PUT | `/fundamentals/assumptions/{scenario}` | `AssumptionUpdateIn` | `AssumptionSetOut` | admin |
| POST | `/fundamentals/recompute` | `?symbol=&scenario=base|all` | `FundamentalImportOut` | admin |

## Schemas

Defined in `services/api/app/schemas/fundamentals.py`. Frontend types mirror via `frontend/lib/api.ts` (search for `Fundamental*` types).

## Canonical snapshot resolution

All display-facing reads resolve the current fundamental import through the
shared canonical snapshot resolver. The persisted pointer is
`fundamental_latest_snapshot.is_canonical`; if an older database does not yet
have the column, the resolver falls back to the same deterministic ranking used
to write the flag. Consumers do not choose between multiple imports for the same
symbol.

The cleanup script `services/api/scripts/prune_superseded_fundamentals.py`
collapses stale per-symbol valuation artifacts. Dry-run is the default:

```bash
python services/api/scripts/prune_superseded_fundamentals.py
python services/api/scripts/prune_superseded_fundamentals.py --symbols MNG ATW
python services/api/scripts/prune_superseded_fundamentals.py --apply
```

The script deletes superseded latest-snapshot, valuation, ensemble, and
projection rows only. It never deletes `fundamental_import` audit rows,
`fundamental_source_document` provenance, or annual/period source metrics.

### `FundamentalUniverseRow`

The list-view row. Slimmed to keep `/universe` fast.

```typescript
{
    symbol: string;
    company_name: string | null;
    sector: string | null;
    market_region: string | null;
    current_price: number | null;
    market_cap: number | null;
    latest_statement_year: number | null;
    overall_score: number | null;
    value_score: number | null;
    quality_score: number | null;
    growth_score: number | null;
    risk_score: number | null;
    cash_flow_score: number | null;
    health_score: number | null;
    dividend_score: number | null;
    accrual_quality_score: number | null;
    ensemble: FundamentalEnsembleSummary | null;
    valuation_summary: { consensus_upside_pct: number | null; ... };
    technical: { signal_label: string | null; ... } | null;   // cross-layer enrichment
    data_quality: string | null;
}
```

### `FundamentalStockDetailOut`

The full per-symbol payload powering the detail panel.

```typescript
{
    symbol: string;
    snapshot: {
        metrics: Record<string, number | null>;     // raw values
        scores: Record<string, number | null>;      // pillar scores
        diagnostics: {                              // Piotroski / DuPont / accrual
            dupont: { ... };
            piotroski_lite: { ... };
            accrual_quality: { ... };
        };
        coverage: { ... };
        source: { workbook_filename, imported_at, ... };
    };
    annual_metrics: AnnualMetricRow[];              // long-form for sparklines
    valuations: ValuationResultOut[];               // 7 per-model results
    ensemble: EnsembleOut;                          // selected scenario
    ensembles: Record<"bear"|"base"|"bull", EnsembleOut>; // all scenarios when persisted
    quality_issues: QualityIssueOut[];
    assumptions: AssumptionSetOut;                  // currently active (after resolution)
    assumption_provenance: Record<string, Record<string, "default"|"scenario"|"symbol">>;
    technical_context: { ... } | null;
}
```

### `ValuationResultOut`

```typescript
{
    symbol: string;
    scenario: string;             // "bear", "base", or "bull"
    model: string;                // "fcff_dcf", "ddm", etc.
    fair_value: number | null;
    current_price: number | null;
    upside_pct: number | null;
    confidence: "high" | "medium" | "low" | "unavailable";
    inputs: Record<string, any>;
    outputs: Record<string, any>;
    warnings: string[];
    family: "intrinsic" | "relative" | "diagnostic";
    methodology: string;
    confidence_score: number | null;
    weight: number | null;        // ensemble weight share
    is_proxy: boolean;
    data_quality_score: number;   // 0-100
    currency: string | null;
}
```

### `EnsembleOut`

```typescript
{
    symbol: string;
    scenario: string;
    fair_value_low: number | null;
    fair_value_base: number | null;
    fair_value_high: number | null;
    current_price: number | null;
    upside_pct: number | null;
    confidence_score: number | null;
    usable_model_count: number;
    excluded_model_count: number;
    model_weights: Record<string, number>;
    warnings: string[];
    currency: string | null;
    model_dispersion_low: number | null;
    model_dispersion_base: number | null;
    model_dispersion_high: number | null;
    monte_carlo_low: number | null;
    monte_carlo_base: number | null;
    monte_carlo_high: number | null;
    fair_value_mean: number | null;
    model_dispersion_cv: number | null;
    dispersion_factor: number | null;
}
```

## Frontend page surface

`frontend/app/fundamentals/page.tsx`. Layout:

```
┌──────────────────────────────────────────────────────────────────┐
│  Header: search bar + import button + freshness chip             │
├────────────┬─────────────────────────────────┬───────────────────┤
│            │                                 │                   │
│  Universe  │  Pillar gauges (6 bars)         │  Valuation summary│
│  table     │  + Composite score              │  (fair value      │
│  (left)    │  + Sector / size badges         │   triangle,        │
│            │                                 │   upside,          │
│            │                                 │   confidence)     │
│            │                                 │                   │
├────────────┴─────────────────────────────────┴───────────────────┤
│  Detail tabs:                                                    │
│  [Summary] [Valuation] [Quality] [Financials] [Assumptions]      │
│  [Lineage]                                                        │
├──────────────────────────────────────────────────────────────────┤
│  Active tab body                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Tab contents

**Summary** — narrative description, top-3 positive and top-3 negative score contributors, key dates (latest statement year, last import).

**Valuation** — per-model table (7 rows). Each row: model name, fair value, low/high, confidence, weight, warnings count. Click a row to expand `inputs` and `outputs` JSON. Ensemble band rendered above the table.

**Quality** — `FundamentalQualityIssue` list with severity chips (error/warn/info) and `metric_name` / `statement_year` context.

**Financials** — annual metric table. Rows are metric names (Revenue, EBIT, EBITDA, NetIncome, FCF, Total Debt, Cash, Equity). Columns are fiscal years (5 most recent). Each row has a sparkline.

**Assumptions** — editable form with current values for each assumption (cost_of_equity, WACC, terminal_growth, growth_cap, stable_payout_ratio). On save, `PUT` the new assumption set and re-render.

**Lineage** — source workbook filename, imported_at, parser version, methodology_version, list of metric sources (which sheet/cell each came from).

## Cross-layer integration

`FundamentalUniverseRow.technical` is populated by joining to the signal layer's recent signal label for the same symbol. Source: `services/api/app/services/fundamentals.py:technical_context`. The frontend uses it to display a tiny "Technical: BUY/HOLD/SELL" badge next to the fundamental row.

**Note:** this is a one-way link (fundamentals reads technical). The reverse — signal engine consuming fundamental scores — is not yet implemented. See the integration plan in `/Users/taha/.claude/plans/`.

## Error handling

| Endpoint | Failure case | Response |
|---|---|---|
| `POST /fundamentals/import` | File too large / not Excel | 422 |
| `POST /fundamentals/import` | Storage error | 500 |
| `GET /fundamentals/stocks/{symbol}` | Symbol not in fundamentals | 404 |
| `GET /fundamentals/stocks/{symbol}` | Symbol exists in `stock_master` but no snapshot | 200 with `snapshot: null` and `valuations: []` |
| `PUT .../assumptions/{scenario}` | Invalid JSON body | 422 |
| `PUT .../assumptions/{scenario}` | `terminal_growth >= cost_of_equity` | 422 with warning |

## Frontend gotchas

- `current_price` on snapshots is **as of workbook upload time**, not real-time. The signal layer maintains live prices; fundamentals does not refresh on quote ticks.
- `ensemble.upside_pct` may be `null` if either `fair_value_base` or `current_price` is missing — UI must guard.
- `model_weights` keys are model names; values are 0-1 ratios summing to ≤ 1.0 (≤1 because diagnostic models contribute 0).
- When `usable_model_count == 1`, the band collapses to a single number — show a warning chip "Ensemble of 1".

## See also

- [02-data-flow.md](02-data-flow.md) — full pipeline from upload to UI.
- [15-ui-goals-and-design.md](15-ui-goals-and-design.md) — planned UI evolutions.
