# Strategy Page Redesign + Backtest WFO Implementation Plan

## Context

The quantitative backtesting platform has 4 pages: Data -> Signals -> Strategy -> Backtest. The Strategy page is ~70% built but uses a flat signal/bet-sizing/risk model. The docs (strategy-layer 02-11, architecture 01-04) specify a richer per-stock configuration with WFO parameter flagging, entry/exit rule builders, and a handoff to the Backtest page. The Backtest page currently runs a simple single-pass backtest — the docs specify a full Pardo WFO pipeline (PROM, neighbor-averaging, WFE, Kelly, Monte Carlo, DSR).

**Goal:** Produce a single Codex-ready implementation plan (.md file) that can be executed in autoaccept mode to bring both pages in line with the documented architecture.

**User preferences:** Keep Capital + Universe + Allocation sections as-is. Restructure per-stock tabs from `Allocation | Signal | Bet Sizing | Risk` to `Allocation | Signal | Entry Rules | Exit Rules | Risk | Review`. Include signal-construction preview and risk preview. Defer entry/exit rule previews. French labels in UI. Both Strategy + Backtest in one plan.

---

## Phase 1 — Strategy Page: New Types + Shared Components

### Step 1.1: New TypeScript types file

**Create** `quant-backtesting-frontend/lib/strategy-types.ts`

Define and export:

```ts
// --- WFO Parameter wrapper (de Prado / Pardo dual-mode) ---
export type WFOParam<T = number> = {
  mode: "manual" | "wfo"
  value: T
  scan_min?: T
  scan_max?: T
  scan_step?: T
}

export type StrategyType = "trend_following" | "mean_reversion"
export type FamilyId = "sma" | "rsi" | "macd" | "obv"
export type ConfigOption = "A" | "B" | "C" | "D" | "E"
export type RuleOperator = ">" | ">=" | "<" | "<="
export type ScoreVariable =
  | "trend_score"      // SMA continuous score
  | "momentum_score"   // MACD continuous score
  | "oscillation_score" // RSI raw value
  | "volume_score"     // OBV deviation score
  | "consensus_score"  // weighted consensus

export interface FamilyConfig {
  enabled: boolean
  indicator_type: string // "price_vs_sma" | "rsi_wilder" | "macd_histogram" | "obv_deviation"
  params: Record<string, WFOParam<number>>
}

export interface SignalConstructionConfig {
  strategy_type: StrategyType
  families: Record<FamilyId, FamilyConfig>
}

export interface RuleCondition {
  variable: ScoreVariable
  operator: RuleOperator
  threshold: WFOParam<number>
}

export interface EntryRule {
  id: string
  label: string            // "Entree 1", "Entree 2", etc.
  config_option: ConfigOption
  conditions: RuleCondition[]
  sizing_pct: WFOParam<number> // manual % or Kelly from WFO
}

export interface ExitRule {
  id: string
  label: string
  config_option: ConfigOption
  conditions: RuleCondition[]
  reduction_pct: WFOParam<number>
}

export type StopLossMode = "manual_pct" | "atr_based" | "wfo"
export type TakeProfitMode = "manual_pct" | "rr_target" | "wfo"

export interface RiskConfig {
  stop_loss_mode: StopLossMode
  stop_loss_manual_pct: number       // e.g. 0.02
  stop_loss_atr_multiplier: WFOParam<number>
  take_profit_mode: TakeProfitMode
  take_profit_manual_pct: number
  take_profit_rr_ratio: WFOParam<number>
  cooldown_bars: WFOParam<number>
  time_stop_bars: WFOParam<number>
  time_stop_enabled: boolean
  trailing_stop_enabled: boolean
  max_position_pct: number           // always manual, never WFO
  max_sector_pct: number             // always manual, never WFO
}

export interface StockStrategyConfig {
  signal_construction: SignalConstructionConfig
  entry_rules: EntryRule[]
  exit_rules: ExitRule[]
  risk: RiskConfig
}

// --- Handoff to backtest ---
export interface WFOParamEntry {
  stock: string
  section: "signal" | "entry" | "exit" | "risk"
  param_path: string
  scan_min: number
  scan_max: number
  scan_step: number
}

export interface BacktestHandoff {
  strategy_id: string
  strategy_name: string
  portfolio: { total_capital_mad: number; allocation_method: string; hrp_lookback_bars: number }
  stocks: Record<string, StockStrategyConfig>
  wfo_params: WFOParamEntry[]
  total_wfo_param_count: number
  detected_config_option: ConfigOption
  warnings: string[]
}
```

Export `DEFAULT_FAMILY_CONFIGS`, `DEFAULT_RISK_CONFIG`, `DEFAULT_ENTRY_RULE()` (factory), `DEFAULT_EXIT_RULE()` (factory) with sensible defaults:
- SMA: `{ enabled: true, indicator_type: "price_vs_sma", params: { window: { mode: "manual", value: 20 } } }`
- RSI: `{ enabled: true, indicator_type: "rsi_wilder", params: { period: { mode: "manual", value: 14 } } }`
- MACD: `{ enabled: true, indicator_type: "macd_histogram", params: { fast: { mode: "manual", value: 12 }, slow: { mode: "manual", value: 26 }, signal: { mode: "manual", value: 9 } } }`
- OBV: `{ enabled: true, indicator_type: "obv_deviation", params: { ema_period: { mode: "manual", value: 21 } } }`
- Default risk: `stop_loss_mode: "atr_based"`, `stop_loss_atr_multiplier: { mode: "manual", value: 1.5 }`, `take_profit_mode: "rr_target"`, `take_profit_rr_ratio: { mode: "manual", value: 1.5 }`, `cooldown_bars: { mode: "manual", value: 5 }`, `time_stop_bars: { mode: "manual", value: 30 }`, `max_position_pct: 20`, `max_sector_pct: 40`

**Verify:** `npx tsc --noEmit`

---

### Step 1.2: WFO param toggle reusable component

**Create** `quant-backtesting-frontend/components/strategy/wfo-param-input.tsx`

Props:
```ts
interface WFOParamInputProps {
  label: string
  param: WFOParam<number>
  onChange: (p: WFOParam<number>) => void
  min?: number; max?: number; step?: number
  unit?: string  // e.g. "bars", "%", "x"
}
```

