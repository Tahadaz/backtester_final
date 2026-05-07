# API Data Flow & Frontend Contracts

## Overview

This chapter maps every `/analytics/*` endpoint to its **backend schema** (Pydantic), **frontend schema** (Zod), **cache strategy**, and **UI surface**. Serves as the single source of truth for API evolution.

---

## Endpoint: GET `/analytics/macro/list`

**Purpose**: List available macro factors (VIX, DXY, BRENT, etc.) and their ingestion status.

### Backend Schema

```python
# services/api/app/schemas/analytics.py
class MacroSeriesInfo(BaseModel):
    canonical_id: str       # "VIX", "DXY", "BRENT", "SP500", "US10Y", "EURUSD"
    display_name: str       # "Volatility Index", "US Dollar Index", ...
    source: str             # "CBOE", "ICE", ...
    last_updated: datetime  # UTC
    num_data_points: int    # observations available
    earliest_date: date
    latest_date: date

class MacroListOut(BaseModel):
    factors: list[MacroSeriesInfo]
    count: int
```

### Frontend Schema

```typescript
// frontend/lib/api.ts
export const MacroSeriesInfoSchema = z.object({
  canonical_id: z.string(),
  display_name: z.string(),
  source: z.string(),
  last_updated: z.coerce.date(),
  num_data_points: z.number(),
  earliest_date: z.string(), // ISO date
  latest_date: z.string(),
})
export type MacroSeriesInfo = z.infer<typeof MacroSeriesInfoSchema>

export const MacroListOutSchema = z.object({
  factors: z.array(MacroSeriesInfoSchema),
  count: z.number(),
})
```

### UI Surface

- **Page**: `/analytics` → **Données Macro** tab
- **Component**: `MacroCatalogTable` (tabular display)
- **Columns**: Canonical ID, Display Name, Source, Last Updated, Data Points, Coverage
- **Actions**: Click row to ingest (if data is stale)

### Cache

None (metadata is cheap; refresh on page load).

---

## Endpoint: POST `/analytics/macro/ingest-all`

**Purpose**: Trigger ingestion of all 6 macro factors from external APIs (FRED, Yahoo Finance, etc.).

### Request

```
POST /analytics/macro/ingest-all
Body: {} (empty)
```

### Response (202 Accepted + Poll)

```python
class IngestStatusOut(BaseModel):
    task_id: str            # Background job ID
    status: str             # "running" | "completed" | "failed"
    factors_completed: int
    factors_total: int
    error_message: Optional[str]

class IngestInitOut(BaseModel):
    task_id: str
    message: str
```

### Frontend Integration

```typescript
export async function postMacroIngestAll() {
  const res = await apiPost("/analytics/macro/ingest-all", {})
  const task_id = res.task_id
  return task_id
}

// Poll for completion
export async function getMacroIngestStatus(task_id: string) {
  return await apiGet(`/analytics/macro/ingest-status/${task_id}`)
}
```

### UI Surface

- **Button**: "Réingérer les facteurs macro" (in **Données Macro** tab)
- **Modal**: Shows progress (X/6 completed)
- **Auto-refresh**: Polls every 2 seconds until done
- **On success**: "Ingestion complete; IC analysis refreshed"

### Cache

Ingest jobs use Redis task queue; state stored in DB once complete.

---

## Endpoint: GET `/analytics/factors/{symbol}/relevance`

**Purpose**: Descriptive Information Coefficient (IC) stats for a stock across all 6 macro factors.

### Backend Schema

```python
class FactorICOut(BaseModel):
    factor_id: str          # "VIX", "DXY", ...
    factor_display_name: str
    ic: float               # Spearman rank correlation
    tstat: float            # Newey-West t-stat
    pvalue: float           # Two-tailed
    significant: bool       # pvalue < 0.05
    n_obs: int

class FactorRelevanceOut(BaseModel):
    symbol: str
    sector: str             # from StockMaster
    factors: list[FactorICOut]
```

### Frontend Schema

```typescript
export const FactorICSchema = z.object({
  factor_id: z.string(),
  factor_display_name: z.string(),
  ic: z.number(),
  tstat: z.number(),
  pvalue: z.number(),
  significant: z.boolean(),
  n_obs: z.number(),
})

export const FactorRelevanceSchema = z.object({
  symbol: z.string(),
  sector: z.string(),
  factors: z.array(FactorICSchema),
})

export type FactorRelevance = z.infer<typeof FactorRelevanceSchema>
```

### UI Surface

