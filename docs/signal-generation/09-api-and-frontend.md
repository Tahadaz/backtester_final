# 09 — API Endpoints & Frontend Architecture

---

## Backend API

**File**: `services/api/app/routers/strategy_signals.py`
**Schemas**: `services/api/app/schemas/strategy_signals.py`

### Endpoints

#### POST /strategy/signal/sma-ensemble
SMA-specific ensemble (legacy — use family-ensemble instead).

#### POST /strategy/signal/family-ensemble
Generic family ensemble. Runs the full A→G pipeline for one (family, symbol, horizon).

**Request**:
```json
{
  "family": "sma|rsi|macd|obv",
  "symbol": "ATW",
  "horizon": "short|medium|long",
  "timeframe": "1D",
  "cost_bps": 10.0,
  "cooldown_bars": 0
}
```

**Response**: `FamilyCombinedSignal` — family_score_pct, family_signal_label, funnel counts, representatives list, methodology_status.

#### POST /strategy/signal/variant-detail
Full context for one variant within its family pipeline.

**Response** includes:
- `variant_id`, `archetype`, `params`, `description`
- `signal`, `signal_label` (current)
- `robustness` — all 4 component scores + reliability
- `oos_windows` — per-window metrics
- `all_variants` — all 30 candidates with status (selected/redundant/eliminated/non-viable), signal, scores, correlation info
- `funnel` — {tested, viable, competitive, representative}
- `correlation_matrix` — {labels, ids, z (2D array), is_representative flags}

#### POST /strategy/signal/variant-backtest
Backtest artifacts for one variant.

**Response** includes:
- `metrics` — aggregate OOS metrics
- `trade_performance` — fill-level statistics (win_rate, profit_factor, etc.)
- `trade_ledger` — per-fill execution records
- `plots` — Plotly JSON: price+signal, equity, drawdown
- `per_window` — per-window: plot, equity_plot, drawdown_plot, trades, metrics
- `oos_window_dates` — date ranges for each window

#### POST /strategy/signal/batch-scores
Batch computation for the stock sidebar.

**Request**:
```json
{
  "symbols": ["ATW", "BCP", "IAM"],
  "horizon": "medium",
  "timeframe": "1D",
  "cost_bps": 10.0,
  "cooldown_bars": 0
}
```

**Response**: Per-symbol:
```json
{
  "symbol": "ATW",
  "aggregate_score_pct": 25.5,
  "aggregate_signal_label": "Achat",
  "categories": {
    "tendance": {"score_pct": 35.0, "label": "Haussier", "families": ["sma", "macd"]},
    "oscillation": {"score_pct": 15.0, "label": "Survendu", "families": ["rsi"]},
    "volume": {"score_pct": 20.0, "label": "Accumulation", "families": ["obv"]}
  },
  "per_family": {
    "sma": {"score_pct": 40.0, "label": "Haussier"},
    "rsi": {"score_pct": 15.0, "label": "Survendu"},
    "macd": {"score_pct": 30.0, "label": "Haussier"},
    "obv": {"score_pct": 20.0, "label": "Accumulation"}
  }
}
```

### Caching

In-process TTL cache keyed by `(family, symbol, horizon, timeframe, cost_bps, cooldown_bars)`:
- Signal results: 5-minute TTL
- Backtest plots: 10-minute TTL

---

## Pydantic Schemas

```python
class FamilyEnsembleRequest(BaseModel):
    family: str = Field(pattern=r"^(sma|rsi|macd|obv)$")
    symbol: str
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    timeframe: str = Field(default="1D")
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)

class VariantDetailRequest(BaseModel):
    symbol: str
    variant_id: str
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    timeframe: str = Field(default="1D")
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)

class BatchScoresRequest(BaseModel):
    symbols: list[str]
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    timeframe: str = Field(default="1D")
    cost_bps: float = Field(default=10.0, ge=0, le=100)
    cooldown_bars: int = Field(default=0, ge=0)
```

---

## Frontend Architecture

### Page: `/signals`

**File**: `quant-backtesting-frontend/app/signals/page.tsx`

**Layout**: Flex — StockSidebar (280px) | Main content (flex-1)

**State**:
- `selectedSymbol: string | null`
- `horizon: "short" | "medium" | "long"` (default: "medium")
- `cooldownBars: number` (default: 0)