Renders:
- Row with `<Label>` + a small `<Switch>` labeled "WFO" on the right
- **Manual mode:** single `<Input type="number">` for `param.value`
- **WFO mode:** three `<Input>`s in a row labeled "Min", "Max", "Pas" with muted background card
- When switching to WFO: auto-populate `scan_min = value * 0.5`, `scan_max = value * 2`, `scan_step = value * 0.1` (rounded)
- When switching back to manual: keep `value` as-is

Use existing shadcn `Switch`, `Input`, `Label` from `@/components/ui/`.

**Verify:** Component renders in isolation (import from another component).

---

## Phase 2 — Strategy Page: Per-Stock Tab Components

### Step 2.1: Signal Construction tab (replaces current Signal section)

**Create** `quant-backtesting-frontend/components/strategy/signal-construction-tab.tsx`

Props:
```ts
interface SignalConstructionTabProps {
  symbol: string
  horizon: string
  config: SignalConstructionConfig
  onChange: (config: SignalConstructionConfig) => void
}
```

Layout:
1. **Strategy Type** — `<Select>` at top with two options: "Suivi de tendance" / "Retour a la moyenne". Maps to `config.strategy_type`.
2. **Four family cards** in a 2-col grid, one per family (Tendance/SMA, Momentum/MACD, Oscillation/RSI, Volume/OBV):
   - `<Switch>` to enable/disable the family
   - Family name + description (French: "Tendance (SMA)", "Momentum (MACD)", "Oscillation (RSI)", "Volume (OBV)")
   - When enabled: show parameter inputs using `<WFOParamInput>` for each param in `config.families[familyId].params`
   - **Score preview badge:** Use `useIndicatorSeries(symbol, familyId, paramsAsPlain, true)` from existing `hooks/use-api.ts` — show `current_score` + `current_label` as a colored Badge. Debounce 500ms on param changes before re-fetching.

The existing `useIndicatorSeries` hook and `fetchIndicatorSeries` function already exist and return `{ current_score, current_label }` — reuse them directly.

French labels for families: `{ sma: "Tendance (SMA)", rsi: "Oscillation (RSI)", macd: "Momentum (MACD)", obv: "Volume (OBV)" }`.

**Verify:** Tab renders with 4 family cards, toggling WFO shows scan range inputs, score preview badge updates.

---

### Step 2.2: Entry Rules tab

**Create** `quant-backtesting-frontend/components/strategy/entry-rules-tab.tsx`

Props:
```ts
interface EntryRulesTabProps {
  rules: EntryRule[]
  onChange: (rules: EntryRule[]) => void
}
```

Layout:
1. Header row: title "Regles d'entree" + `<Button>` "Ajouter une regle" (calls `DEFAULT_ENTRY_RULE()` and appends)
2. For each rule, a `<Card>`:
   - Header: rule label (editable `<Input>`) + Config Option `<Select>` (A/B/C/D/E) + delete `<Button>` (trash icon)
   - Description text per option:
     - A: "Seuils manuels + taille manuelle"
     - B: "Seuils manuels + Kelly WFO"
     - C: "Seuils WFO + taille manuelle"
     - D: "Seuils WFO + Kelly WFO"
     - E: "Decouverte complete WFO"
   - **Conditions section:** For each condition row:
     - `<Select>` for variable (trend_score, momentum_score, oscillation_score, volume_score, consensus_score)
     - `<Select>` for operator (>, >=, <, <=)
     - `<WFOParamInput>` for threshold — **force WFO mode when config_option is C, D, or E**
     - Delete condition button
   - "Ajouter une condition" button
   - **Sizing section:**
     - When config_option A or C: plain `<Input>` for sizing_pct (manual %)
     - When config_option B, D, or E: `<WFOParamInput>` for sizing_pct with label "Kelly from WFO" and WFO forced on
3. If 0 rules: show empty state "Aucune regle d'entree. Ajoutez-en une pour commencer."

**Behavior when config_option changes:**
- Switching to C/D/E: force all condition thresholds to `mode: "wfo"` (auto-populate scan ranges from current value)
- Switching to A/B: force all condition thresholds to `mode: "manual"`
- Switching to B/D/E: force sizing_pct to `mode: "wfo"`
- Switching to A/C: force sizing_pct to `mode: "manual"`

**Verify:** Can add/remove rules, add/remove conditions, config option changes force correct WFO modes.

---

### Step 2.3: Exit Rules tab

**Create** `quant-backtesting-frontend/components/strategy/exit-rules-tab.tsx`

Nearly identical to entry-rules-tab but:
- Title: "Regles de sortie"
- Uses `ExitRule` type with `reduction_pct` instead of `sizing_pct`
- Label: "Reduction %" instead of "Taille %"
- Default label factory: "Sortie 1", "Sortie 2", etc.
- Empty state: "Aucune regle de sortie."

Props: `{ rules: ExitRule[], onChange: (rules: ExitRule[]) => void }`

**Verify:** Same as entry rules.

---

### Step 2.4: Risk tab (replace existing inline Risk card)

**Create** `quant-backtesting-frontend/components/strategy/risk-tab.tsx`

Props:
```ts
interface RiskTabProps {
  symbol: string
  horizon: string
  config: RiskConfig
  onChange: (config: RiskConfig) => void
}
```

Layout:
1. **Stop Loss section:**
   - `<Select>` for mode: "Manuel (%)" / "Base ATR" / "WFO"
   - If `manual_pct`: `<Input>` for percentage
   - If `atr_based`: `<WFOParamInput>` for ATR multiplier
   - If `wfo`: `<WFOParamInput>` with scan range (forced WFO mode)

2. **Take Profit section:**
   - `<Select>` for mode: "Manuel (%)" / "Ratio R:R" / "WFO"
   - If `manual_pct`: `<Input>` for percentage
   - If `rr_target`: `<WFOParamInput>` for R:R ratio
   - If `wfo`: `<WFOParamInput>` with scan range

3. **Cooldown** — `<WFOParamInput>` for `cooldown_bars` (unit: "bars")

4. **Time stop** — `<Switch>` to enable + `<WFOParamInput>` for `time_stop_bars` (unit: "bars")

5. **Trailing stop** — `<Switch>` toggle (placeholder, stored for future)

6. **Position limits** (always manual, no WFO):
   - `<Input>` for `max_position_pct` (label: "Position max (%)")
   - `<Input>` for `max_sector_pct` (label: "Secteur max (%)")