- **Page**: `/analytics` → **Facteurs Macro** tab
- **Symbol picker**: Dropdown or search
- **Component**: `FactorRelevancePanel`
  - Table: 6 rows (one per factor)
  - Columns: Factor, IC, t-stat, p-value, Significant
  - Cell coloring: Green if IC > 0.10 and significant; gray if not significant
  - Hover: Shows full statistics and academic interpretation

### Cache

Redis key: `analytics:factor_relevance:{symbol}`, TTL 7200s (2 hours).

---

## Endpoint: GET `/analytics/factors/{symbol}/evaluate`

**Purpose**: Phase 1 evaluation results for a stock across all 6 signals.

### Backend Schema

```python
class FactorSignalEvalOut(BaseModel):
    factor_id: str
    signal_name: str
    symbol: str
    citation: str
    channel_filter: list[str]  # e.g., ["materials", "mining"]
    applicable: bool            # True if sector matches channel_filter
    
    # Headline metrics (zeroed if applicable=False)
    ic_h1: float
    ic_h5: float
    hit_rate: float
    sharpe: float
    after_cost_sharpe: float
    dsr: float
    psr: float
    conditional_return_tstat: float
    n_obs: int
    fdr_pass: bool
    
    # Detail (reuses Phase 0 schemas)
    ic_curve: ICCurveOut
    portfolio: PortfolioStatsOut
    robustness: RobustnessOut
```

### Frontend Schema

```typescript
export const FactorSignalEvalSchema = z.object({
  factor_id: z.string(),
  signal_name: z.string(),
  symbol: z.string(),
  citation: z.string(),
  channel_filter: z.array(z.string()),
  applicable: z.boolean(),
  
  ic_h1: z.number(), ic_h5: z.number(),
  hit_rate: z.number(),
  sharpe: z.number(), after_cost_sharpe: z.number(),
  dsr: z.number(), psr: z.number(),
  conditional_return_tstat: z.number(),
  n_obs: z.number(),
  fdr_pass: z.boolean(),
  
  ic_curve: ICCurveSchema,
  portfolio: PortfolioStatsSchema,
  robustness: RobustnessSchema,
})
```

### UI Surface

- **Page**: `/analytics` → **Facteurs Macro** tab
- **When symbol selected**: Display two panels:
  1. **FactorRelevancePanel** (Phase 0.9 descriptive IC)
  2. **FactorSignalPanel** (Phase 1 evaluation) — **NEW**
- **FactorSignalPanel**: Table with 6 rows
  - Columns: Factor, Signal Rule, Citation, IC d1, IC d5, Hit Rate, Sharpe (net), DSR, FDR, Channel
  - Row styling:
    - Green tint if `applicable=true && fdr_pass=true`
    - Default if `applicable=true && fdr_pass=false` (honest null)
    - Muted/strikethrough if `applicable=false` (channel mismatch)
  - Click row: Expands to show IC curve, portfolio metrics, robustness

### Cache

Redis key: `analytics:factor_eval:{symbol}`, TTL 3600s (1 hour).

---

## Endpoint: GET `/analytics/signals/{symbol}`

**Purpose**: List all TA signals (existing Phase 0 endpoint).

### Backend Schema

```python
class SignalEvalOut(BaseModel):
    signal_id: str
    signal_name: str
    symbol: str
    ic_h1: float
    ic_h5: float
    sharpe: float
    dsr: float
    ic_curve: ICCurveOut
    portfolio: PortfolioStatsOut
```

### UI Surface

- **Page**: `/analytics` → **Signaux TA** tab
- **Component**: `SignalEvaluationPanel` (unchanged from Phase 0)
- Shows TA signals (SMA, RSI, MACD, Bollinger, OBV, Stoch, Ichimoku)

### Cache

Redis key: `analytics:signal_eval:{symbol}`, TTL 3600s.

---

## Endpoint: GET `/analytics/macro/series/{canonical_id}`

**Purpose**: Time series for a single macro factor (for plotting).

### Backend Schema

```python
class MacroSeriesPoint(BaseModel):
    date: date
    value: float

class MacroSeriesOut(BaseModel):
    canonical_id: str
    data: list[MacroSeriesPoint]
```

### Frontend Schema

```typescript
export const MacroSeriesPointSchema = z.object({
  date: z.string(), // ISO date
  value: z.number(),
})

export const MacroSeriesSchema = z.object({
  canonical_id: z.string(),
  data: z.array(MacroSeriesPointSchema),
})
```

### UI Surface

- **Page**: `/analytics` → **Données Macro** tab
- **Component**: Interactive line chart (Recharts)
- **X-axis**: Date
- **Y-axis**: Factor value (auto-scaled)
- **Tooltip**: Date, Value

### Cache