**Tabs** (only first enabled):
1. **Analyse Technique** → `TechnicalAnalysisPanel`
2. **Fondamentale** → PlaceholderTab ("Bientôt disponible")
3. **Quantitative** → PlaceholderTab
4. **Personnelle** → PlaceholderTab

### Component Hierarchy

```
SignalsPage
├── StockSidebar (stock-sidebar.tsx)
│   ├── useMarketCatalog() — all canonical stocks
│   ├── useBatchScores(symbols, horizon, cooldownBars)
│   ├── Search input (debounced)
│   └── Per-stock: symbol + signal label badge + display name
│
├── HorizonSelector (horizon-selector.tsx)
│   └── Toggle: Court terme / Moyen terme / Long terme
│
├── TechnicalAnalysisPanel (technical-analysis-panel.tsx)
│   ├── Level 0: Aggregate overview → single card with score bar
│   ├── Level 1: Categories → 3 sections × family cards
│   │   ├── TENDANCE (TrendingUp) — SMA, MACD
│   │   ├── OSCILLATION (Activity) — RSI
│   │   └── VOLUME (BarChart3) — OBV
│   └── Level 2: Family drilldown → SmaFamilyDrilldown
│
├── SmaFamilyDrilldown (sma-family-drilldown.tsx)
│   ├── Funnel stats (Testées → Viables → Compétitives → Représentatives)
│   ├── Score explanation text
│   └── Representative grid (2-3 cols, max 10 cards)
│       └── Click → /signals/variant/{id}
│
├── PipelineStepper (pipeline-stepper.tsx)
│   └── 4-step horizontal funnel with counts and filter tooltips
│
├── Speedometer (speedometer.tsx)
│   └── SVG gauge with 5 zones: Vente forte → Achat fort
│
├── SignalScoreBar (signal-score-bar.tsx)
│   └── Horizontal bar (-100 to +100) with dot marker
│
└── MethodologyModal (methodology-modal.tsx)
    └── 6 sections explaining the pipeline
```

### 3-Level Drill-Down Navigation

**Level 0 — Overview**:
- Single card with aggregate score bar
- Badge: "{N}/4 familles" loaded
- Click → Level 1

**Level 1 — Categories**:
- 3 category sections: Tendance, Oscillation, Volume
- Each section shows its families with score bars
- "← Vue d'ensemble" back button
- "Méthodologie" opens modal
- Click family → Level 2

**Level 2 — Family Drilldown**:
- Family name + back button
- Pipeline stepper (funnel visualization)
- Score explanation
- Grid of representative variant cards
- Click card → navigates to `/signals/variant/{id}`

### Signal Label & Color Mapping

**Score → Label**:
| Score | Label | Color |
|-------|-------|-------|
| > 50 | ACHAT FORT | Emerald |
| > 15 | ACHAT | Green |
| -15 to 15 | NEUTRE | Gray |
| -50 to -15 | VENTE | Orange |
| < -50 | VENTE FORTE | Red |

Consistent across: sidebar, score bars, speedometer, badges.

### SWR Hooks

| Hook | Purpose | Polling |
|------|---------|---------|
| `useMarketCatalog()` | Stock list for sidebar | 30s |
| `useBatchScores(symbols, horizon, cooldown)` | Per-stock aggregate scores | Standard |
| `useFamilyEnsemble(family, symbol, horizon, _, cooldown)` | Family pipeline result | Standard |
| `useVariantDetail(id, symbol, horizon, cost, cooldown)` | Variant comparison data | Standard |
| `useVariantBacktest(id, symbol, horizon, cost, cooldown)` | Variant backtest artifacts | Standard |

### Variant Detail Page

**Route**: `/signals/variant/[id]?symbol=X&horizon=medium&cooldown=0`

**3 tabs**: Comparaison | Fenêtres OOS | Fiabilité

See 08-variant-detail.md for full documentation.

### Representative Label Generation

The `repLabel()` function generates human-readable variant names:

| Family | Example Output |
|--------|---------------|
| SMA | "SMA-20" |
| SMA Cross | "SMA(10,20)" |
| RSI | "RSI-14 (30/70)" |
| MACD | "MACD(12,26,9)" |
| OBV | "OBV-EMA-20" |