7. **Risk Preview card** (bottom):
   - Use existing `useExecution` hook (already fetches stop_loss, target_1, rr_ratio from `/strategy/plan/execution`)
   - Display: Stop price, Target price, R:R ratio, Cooldown bars as `<MetricTile>` badges

**Verify:** Mode switching shows correct inputs, WFO toggles work, preview updates.

---

### Step 2.5: Review tab

**Create** `quant-backtesting-frontend/components/strategy/review-tab.tsx`

Props:
```ts
interface ReviewTabProps {
  strategyId: string | null
  strategyName: string
  horizon: string
  stocks: Record<string, StockStrategyConfig>
  basket: string[]
  onOpenBacktest: (handoff: BacktestHandoff) => void
}
```

Layout:
1. **Per-stock readiness table (doc 09 — Ready/Not-Ready Checklist):**
   - Columns: Symbole, Type, Signal, Entrees, Sorties, Risque, Params WFO, Statut
   - For each stock in basket, compute locally:
     - `has_strategy_type`: strategy_type is set (BLOCKING)
     - `has_signal`: at least one family enabled AND all families referenced in rules are configured (BLOCKING)
     - `has_entry_rules`: entry_rules.length > 0 (BLOCKING)
     - `has_exit_or_risk`: exit_rules.length > 0 OR risk has stop_loss configured (BLOCKING)
     - `has_stop_loss`: stop_loss is configured (BLOCKING)
     - `sufficient_bars`: stock has enough data bars for the indicator lookbacks (BLOCKING — check against bar count)
     - `wfo_param_count`: count all params where `mode === "wfo"` across signal + entry + exit + risk (WARNING only)
   - Status badge: green checkmark if ALL blocking checks pass, orange warning if blocking passes but WFO warnings exist, red X if any blocking check fails

2. **WFO parameter summary card:**
   - `total_wfo_param_count` = sum across all stocks
   - Severity badge:
     - 0: "Option A — aucun parametre WFO" (blue)
     - 1-10: "OK" (green)
     - 11-15: "Attention — risque de suroptimisation" (orange)
     - >15: "Danger — trop de parametres" (red)
   - Pardo DF hint: "Regle de Pardo : IS >= 10 x lookback max"

3. **Detected config option:** Compute from WFO params pattern and display as badge (A/B/C/D/E)

4. **"Ouvrir dans Backtest" button (doc 09 — Save Before Backtest):**
   - Disabled if:
     - Strategy is not saved (status !== "saved") — show "Sauvegardez d'abord" tooltip
     - Any stock fails a BLOCKING check
     - No stocks in basket
   - On click: build `BacktestHandoff` locally (extract all WFO params into flat manifest), then call `onOpenBacktest(handoff)` which navigates to `/backtest?strategyId={id}&mode=wfo`
   - Include `warnings[]` array in handoff for non-blocking issues (WFO param count, sizing placeholders, etc.)

5. **"User chooses vs WFO optimizes" table** — prominently displayed per doc 09:
   | L'utilisateur choisit (Structure) | WFO optimise (Parametres) |
   Strategy type, families to use, rule structure, sizing mode | Indicator params, thresholds, sizing values, ATR multiplier (when flagged)

**Verify:** Table shows all basket stocks, WFO count computes correctly, button navigates.

---

## Phase 3 — Strategy Page: Integration

### Step 3.1: Modify `app/strategy/page.tsx`

**File:** `quant-backtesting-frontend/app/strategy/page.tsx` (1323 lines)

Changes:

1. **Add imports** (top of file):
   ```ts
   import { SignalConstructionTab } from "@/components/strategy/signal-construction-tab"
   import { EntryRulesTab } from "@/components/strategy/entry-rules-tab"
   import { ExitRulesTab } from "@/components/strategy/exit-rules-tab"
   import { RiskTab } from "@/components/strategy/risk-tab"
   import { ReviewTab } from "@/components/strategy/review-tab"
   import type { StockStrategyConfig, SignalConstructionConfig, EntryRule, ExitRule, RiskConfig } from "@/lib/strategy-types"
   import { DEFAULT_FAMILY_CONFIGS, DEFAULT_RISK_CONFIG, DEFAULT_ENTRY_RULE, DEFAULT_EXIT_RULE } from "@/lib/strategy-types"
   ```

2. **Extend `StrategyConfig` interface** (line 109): Add a `stocks` field:
   ```ts
   interface StrategyConfig {
     capital: { ... }        // keep
     universe: { ... }       // keep
     allocation: { ... }     // keep
     signal: { ... }         // keep (shared signal families toggle — still used for consensus)
     bet_sizing: BetSizingConfig  // keep for backward compat
     risk: { ... }           // keep for backward compat
     stocks: Record<string, StockStrategyConfig>  // NEW
   }
   ```

3. **Extend `DEFAULT_CONFIG`** (line 183): Add `stocks: {}`.

4. **Extend `normalizeStrategyConfig`** (around line 260): After existing normalization, add:
   ```ts
   // Normalize per-stock configs
   if (!cfg.stocks) cfg.stocks = {}
   for (const sym of cfg.universe?.basket ?? []) {
     if (!cfg.stocks[sym]) {
       cfg.stocks[sym] = {
         signal_construction: {
           strategy_type: "trend_following",
           families: structuredClone(DEFAULT_FAMILY_CONFIGS),
         },
         entry_rules: [],
         exit_rules: [],
         risk: structuredClone(DEFAULT_RISK_CONFIG),
       }
     }
   }
   ```

5. **Add `updateStockConfig` helper** inside `StrategyPageContent` (after line 858):
   ```ts
   const updateStockConfig = useCallback(
     (symbol: string, section: keyof StockStrategyConfig, value: unknown) => {
       setConfig((prev) => ({
         ...prev,
         stocks: {
           ...prev.stocks,
           [symbol]: { ...prev.stocks[symbol], [section]: value },
         },
       }))
       if (status === "saved") setStatus("modified")
     },
     [status],
   )
   ```