Redis key: `analytics:macro_series:{canonical_id}`, TTL 86400s (1 day).

---

## Routing & Implementation

### Backend Router

File: `services/api/app/routers/analytics.py`

```python
@router.get("/analytics/macro/list", response_model=MacroListOut)
async def list_macro_factors(db: Session = Depends(get_db)):
    ...

@router.post("/analytics/macro/ingest-all")
async def ingest_all_macro(db: Session = Depends(get_db)):
    ...

@router.get("/analytics/factors/{symbol}/relevance", response_model=FactorRelevanceOut)
async def get_factor_relevance(symbol: str, db: Session = Depends(get_db)):
    ...

@router.get("/analytics/factors/{symbol}/evaluate", response_model=list[FactorSignalEvalOut])
async def evaluate_factor_signals(symbol: str, db: Session = Depends(get_db)):
    ...
```

### Frontend Hooks

File: `frontend/hooks/use-api.ts`

```typescript
export function useFactorRelevance(symbol: string | null) {
  const key = symbol ? `/analytics/factors/${symbol}/relevance` : null
  return useSWR<FactorRelevance>(key, getFactorRelevance, ...)
}

export function useFactorSignalEval(symbol: string | null) {
  const key = symbol ? `/analytics/factors/${symbol}/evaluate` : null
  return useSWR<FactorSignalEval[]>(key, getFactorSignalEval, ...)
}
```

---

## IC Stats Chip Integration

**Location**: `frontend/app/signals/sr-variant/[id]/page.tsx` (missing insertion).

### Current State

The page renders signal variant details. It should include an **IC Stats Chip** (already present in `/signals/variant/[id]/page.tsx`).

### Insertion

```typescript
import { ICStatsChip } from "@/components/analytics/ic-badge"

// In JSX (guarded by !srMode && symbol):
{!srMode && symbol && (
  <div className="flex gap-2">
    <ICStatsChip ic={signalEval.ic_h1} tstat={signalEval.ic_tstat} />
  </div>
)}
```

**Style**: Badge component, placed alongside signal status indicators.

---

## Error Handling

All endpoints return error responses with `detail` field:

```python
class ErrorResponse(BaseModel):
    detail: str
    status_code: int
```

### Common Errors

| Endpoint | Error | HTTP | Cause |
|----------|-------|------|-------|
| `/factors/{symbol}/evaluate` | Not Found | 404 | Symbol not in universe |
| `/macro/ingest-all` | Conflict | 409 | Ingest already running |
| `/factors/{symbol}/evaluate` | Timeout | 504 | Redis cache miss + slow compute |

### Frontend Handling

```typescript
.catch((err) => {
  if (err.status === 404) setError("Symbol not found")
  else if (err.status === 409) setError("Ingest in progress, try later")
  else setError("Failed to load; try refreshing")
})
```

---

## Schema Version Control

### Pattern

If a schema changes, increment version and maintain backward compatibility:

```python
# Good: Add field with default
class FactorSignalEvalOut(BaseModel):
    ...
    confidence_score: float = 0.5  # New field, backward compatible
```

```python
# Bad: Remove field without migration
# Old clients will break
```

### Frontend SWR Validation

Use Zod parsing to catch schema mismatches:

```typescript
const parsed = z.array(FactorSignalEvalSchema).safeParse(data)
if (!parsed.success) {
  console.error("Schema mismatch:", parsed.error)
  setError("Server response format unexpected")
}
```

---

## Caching Strategy

| Endpoint | Cache Key | TTL | Invalidation |
|----------|-----------|-----|--------------|
| `/macro/list` | N/A | N/A | On-demand (cheap) |
| `/factors/{symbol}/relevance` | `factor_relevance:{symbol}` | 2h | Manual invalidation if macro re-ingested |
| `/factors/{symbol}/evaluate` | `factor_eval:{symbol}` | 1h | Manual invalidation if signals re-run |
| `/signals/{symbol}` | `signal_eval:{symbol}` | 1h | Manual invalidation |
| `/macro/series/{id}` | `macro_series:{id}` | 1d | Daily refresh (macro data static) |

### Manual Invalidation

After running evaluations:

```python
# In execute_run or eval task
redis_client.delete(f"analytics:factor_eval:{symbol}")
redis_client.delete(f"analytics:signal_eval:{symbol}")
```

---

## References

- Backend schemas: `services/api/app/schemas/analytics.py`
- Routes: `services/api/app/routers/analytics.py`
- Frontend hooks: `frontend/hooks/use-api.ts`
- Components: `frontend/components/analytics/*.tsx`
- Signals implementation: `core/quant_core/research/factors/signals.py`
