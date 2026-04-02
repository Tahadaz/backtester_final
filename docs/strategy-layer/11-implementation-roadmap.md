# Strategy Layer — Implementation Roadmap

## Summary

The strategy layer (Phase 2) depends on Phase 1 (signal engine + indicator explorer). Phase 1 defines the indicator types, scoring formulas, and parameter ranges that the strategy layer consumes.

Implementation within Phase 2 should follow an order that respects business dependencies. The strategy page is a chain of decisions — each section depends on the one above it.

## Dependency: Phase 1 (Signal Engine)

Phase 1 delivers:

- 4 indicator families (SMA, MACD, RSI, OBV) with continuous scoring
- ATR normalization
- Indicator explorer page for interactive exploration
- OOS evaluation pipeline (walk-forward windows, robustness scoring)

The strategy layer assumes these exist. Specifically:

- Signal Construction (doc 05) references the indicator types and scoring formulas from Phase 1
- Entry/Exit Rules (docs 06–07) reference the continuous scores produced by those indicators
- The WFO flags are designed to interface with the backtest engine's optimization loop

## Implementation Order within Phase 2

### Step 1: Strategy Domain and Persistence

**Deliverables:**
- Updated `SavedStrategy` schema with `portfolio` + `stocks` structure
- Per-stock `StockStrategyConfig` model
- `WFOParam<T>` type for every optimizable parameter
- Updated CRUD endpoints to handle the new schema
- Database migration for the expanded `config_json`

**Depends on:** Phase 1 (indicator types known)

**Verification:**
- [ ] Strategy can be created, saved, loaded, duplicated, archived with the new schema
- [ ] Per-stock configs are persisted and retrieved correctly
- [ ] WFO flags are stored and round-tripped without loss

### Step 2: Universe + Capital + Allocation (Portfolio Level)

**Deliverables:**
- Universe section (filters, candidates, basket) — largely exists from Phase 1
- Capital configuration (account equity)
- Allocation method selection
- Per-stock tab scaffold (one tab per basket stock)

**Depends on:** Step 1

**Verification:**
- [ ] Basket selection produces per-stock tabs
- [ ] Adding/removing stocks from basket creates/removes tabs
- [ ] Allocation method is persisted in the strategy

### Step 3: Strategy Type Section

**Deliverables:**
- Strategy type selector (Trend Following / Mean Reversion) per stock tab
- Contextual guidance display (indicator role tables)
- Default entry/exit rule templates per type

**Depends on:** Step 2

**Verification:**
- [ ] Strategy type is persisted per stock
- [ ] Changing type shows appropriate guidance
- [ ] Type change with existing rules shows warning

### Step 4: Signal Construction Section

**Deliverables:**
- Per-family indicator type selector (v1: one type per family)
- Parameter inputs with manual/WFO toggle
- WFO scan range inputs (min, max, step)
- Score preview backend endpoint
- Score preview UI (current value, sparkline, distribution)

**Depends on:** Step 3, Phase 1 indicator implementations

**Verification:**
- [ ] Parameters are persisted per stock per family
- [ ] WFO flag toggles correctly between manual and wfo modes
- [ ] Score preview updates when parameters change
- [ ] WFO parameter count is computed correctly

### Step 5: Entry Rules Section

**Deliverables:**
- Entry rule list UI (add, remove, reorder)
- Rule expression builder (score variables + operators)
- Sizing configuration per entry
- 5 configuration options (A–E)
- Entry preview backend endpoint
- Entry preview UI (historical trigger markers)

**Depends on:** Step 4

**Verification:**
- [ ] Entry rules are persisted per stock
- [ ] Multiple entries can be added
- [ ] Config options A–E work correctly
- [ ] WFO parameter count includes entry rule parameters
- [ ] Entry preview shows correct trigger bars

### Step 6: Exit Rules Section

**Deliverables:**
- Exit rule list UI (mirrors entry rules)
- Rule expression builder
- Reduction sizing per exit
- 5 configuration options
- Exit preview backend endpoint

**Depends on:** Step 5

**Verification:**
- [ ] Exit rules are persisted per stock
- [ ] Reduction percentages work correctly (relative to current position)
- [ ] Config options A–E work correctly
- [ ] WFO parameter count includes exit rule parameters

### Step 7: Risk Section

**Deliverables:**
- Stop loss configuration (manual %, ATR-based, WFO)
- Take profit configuration (manual %, R:R, WFO)
- Cooldown and time stop configuration
- Max position % and max sector % (always manual)
- Risk preview backend endpoint

**Depends on:** Step 6

**Verification:**
- [ ] All risk parameters are persisted per stock
- [ ] ATR-based stops compute correctly
- [ ] WFO flags work for optimizable risk parameters
- [ ] Max position/sector % are never WFO-flagged

### Step 8: Review and Backtest Handoff

**Deliverables:**
- Per-stock review section
- WFO parameter count display with warnings
- Pardo DF constraint check
- Ready/not-ready checklist
- Global review aggregation
- Backtest handoff endpoint and payload
- "Open in Backtest" action

**Depends on:** Steps 1–7

**Verification:**
- [ ] WFO parameter count is accurate across all sections
- [ ] Warnings appear at appropriate thresholds (10, 15)
- [ ] Blocking items prevent backtest handoff
- [ ] Handoff payload contains complete strategy definition
- [ ] Backtest page can hydrate from handoff payload

### Step 9: "Apply to All" Template

**Deliverables:**
- "Apply to all stocks" action on any stock tab
- Confirmation dialog listing what will be overwritten
- Selective application (choose which sections to apply)

**Depends on:** Steps 3–7

**Verification:**
- [ ] Template copies all sections to all stocks
- [ ] Each stock's config remains independently editable after application
- [ ] Max position % and max sector % can be excluded from template

## Success Criteria

The strategy layer is complete when:

1. A user can create a strategy, select a basket, and configure each stock independently
2. Each stock has a strategy type, signal construction, entry rules, exit rules, and risk parameters
3. Parameters can be toggled between manual and WFO modes with scan ranges
4. The review section accurately counts WFO parameters and warns about overfitting risk
5. The handoff to Backtest contains a complete, validated strategy definition
6. The "Apply to all" template works for bulk configuration
7. All configurations round-trip correctly through save/load cycles

## Timeline Estimate

| Step | Effort | Cumulative |
|------|--------|------------|
| 1. Domain + Persistence | 3–4 days | 3–4 days |
| 2. Universe + Tabs | 2–3 days | 5–7 days |
| 3. Strategy Type | 1–2 days | 6–9 days |
| 4. Signal Construction | 3–4 days | 9–13 days |
| 5. Entry Rules | 4–5 days | 13–18 days |
| 6. Exit Rules | 3–4 days | 16–22 days |
| 7. Risk | 2–3 days | 18–25 days |
| 8. Review + Handoff | 3–4 days | 21–29 days |
| 9. Apply to All | 1–2 days | 22–31 days |

Total estimate: ~4–6 weeks of focused development.

## Cross-Links

- Phase 1 signal engine: see [../signal-generation/00-INDEX.md](../signal-generation/00-INDEX.md)
- Strategy domain model: see [02-strategy-domain-and-page-architecture.md](./02-strategy-domain-and-page-architecture.md)
- API contracts: see [10-api-data-flow-and-frontend-contracts.md](./10-api-data-flow-and-frontend-contracts.md)