6. **Replace `StockStrategyTab` body** (lines 550-844): Keep the Allocation card as-is. Replace the Signal/Bet Sizing/Risk cards with a `<Tabs>` component:
   ```tsx
   <Tabs defaultValue="signal" className="mt-4">
     <TabsList>
       <TabsTrigger value="allocation">Allocation</TabsTrigger>
       <TabsTrigger value="signal">Signal</TabsTrigger>
       <TabsTrigger value="entry">Entrees</TabsTrigger>
       <TabsTrigger value="exit">Sorties</TabsTrigger>
       <TabsTrigger value="risk">Risque</TabsTrigger>
       <TabsTrigger value="review">Revue</TabsTrigger>
     </TabsList>
     <TabsContent value="allocation">
       {/* existing Allocation card JSX */}
     </TabsContent>
     <TabsContent value="signal">
       <SignalConstructionTab
         symbol={symbol}
         horizon={horizon}
         config={config.stocks[symbol]?.signal_construction ?? { strategy_type: "trend_following", families: DEFAULT_FAMILY_CONFIGS }}
         onChange={(sc) => updateStockConfig(symbol, "signal_construction", sc)}
       />
     </TabsContent>
     <TabsContent value="entry">
       <EntryRulesTab
         rules={config.stocks[symbol]?.entry_rules ?? []}
         onChange={(rules) => updateStockConfig(symbol, "entry_rules", rules)}
       />
     </TabsContent>
     <TabsContent value="exit">
       <ExitRulesTab
         rules={config.stocks[symbol]?.exit_rules ?? []}
         onChange={(rules) => updateStockConfig(symbol, "exit_rules", rules)}
       />
     </TabsContent>
     <TabsContent value="risk">
       <RiskTab
         symbol={symbol}
         horizon={horizon}
         config={config.stocks[symbol]?.risk ?? DEFAULT_RISK_CONFIG}
         onChange={(risk) => updateStockConfig(symbol, "risk", risk)}
       />
     </TabsContent>
     <TabsContent value="review">
       <ReviewTab
         strategyId={activeId}
         strategyName={name}
         horizon={horizon}
         stocks={config.stocks}
         basket={config.universe.basket}
         onOpenBacktest={(handoff) => {
           window.location.href = `/backtest?strategyId=${activeId}&mode=wfo`
         }}
       />
     </TabsContent>
   </Tabs>
   ```

7. **Ensure basket changes sync stocks:** When `config.universe.basket` changes (stocks added/removed), auto-create/remove entries in `config.stocks`. This already partially happens in `normalizeStrategyConfig` — make sure it also fires on basket changes in the UI.

8. **Keep existing Signal consensus bar** in a condensed form above the tabs (the `SignalScoreBar` + `SignalZoneChart` are useful context). Or move them inside the Signal tab. User preference: move them into the Signal tab as a "Consensus preview" section above the family cards.

**Verify:** Page loads, 6 sub-tabs render per stock, saving persists `config.stocks` in `config_json`, reloading restores state.

---

## Phase 4 — Backend: New Strategy Endpoints

### Step 4.1: Extend strategy schemas

**File:** `services/api/app/schemas/strategy.py` (371 lines) — append after `SizingOut`:

```python
# --- Review / Readiness ---
class ReviewRequest(BaseModel):
    config_json: dict[str, Any] = Field(default_factory=dict)
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")

class ReviewStockReadiness(BaseModel):
    symbol: str
    has_signal: bool = False
    has_entry_rules: bool = False
    has_exit_rules: bool = False
    has_risk: bool = False
    wfo_param_count: int = 0
    warnings: list[str] = []

class ReviewOut(BaseModel):
    total_wfo_param_count: int = 0
    wfo_param_severity: str = "ok"
    pardo_df_ok: bool = True
    pardo_df_message: str = ""
    stocks: list[ReviewStockReadiness] = []
    global_warnings: list[str] = []

# --- Handoff ---
class HandoffOut(BaseModel):
    strategy_id: str
    strategy_name: str
    portfolio: dict[str, Any] = Field(default_factory=dict)
    stocks: dict[str, Any] = Field(default_factory=dict)
    wfo_params: list[dict[str, Any]] = Field(default_factory=list)
    total_wfo_param_count: int = 0
    detected_config_option: str = "A"
    warnings: list[str] = Field(default_factory=list)
```

### Step 4.2: Add review + handoff endpoints

**File:** `services/api/app/routers/strategy.py` (797 lines) — append after `archive_strategy`:

**POST `/strategy/plan/review`**: Takes `ReviewRequest`. Iterate `config_json.get("stocks", {})`, for each stock count WFO params (any dict with `"mode": "wfo"`), check has_signal/has_entry/has_exit/has_risk. Return `ReviewOut` with severity thresholds (1-10 ok, 11-15 warning, >15 danger).

**POST `/strategy/plan/strategies/{strategy_id}/handoff`**: Load strategy from DB. Extract `config_json.stocks`, flatten all WFO params into a list of `{stock, section, param_path, scan_min, scan_max, scan_step}`. Detect config option: 0 WFO params = A, only sizing WFO = B, thresholds WFO but not sizing = C, both = D, entry/exit count WFO = E. Return `HandoffOut`.

Import new schemas at the top of strategy.py:
```python
from ..schemas.strategy import ReviewRequest, ReviewOut, ReviewStockReadiness, HandoffOut
```

Helper function `_count_wfo_params(obj: dict) -> int` that recursively walks a dict and counts entries where `obj.get("mode") == "wfo"`.

**Verify:** `curl -X POST localhost:8000/strategy/plan/review` with a config_json returns correct counts. `curl -X POST localhost:8000/strategy/plan/strategies/{id}/handoff` returns handoff payload.

---

## Phase 5 — Backtest: WFO Engine Core

### Step 5.1: Create backtest package

**Create** `core/quant_core/backtest/__init__.py` (empty `"""WFO backtest engine."""`)

### Step 5.2: PROM computation (Pardo Ch.9 p.239)

**Create** `core/quant_core/backtest/prom.py`

Implement `compute_prom(trades: list[dict], capital: float) -> float`:
```
PROM = {[AW x (#WT - sqrt(#WT))] - [AL x (#LT + sqrt(#LT))]} / Capital
```
Where AW = average win (currency), AL = average loss (currency, positive), #WT/#LT = win/loss counts.

**Critical edge cases from doc 03:**
- 0 trades -> return `float('-inf')` (NOT 0.0 — a parameter generating no trades is the worst possible)
- 1 winning trade -> PROM = 0.0 (since 1 - sqrt(1) = 0, the single lucky trade carries zero information)
- 1 losing trade -> PROM = -2*AL/capital (doubly penalized)
- All wins, no losses -> adj_losses = 0, PROM = adjusted wins / capital
- All losses, no wins -> adj_wins = 0, PROM = -adjusted losses / capital

**Trades must include transaction costs (net P&L, not gross).** Cost is applied upstream before calling PROM.

**Capital parameter:** For equities, use `account_equity * allocation_weight_for_stock` (Pardo uses futures margin; we adapt for equities).

### Step 5.3: Neighbor averaging (Pardo Ch.10 p.235)

**Create** `core/quant_core/backtest/neighbor_avg.py`

**DO NOT use `scipy.ndimage.uniform_filter`** — the docs specify axis-wise independent smoothing, not isotropic smoothing.

**1D (SMA, OBV) — `neighbor_average_1d(prom_dict: dict[int, float], k=1) -> dict[int, float]`:**
For each param value p, smoothed_PROM(p) = mean of p and its k neighbors in the sorted param list. Boundary handling: at edges, use only available neighbors (2 values at boundaries instead of 3).

**2D (RSI: period x threshold_set) — `neighbor_average_2d(prom_grid, periods, thresholds, k=1)`:**
Per doc 04: smooth along each axis independently, then combine:
1. For each threshold_set, smooth across periods (1D)
2. For each period, smooth across threshold_sets (1D)
3. Combined = mean of both smoothings

**3D (MACD: fast x slow x signal) — `neighbor_average_3d(prom_cube, fast_vals, slow_vals, signal_vals, k=1)`:**
Same principle along three axes. Combined = mean of three axis-wise smoothings.

**Selection: use highest smoothed_PROM, not highest raw PROM.** This shifts selection from isolated spikes to plateaus.

### Step 5.4: Optimization profile checks (Pardo Ch.10 p.260-268)

**Create** `core/quant_core/backtest/profile.py`

Three checks. All three must pass for an IS window's winner to be used.

**Check 1 — Statistical Significance: `check_significance(all_proms, threshold=20.0) -> ProfileCheck`:**
- Count params where PROM > 0
- `< 5%` profitable: catastrophic failure (strong reject)
- `< 20%` profitable: insufficient (soft reject)
- `>= 20%`: pass

**Check 2 — Distribution: `check_distribution(all_proms, winner_smoothed_prom) -> ProfileCheck`:**
- Compute mean and std of PROFITABLE proms only (PROM > 0)
- Winner's smoothed PROM must be <= mean_profitable + 1 * std_profitable
- Rejects extreme outliers (likely statistical artifacts)

**Check 3 — Shape/Smoothness: `check_shape(prom_values, winner_params, k=2) -> ProfileCheck`:**
- Get k=2 neighborhood of winner
- CV = std(neighbor_proms) / abs(mean(neighbor_proms))
- CV > 1.5: soft warning (not a hard reject — neighbor-averaging already handles this)

**When profile fails:** Flag window, do NOT use its winner in OOS. Window still counts toward total (affects robustness ratio — a failed profile window is equivalent to a non-profitable OOS window).

### Step 5.5: Kelly sizing (Kelly 1956, Thorp 2006, doc 07)

**Create** `core/quant_core/backtest/kelly.py`

**Input:** Concatenated OOS trades from winning WFO configuration (NOT IS trades — doc 07 is explicit).

Implement two functions:

**`compute_trade_stats(trades) -> TradeStats`:**
- wins = trades where net_pnl > 0
- losses = trades where net_pnl <= 0
- win_rate W = n_wins / n_total
- avg_win, avg_loss (absolute value)
- wl_ratio R = avg_win / avg_loss (if avg_loss > 0, else inf)

**`compute_kelly(stats: TradeStats) -> KellyResult`:**
- `kelly = W - (1-W)/R`
- If kelly <= 0: return 0.0 with reason "Negative Kelly — no edge"
- If R <= 0 or W <= 0: return 0.0 with reason "No positive expectancy"
- Return `{ kelly_fraction, half_kelly (= kelly/2), win_rate, wl_ratio, n_trades, warning }`
- **Warning when n_trades < 30** (doc 07): "Only N OOS trades. Kelly estimate has high uncertainty. Consider using half-Kelly."
- Half-Kelly sacrifices ~25% of growth rate while substantially reducing variance (doc 07).

### Step 5.6: Statistical validation (doc 08)

**Create** `core/quant_core/backtest/statistical.py`

**1. Monte Carlo Permutation Test — `monte_carlo_test(oos_trade_returns: np.ndarray, n_simulations=10000, metric="total_return") -> dict`:**
- **Shuffle TRADE RETURNS (not daily returns)** — doc 08 is explicit: permute the net returns of individual OOS trades
- For each shuffle: recompute equity curve via `np.cumprod(1 + shuffled_returns)`
- Actual metric = total return of real trade sequence
- Count n_exceed = shuffles where sim_metric >= actual_metric
- **p-value = (n_exceed + 1) / (n_simulations + 1)** — the +1 correction avoids p=0 (doc 08)
- Store all 10,000 simulated equity curves for fan chart visualization
- Compute percentile bands: p5, p25, p50, p75, p95 of simulated final equity
- Return `{ p_value, significant (p < 0.05), actual_metric, actual_percentile, simulated_curves, percentile_bands }`

**2. Deflated Sharpe Ratio — `deflated_sharpe_ratio(oos_returns: np.ndarray, n_variants_tested: int, risk_free_rate=0.0) -> dict`:**
Per Bailey & Lopez de Prado (2014):
```
SR_observed = mean(oos_returns) / std(oos_returns)
gamma_3 = skewness(oos_returns)        # scipy.stats.skew
gamma_4 = kurtosis(oos_returns, fisher=False)  # raw kurtosis, NOT excess
T = len(oos_returns)

sigma_SR = sqrt((1 - gamma_3 * SR + (gamma_4 - 1)/4 * SR^2) / T)
SR_benchmark = sqrt(2 * ln(n_variants_tested)) * sigma_SR
DSR = (SR_observed - SR_benchmark) / sigma_SR
p_value = 1 - norm.cdf(DSR)
```
- Input `n_variants_tested` comes from WFO diagnostics (total parameter combinations tested)
- Return `{ observed_sharpe, benchmark_sharpe, dsr_statistic, p_value, significant (p < 0.05), skewness, kurtosis, n_trades, n_variants }`

**Combined verdict:** Strategy must pass ALL THREE (WFE >= 50%, MC p < 0.05, DSR p < 0.05) to be statistically validated.

### Step 5.7: WFO engine orchestrator (doc 02 — the core pipeline)

**Create** `core/quant_core/backtest/wfo.py`

Dataclasses: `WFOConfig`, `WindowResult`, `ConfigResult`, `WFOResult`

**WFOConfig fields:**
- `is_oos_ratios: list[float]` — e.g. [0.25, 0.30, 0.35] (MULTIPLE ratios to test, NOT a single value)
- `max_lookback: int` — longest indicator lookback among WFO-flagged params
- `param_grid: dict[str, list]` — search space per parameter
- `capital: float`
- `test_period_start_idx: int | None` — index where test period begins
- `min_walk_forwards: int = 5` — warn if fewer

**Main function `run_wfo(bars, volume, config, simulate_fn, progress_cb=None) -> WFOResult`:**

```python
# Step 1: Generate all param combos (30-50 candidates per dimension per Pardo Ch.10 p.252)
all_combos = enumerate_param_combinations(config.param_grid)

# Step 2: Enumerate feasible (IS, OOS) configurations for EACH ratio
feasible_configs = []
for ratio in config.is_oos_ratios:
    is_bars = max(10 * config.max_lookback, MIN_IS_BARS)
    oos_bars = int(is_bars * ratio)
    step = oos_bars  # standard WFA: step = OOS length (Pardo Ch.11)
    t_available = len(bars) if not config.test_period_start_idx else config.test_period_start_idx
    n_wf = (t_available - is_bars) // oos_bars
    if n_wf >= 2:
        feasible_configs.append((is_bars, oos_bars, step, n_wf, ratio))

# Step 3: For EACH feasible config: rolling walk-forward
for is_bars, oos_bars, step, n_wf, ratio in feasible_configs:
    windows = []
    for w in range(n_wf):
        is_start = w * oos_bars
        is_end = is_start + is_bars
        oos_start = is_end
        oos_end = oos_start + oos_bars

        # IS: run all combos, compute PROM for each
        prom_map = {}
        for combo in all_combos:
            trades = simulate_fn(bars[is_start:is_end], volume[is_start:is_end], combo, capital)
            prom_map[combo_key] = compute_prom(trades, capital)

        # Neighbor-average (dispatch by family dimensionality)
        smoothed = neighbor_average(prom_map, family_dims)

        # Optimization profile check (3 checks)
        profile = check_optimization_profile(prom_map, smoothed, winner_key)
        if not profile.passes:
            windows.append(WindowResult(flagged=True, ...))
            continue  # skip this window's winner, but it STILL COUNTS

        # IS winner = argmax(smoothed_PROM)
        winner_key = max(smoothed, key=smoothed.get)

        # OOS: run winner on unseen data
        oos_trades = simulate_fn(bars[oos_start:oos_end], volume[oos_start:oos_end], winner_params, capital)
        oos_return = compute_total_return(oos_trades)

        windows.append(WindowResult(
            is_prom=prom_map[winner_key],
            is_smoothed_prom=smoothed[winner_key],
            is_winner_return=...,  # return of winner on IS data
            oos_return=oos_return,
            oos_trades=oos_trades,
            oos_profitable=(oos_return > 0),
            is_winner_params=winner_params,
            profile=profile,
        ))

    # Step 4: Compute WFE (compounding formula from doc 05)
    is_total = 1.0; is_total_bars = 0
    oos_total = 1.0; oos_total_bars = 0
    for w in windows:
        is_total *= (1 + w.is_winner_return)
        is_total_bars += is_bars
        oos_total *= (1 + w.oos_return)
        oos_total_bars += oos_bars
    is_ann = is_total ** (252 / is_total_bars) - 1
    oos_ann = oos_total ** (252 / oos_total_bars) - 1
    wfe = oos_ann / is_ann if is_ann > 0 else 0.0

    # Step 5: Robustness checks
    robustness_ratio = sum(w.oos_profitable for w in windows) / len(windows)
    # Check single-window dominance (doc 05): max single window contribution < 50%

    config_results.append(ConfigResult(is_bars, oos_bars, ratio, n_wf, wfe, robustness_ratio, windows))

# Step 4 (global): Select config with best WFE >= 50%
viable = [c for c in config_results if c.wfe >= 0.50]
if not viable:
    return WFOResult(viable=False, best_wfe=max(c.wfe for c in config_results), ...)

best = max(viable, key=lambda c: c.wfe)

# Step 6: Final params = last IS window's winner (most recent calibration)
final_params = best.windows[-1].is_winner_params

# Step 7: Kelly from concatenated OOS trades
all_oos_trades = concat([w.oos_trades for w in best.windows if not w.flagged])
kelly = compute_kelly(all_oos_trades)

# Step 8: Statistical validation
mc = monte_carlo_test(all_oos_trade_returns, n_simulations=10000)
dsr = deflated_sharpe_ratio(all_oos_trade_returns, n_variants_tested=len(all_combos))

# Step 9: Test period (if configured)
if config.test_period_start_idx:
    test_result = simulate_fn(bars[test_start:], volume[test_start:], final_params, capital)
```

The `simulate_fn` signature: `(close_window, volume_window, params, capital) -> list[Trade]` where each Trade has `net_pnl` and `net_return`. The API layer provides this callback by wrapping existing `compute_signal_array` from `oos_eval.py` + position logic.

**Verify:** Unit test with synthetic trending data + SMA crossover strategy produces valid WFOResult with WFE > 0.

---

## Phase 6 — Backtest: API + Frontend

### Step 6.1: WFO backend schemas (must match doc 10 API contracts exactly)

**Create** `services/api/app/schemas/backtest_wfo.py`

**Request — matches doc 10:**
```python
class WFOSubmitRequest(BaseModel):
    strategy_id: str
    wfo_config: WFOConfigPayload

class WFOConfigPayload(BaseModel):
    start_date: str
    end_date: str
    test_period_start: str | None = None  # auto-computed if omitted
    horizon: str = Field(default="medium", pattern=r"^(short|medium|long)$")
    is_oos_ratios: list[float] = Field(default=[0.25, 0.30, 0.35])  # ARRAY, not single value
    cost_model: CostModelPayload = Field(default_factory=CostModelPayload)
    volume_gate: int = 10000
    cooldown_bars: int = 3

class CostModelPayload(BaseModel):
    brokerage_bps: float = 5.0
    commission_bps: float = 3.0
    slippage_bps: float = 2.0
    tva_rate: float = 0.10
```

**Response — matches doc 10 schema:**
```python
class WFOResultOut(BaseModel):
    viable: bool                          # TOP-LEVEL viable flag
    strategy_id: str
    horizon: str

    # Only present when viable=True:
    winning_config: WinningConfigOut | None = None
    windows: list[WFOWindowOut] = []
    final_params: dict[str, Any] = {}     # from last IS window
    statistical_validation: StatisticalValidationOut | None = None
    sizing: WFOKellyOut | None = None
    test_period: WFOTestPeriodOut | None = None
    all_configs_tested: list[ConfigTestedOut] = []
    diagnostics: WFODiagnosticsOut = Field(default_factory=WFODiagnosticsOut)

    # Only present when viable=False:
    best_wfe: float | None = None
    best_config: WinningConfigOut | None = None

class WinningConfigOut(BaseModel):
    is_bars: int
    oos_bars: int
    is_oos_ratio: float
    n_walk_forwards: int
    wfe: float
    wfe_threshold: float = 0.50
    robustness_ratio: float

class WFOWindowOut(BaseModel):
    index: int
    is_start_date: str; is_end_date: str
    oos_start_date: str; oos_end_date: str
    is_prom: float; is_smoothed_prom: float
    is_winner_params: dict[str, Any]
    oos_return: float; oos_profitable: bool; oos_n_trades: int
    optimization_profile: OptProfileOut

class OptProfileOut(BaseModel):
    pct_profitable: float
    distribution_check: bool
    shape_check: bool
    passes: bool

class StatisticalValidationOut(BaseModel):
    monte_carlo: MonteCarloOut
    deflated_sharpe: DSROut
    all_passed: bool

class MonteCarloOut(BaseModel):
    p_value: float; n_simulations: int
    actual_final_equity: float; actual_percentile: float
    percentile_bands: dict[str, float]  # p5, p25, p50, p75, p95
    significant: bool

class DSROut(BaseModel):
    observed_sharpe: float; benchmark_sharpe: float
    dsr_statistic: float; p_value: float
    skewness: float; kurtosis: float
    n_variants_tested: int; significant: bool

class WFOKellyOut(BaseModel):
    n_oos_trades: int; win_rate: float
    avg_win: float; avg_loss: float; wl_ratio: float
    kelly_fraction: float; half_kelly_fraction: float

class WFOTestPeriodOut(BaseModel):
    start_date: str; end_date: str; n_bars: int
    total_return: float; cagr: float; sharpe: float
    max_drawdown: float; calmar: float
    n_trades: int; win_rate: float; profit_factor: float
    equity_curve: list[list] = []  # [[dates], [values]]
    trades: list[dict] = []

class ConfigTestedOut(BaseModel):
    is_bars: int; oos_bars: int; ratio: float
    n_walk_forwards: int; wfe: float

class WFODiagnosticsOut(BaseModel):
    total_variants_tested: int = 0
    total_is_evaluations: int = 0
    computation_time_seconds: float = 0.0
    failed_profile_windows: list[int] = []
    recommendation: str = ""
```

**Progress:**
```python
class WFOProgressOut(BaseModel):
    phase: str          # "config_1_of_3"
    window: str         # "5_of_10"
    pct: float
    elapsed_s: float
```

### Step 6.2: WFO backend router

**Create** `services/api/app/routers/backtest_wfo.py`

Router prefix: `/backtest/wfo`, tags: `["backtest-wfo"]`

Endpoints:
- `POST ""` (201): Load strategy + handoff, build simulate_fn callback, call `run_wfo()`, store result in memory dict (`_WFO_RUNS`), return run_id
- `GET "/{run_id}"`: Return stored `WFOResultOut`
- `GET "/{run_id}/window/{idx}"`: Return specific window detail including `optimization_landscape` (per doc 10: param_values, raw_proms, smoothed_proms, winner_index, pct_profitable) and `oos_detail` (equity_curve, trades, metrics)
- `GET "/{run_id}/progress"`: Return `WFOProgressOut` (JSON for MVP, SSE later)

**Register** in `services/api/app/main.py`:
```python
from .routers import backtest_wfo
app.include_router(backtest_wfo.router)
```

### Step 6.3: Frontend WFO API layer

**File:** `quant-backtesting-frontend/lib/api.ts` — append:

Zod schemas + fetch functions:
- `WFOResultSchema` + `fetchWFOResult(runId)`
- `WFOSubmitResponseSchema` + `submitWFO(body)`
- `WFOWindowSchema` + `fetchWFOWindow(runId, idx)`
- `WFOProgressSchema` + `fetchWFOProgress(runId)`

**File:** `quant-backtesting-frontend/hooks/use-api.ts` — append:
- `useWFOResult(runId)` — SWR with 5s refreshInterval when status !== "completed"
- `useWFOProgress(runId)` — SWR with 2s refreshInterval

### Step 6.4: Backtest WFO components

**Create** `quant-backtesting-frontend/components/backtest/` directory with:

1. **`wfo-config-card.tsx`** — IS/OOS ratios multi-select (checkboxes for 0.25, 0.30, 0.35 per doc 10 — default all three checked), test period start date picker, MC shuffles input, horizon display (read from strategy), "Lancer WFO" button
2. **`wfo-results-table.tsx`** — Table: Fenetre, Periode IS, Periode OOS, Meilleurs Params, PROM IS, Rendement OOS, Profil. Color-coded rows.
3. **`wfo-param-evolution.tsx`** — Line chart (use Recharts or lightweight-charts) showing how winner params change across windows
4. **`wfo-monte-carlo.tsx`** — p-value badge + equity fan chart (5th/50th/95th percentiles) + DSR display
5. **`wfo-kelly-card.tsx`** — OOS trade stats table (n_trades, win_rate, avg_win, avg_loss, W/L ratio) + Kelly fraction + half-Kelly display + recommended position size. Include "Appliquer le sizing a la strategie" button (doc 07 State 3: writes computed win_rate, wl_ratio, kelly_fraction back to strategy config, sets status to "modified"). Warning badge when n_trades < 30.
6. **`wfo-test-period.tsx`** — Equity curve + metrics summary + trade ledger for held-out period
7. **`wfo-progress-bar.tsx`** — Progress bar with window count, percentage, status message
8. **`wfo-verdict-card.tsx`** — Final verdict panel matching doc 08 layout:
   - Three pass/fail rows: WFE (>= 50%), Monte Carlo p-value (< 0.05), DSR p-value (< 0.05)
   - Each row: metric name, value, pass/fail badge
   - Bottom: verdict = "STRATEGIE VALIDEE" (green) if ALL THREE pass, "STRATEGIE NON VALIDEE" (red) if any fails
   - Explanation per metric per doc 08: WFE catches parameter overfitting, MC catches random performance, DSR catches multiple-testing inflation
   - When not viable (no WFE >= 50%): show "NON VIABLE" with best WFE achieved + recommendation from diagnostics

### Step 6.5: Backtest page integration

**File:** `quant-backtesting-frontend/app/backtest/page.tsx` (717 lines)

Changes:

1. **Add imports** for WFO components and hooks.

2. **Add state** in `BacktestContent`:
   ```ts
   const [wfoMode, setWfoMode] = useState(false)
   const [wfoRunId, setWfoRunId] = useState<string | null>(null)
   const [isOosRatios, setIsOosRatios] = useState([0.25, 0.30, 0.35]) // multiple ratios per doc 10
   const [testPeriodStart, setTestPeriodStart] = useState<string | null>(null)
   const [mcShuffles, setMcShuffles] = useState(10000)
   ```

3. **Detect WFO mode from URL:** `searchParams.get("mode") === "wfo"` sets `wfoMode = true`.

4. **Add mode toggle** in Setup card header: Switch between "Backtest direct" and "Analyse WFO".

5. **Conditionally render WFO sections** when `wfoMode`:
   ```tsx
   {wfoMode && <WFOConfigCard isOosRatio={isOosRatio} ... onSubmit={handleSubmitWFO} />}
   {wfoRunId && wfoResult && (
     <>
       <WFOVerdictCard wfe={wfoResult.wfe} mc={wfoResult.monte_carlo} dsr={wfoResult.dsr} />
       <WFOResultsTable windows={wfoResult.windows} />
       <WFOParamEvolution params={wfoResult.param_evolution} />
       <WFOMonteCarloCard mc={wfoResult.monte_carlo} dsr={wfoResult.dsr} />
       <WFOKellyCard kelly={wfoResult.kelly} />
       {wfoResult.test_period && <WFOTestPeriod data={wfoResult.test_period} />}
     </>
   )}
   {wfoRunId && !wfoResult && <WFOProgressBar runId={wfoRunId} />}
   ```

6. **Keep existing direct backtest** sections when `!wfoMode` (no changes to current behavior).

**Verify:** Backtest page loads in both modes, WFO mode shows config + submits + displays results.

---

## Phase 7 — Unit Tests

### Step 7.1: PROM tests

**Create** `core/tests/test_prom.py`:
- Test known hand-computed PROM values
- Test edge cases: 0 trades, 1 trade, all wins, all losses
- Test that 1 winning trade -> PROM = 0

### Step 7.2: Neighbor averaging tests

**Create** `core/tests/test_neighbor_avg.py`:
- Test 1D smoothing reduces variance
- Test 2D/3D smoothing produces smooth surfaces
- Test boundary handling (edge values)

### Step 7.3: Kelly tests

**Create** `core/tests/test_kelly.py`:
- Test doc example: W=56.5%, R=1.524 -> kelly=0.280
- Test negative Kelly clamps to 0
- Test 0 trades returns 0

### Step 7.4: Profile tests

**Create** `core/tests/test_profile.py`:
- Test significance check thresholds
- Test distribution check (within 1 sigma)
- Test shape CV check

---

## Verification Plan

After all phases:

1. **TypeScript:** `cd quant-backtesting-frontend && npx tsc --noEmit` — 0 errors
2. **Python imports:** `cd services/api && python -c "from app.schemas.backtest_wfo import WFOResultOut; from core.quant_core.backtest.wfo import run_wfo; print('OK')"`
3. **Unit tests:** `cd core && python -m pytest tests/test_prom.py tests/test_neighbor_avg.py tests/test_kelly.py tests/test_profile.py -v`
4. **Strategy page:** Load page, select stocks, navigate all 6 sub-tabs, toggle WFO on params, save strategy, reload, verify state persists
5. **Backtest page:** Load with `?mode=wfo`, configure, submit WFO run, verify results display
6. **Handoff flow:** Strategy Review tab -> "Ouvrir dans Backtest" -> lands on backtest page in WFO mode with strategy pre-selected

---

## File Summary

| Action | File | Lines (est.) |
|--------|------|-------------|
| CREATE | `quant-backtesting-frontend/lib/strategy-types.ts` | ~150 |
| CREATE | `quant-backtesting-frontend/components/strategy/wfo-param-input.tsx` | ~80 |
| CREATE | `quant-backtesting-frontend/components/strategy/signal-construction-tab.tsx` | ~250 |
| CREATE | `quant-backtesting-frontend/components/strategy/entry-rules-tab.tsx` | ~300 |
| CREATE | `quant-backtesting-frontend/components/strategy/exit-rules-tab.tsx` | ~250 |
| CREATE | `quant-backtesting-frontend/components/strategy/risk-tab.tsx` | ~250 |
| CREATE | `quant-backtesting-frontend/components/strategy/review-tab.tsx` | ~200 |
| MODIFY | `quant-backtesting-frontend/app/strategy/page.tsx` | ~200 changed |
| MODIFY | `quant-backtesting-frontend/lib/api.ts` | ~120 appended |
| MODIFY | `quant-backtesting-frontend/hooks/use-api.ts` | ~40 appended |
| MODIFY | `services/api/app/schemas/strategy.py` | ~50 appended |
| MODIFY | `services/api/app/routers/strategy.py` | ~80 appended |
| CREATE | `core/quant_core/backtest/__init__.py` | ~1 |
| CREATE | `core/quant_core/backtest/prom.py` | ~30 |
| CREATE | `core/quant_core/backtest/neighbor_avg.py` | ~30 |
| CREATE | `core/quant_core/backtest/profile.py` | ~40 |
| CREATE | `core/quant_core/backtest/kelly.py` | ~25 |
| CREATE | `core/quant_core/backtest/statistical.py` | ~60 |
| CREATE | `core/quant_core/backtest/wfo.py` | ~200 |
| CREATE | `services/api/app/schemas/backtest_wfo.py` | ~80 |
| CREATE | `services/api/app/routers/backtest_wfo.py` | ~100 |
| MODIFY | `services/api/app/main.py` | ~2 lines |
| CREATE | 8 backtest frontend components | ~800 total |
| MODIFY | `quant-backtesting-frontend/app/backtest/page.tsx` | ~100 changed |
| CREATE | 4 test files | ~200 total |
