# UI component library — fundamentals layer

> Per-component implementation contracts. Codex builds each component to these specs. All components live under `frontend/components/fundamentals/` unless otherwise noted. All TypeScript, React function components.

Design tokens come from [17-ui-design-language.md](17-ui-design-language.md). Page layout from [15-ui-goals-and-design.md](15-ui-goals-and-design.md). Behavior of each tab/section from [15-ui-goals-and-design.md](15-ui-goals-and-design.md).

## Component index

| # | Component | Purpose | File |
|---|---|---|---|
| 1 | `<MethodologyCard>` | Universal 6-section card for valuation models + screens | `methodology-card.tsx` |
| 2 | `<ComputationStepsTable>` | Per-method numbered step trace | `computation-steps-table.tsx` |
| 3 | `<PerMultipleBreakdown>` | Multiples table with peer medians + scope | `per-multiple-breakdown.tsx` |
| 4 | `<CrossMethodScatter>` | Scatter of 7 fair values + ensemble band | `cross-method-scatter.tsx` |
| 5 | `<EnsembleSidebar>` | Permanent right rail | `ensemble-sidebar.tsx` |
| 6 | `<UniverseTreeTable>` | Grouped universe by region | `universe-tree-table.tsx` |
| 7 | `<DetailStrip>` | Dense 5-KPI top strip with scenarios | `detail-strip.tsx` |
| 8 | `<PillarRow>` | Expandable pillar score row with drill-down | `pillar-row.tsx` |
| 9 | `<DiagnosticPanel>` | DuPont / Piotroski / Accrual panel | `diagnostic-panel.tsx` |
| 10 | `<AnnualTable>` | Financials with sparklines | `annual-table.tsx` |
| 11 | `<AssumptionEditor>` | Editor with defaults + scenarios + Δ-FV | `assumption-editor.tsx` |
| 12 | `<ScreenCard>` | Per-screen card for Magic Formula/PEG/Altman/EVA/regression | `screen-card.tsx` |
| 13 | `<SensitivityHeatmap>` | Improved heatmap with axis labels + current marker | `sensitivity-heatmap.tsx` |
| 14 | `<ZoneGauge>` | Altman / GARP / confidence horizontal gauge | `zone-gauge.tsx` |
| 15 | `<ScoreBar>` | Horizontal 0-100 score bar | `score-bar.tsx` |
| 16 | `<Sparkline>` | 80×20 inline sparkline | `sparkline.tsx` |
| 17 | `<Chip>` / `<Badge>` | Confidence, scope, zone, proxy chips | `chip.tsx` |
| 18 | `<TearSheet>` | Print-only layout | `tear-sheet.tsx` |

Plus 2 utility libs:

| Lib | Purpose | File |
|---|---|---|
| `model-step-traces` | Per-model step generators (FCFF DCF, FCFE DCF, ...) | `frontend/lib/fundamentals/model-step-traces.ts` |
| `warning-dictionary` | Translation of warning codes to plain language | `frontend/lib/fundamentals/warning-dictionary.ts` |

---

## 1. `<MethodologyCard>`

The universal card for any valuation model or screen. 6 collapsible sections.

### Props

```typescript
interface MethodologyCardProps {
  modelKey: ValuationModel | ScreenName;            // "fcff_dcf" | "ddm" | ... | "magic_formula" | ...
  headline: {
    primaryLabel: string;                            // "Fair value" or "Implied growth"
    primaryValue: string;                            // "MAD 312" or "3.61%" or "—"
    secondary?: { label: string; value: string };    // optional second number, e.g. "Upside +14.7%"
    confidence?: "high" | "medium" | "low" | "unavailable" | null;
    weight?: number | null;                          // 0-1 ensemble weight share
    isProxy?: boolean;
    family?: "intrinsic" | "relative" | "diagnostic";
  };
  methodology: string;                               // one-line prose
  inputs: Record<string, InputRow>;                  // see below
  outputs: Record<string, OutputRow>;                // see below
  stepsRenderer: () => ReactNode;                    // method-specific component
  warnings: string[];                                // raw warning codes
  crossCheck?: string;                               // optional narrative
  defaultExpanded?: boolean;                         // default false
}

interface InputRow {
  value: number | string | null;
  unit?: string;                                     // "MAD", "%", "x" (multiple), etc.
  source?: string;                                   // "reported_free_cash_flow", "from PER 1.8 + price"
}

interface OutputRow {
  value: unknown;                                    // can be number, array, object — renderer handles it
  unit?: string;
  highlight?: boolean;                               // if true, render as bold/larger
}
```

### Structure

```html
<div class="fund-card methodology-card">
  <header class="methodology-card-header" onClick={toggleExpand}>
    <div class="left">
      <ChevronIcon expanded={isExpanded} />
      <span class="model-label">{MODEL_LABELS[modelKey]}</span>
      {family === "diagnostic" && <Badge type="diagnostic">Diagnostic</Badge>}
    </div>
    <div class="right">
      <div class="headline-block">
        <span class="headline-primary">{headline.primaryValue}</span>
        <span class="headline-secondary">{headline.secondary?.value}</span>
      </div>
      {confidence && <Chip type={confidenceToType(confidence)}>{confidence}</Chip>}
      {weight != null && <span class="weight-badge">{(weight * 100).toFixed(0)}%</span>}
      {isProxy && <Chip type="warning">proxy</Chip>}
    </div>
  </header>

  {isExpanded && (
    <div class="methodology-card-body">
      <Section title="Methodology" defaultOpen={true}>
        <p class="prose">{methodology}</p>
      </Section>

      <Section title={`Inputs used (${Object.keys(inputs).length})`} defaultOpen={true}>
        <table class="fund-table inputs-table">
          {Object.entries(inputs).map(([key, row]) => (
            <tr>
              <td>{humanizeKey(key)}</td>
              <td class="r font-mono">{formatValue(row.value, row.unit)}</td>
              <td class="muted">{row.source}</td>
            </tr>
          ))}
        </table>
      </Section>

      <Section title="Step-by-step computation" defaultOpen={false}>
        {stepsRenderer()}                            <!-- method-specific -->
      </Section>

      <Section title="Outputs persisted" defaultOpen={false}>
        {/* OutputRenderer dispatches on shape: number, array, object */}
        <OutputRenderer outputs={outputs} />
      </Section>

      <Section title={`Warnings (${warnings.length})`} defaultOpen={warnings.length > 0}>
        {warnings.length === 0 ? (
          <span class="muted">—</span>
        ) : (
          <ul class="warning-list">
            {warnings.map(code => (
              <li>
                <Chip type="warning">{code}</Chip>
                <span>{WARNING_DICTIONARY[code] ?? code}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {crossCheck && (
        <Section title="Cross-check" defaultOpen={false}>
          <p class="prose">{crossCheck}</p>
        </Section>
      )}
    </div>
  )}
</div>
```

### Sub-components

- `<Section>`: collapsible region with title + chevron + content slot. State persists per card via React state.
- `<Chip>`: see #17 below.
- `<OutputRenderer>`: dispatches on `typeof value` — arrays as horizontal mini-tables, dicts as key-value, scalars as text.

### Styling (Tailwind-style)

```html
<div class="border border-default rounded-md p-3 bg-app">
  <header class="flex items-center justify-between gap-3 cursor-pointer">
    ...
  </header>
  <div class="mt-3 space-y-3 border-t border-default pt-3">
    ...
  </div>
</div>
```

### State

- `isExpanded: boolean` — controlled by parent or internal state.
- Each `<Section>` has its own `isOpen` state (default per `defaultOpen` prop).

### Behavior

- Click header → toggle expanded.
- Click section title → toggle that section.
- All numeric values formatted via shared `formatValue(value, unit)`.

### Accessibility

- Header is `<button>` with `aria-expanded`.
- Each section title is `<button>` with `aria-expanded`.

---

## 2. `<ComputationStepsTable>`

Renders a numbered list of computation steps with intermediate values.

### Props

```typescript
interface Step {
  number: number;
  label: string;                                    // "Project FCF with growth fade"
  formula?: string;                                 // optional formula display
  result: string | number;                          // "MAD 1264.8" or "5.4%"
  resultUnit?: string;
  detail?: ReactNode;                               // optional expanded detail (e.g. a sub-table)
}

interface ComputationStepsTableProps {
  steps: Step[];
  finalResult?: { label: string; value: string };   // e.g. "Fair value per share: MAD 221.98"
}
```

### Structure

```html
<table class="fund-table steps-table">
  <thead>
    <tr>
      <th class="num">#</th>
      <th>Operation</th>
      <th>Formula</th>
      <th class="r">Result</th>
    </tr>
  </thead>
  <tbody>
    {steps.map(step => (
      <>
        <tr>
          <td class="num font-mono muted">{step.number}.</td>
          <td>{step.label}</td>
          <td class="font-mono text-xs muted">{step.formula}</td>
          <td class="r font-mono">{formatResult(step.result, step.resultUnit)}</td>
        </tr>
        {step.detail && (
          <tr><td></td><td colspan="3">{step.detail}</td></tr>
        )}
      </>
    ))}
    {finalResult && (
      <tr class="final-row">
        <td></td>
        <td colspan="2" class="font-medium">{finalResult.label}</td>
        <td class="r font-mono font-bold">{finalResult.value}</td>
      </tr>
    )}
  </tbody>
</table>
```

### Method-specific renderers (in `model-step-traces.ts`)

```typescript
// frontend/lib/fundamentals/model-step-traces.ts
export function buildFcffDcfSteps(row: FundamentalValuationResult): Step[] {
  const inputs = row.inputs ?? {}
  const outputs = row.outputs ?? {}
  return [
    { number: 1, label: "Resolve starting FCF", formula: "from " + inputs.fcf_source,
      result: inputs.fcf_start, resultUnit: "MAD M" },
    { number: 2, label: "Resolve growth input", formula: "from " + inputs.fcf_growth_source,
      result: inputs.growth, resultUnit: "%" },
    { number: 3, label: "Resolve net debt bridge", formula: "from " + inputs.net_debt_source,
      result: inputs.net_debt, resultUnit: "MAD M" },
    { number: 4, label: "Project FCF with growth fade (5 years)",
      result: "see table",
      detail: <YearByYearProjectionTable projection={outputs.projected_fcf} ... /> },
    { number: 5, label: "Terminal value = FCF_5 × (1+g) / (WACC − g)",
      result: computeTerminalValue(...), resultUnit: "MAD M" },
    { number: 6, label: "Enterprise value = Σ PV + PV(terminal)",
      result: computeEv(...), resultUnit: "MAD M" },
    { number: 7, label: "Equity value = EV − Net Debt",
      formula: `${ev} − ${inputs.net_debt}`,
      result: ev - inputs.net_debt, resultUnit: "MAD M" },
    { number: 8, label: "Fair value per share = Equity / Shares",
      result: row.fair_value, resultUnit: "MAD" },
  ]
}

export function buildFcfeDcfSteps(row: FundamentalValuationResult): Step[] { /* ... */ }
export function buildDdmSteps(row: FundamentalValuationResult): Step[] { /* ... */ }
export function buildResidualIncomeSteps(row: FundamentalValuationResult): Step[] { /* ... */ }
export function buildJustifiedMultiplesSteps(row: FundamentalValuationResult): Step[] { /* ... */ }
export function buildRelativeMultiplesSteps(row: FundamentalValuationResult): Step[] { /* ... */ }
export function buildReverseDcfSteps(row: FundamentalValuationResult): Step[] { /* ... */ }

export function buildMagicFormulaSteps(screen): Step[] { /* ... */ }
export function buildPegGarpSteps(screen): Step[] { /* ... */ }
export function buildAltmanZSteps(screen): Step[] { /* ... */ }
export function buildEvaSteps(screen): Step[] { /* ... */ }
export function buildRegressionAdjSteps(screen): Step[] { /* ... */ }
```

Each builder reads from the `inputs` and `outputs` JSON on the engine's `ValuationResult` (or `screen` dict), so the docs in `06-valuation-models.md` and `16-institutional-screens.md` are the contract for the data shape.

---

## 3. `<PerMultipleBreakdown>`

Used inside the relative multiples and justified multiples cards.

### Props

```typescript
interface PerMultipleBreakdownProps {
  rows: Array<{
    metric: string;                                  // "PER", "Price_to_Book", ...
    own: number | null;
    peerMedian?: number | null;                      // for relative multiples
    justifiedValue?: number | null;                  // for justified multiples
    cohort?: "sector" | "market" | null;
    cohortCount?: number | null;
    impliedPrice: number | null;
  }>;
  aggregateLabel?: string;                            // e.g. "Median implied price"
  aggregateValue?: number | null;
  currency?: string;                                  // "MAD"
}
```

### Structure

```html
<table class="fund-table per-multiple-table">
  <thead>
    <tr>
      <th>Multiple</th>
      <th class="r">Own</th>
      <th class="r">{peerMedian ? "Peer median" : "Justified"}</th>
      <th>Cohort</th>
      <th class="r">n</th>
      <th class="r">Implied price</th>
    </tr>
  </thead>
  <tbody>
    {rows.map(row => (
      <tr>
        <td>{humanizeMetric(row.metric)}</td>
        <td class={cn("r font-mono", row.own > row.peerMedian ? "t-rich" : "t-cheap")}>{row.own}</td>
        <td class="r font-mono">{row.peerMedian ?? row.justifiedValue}</td>
        <td>{row.cohort && <Chip type={row.cohort === "sector" ? "positive" : "warning"}>{row.cohort}</Chip>}</td>
        <td class="r font-mono muted">{row.cohortCount}</td>
        <td class="r font-mono font-medium">{currency} {row.impliedPrice}</td>
      </tr>
    ))}
    {aggregateValue != null && (
      <tr class="aggregate">
        <td colspan="5" class="r font-medium">{aggregateLabel}</td>
        <td class="r font-mono font-bold">{currency} {aggregateValue}</td>
      </tr>
    )}
  </tbody>
</table>
```

### Interactions

- Hovering a row reveals a tooltip with the peer list (when `cohort === "sector"` and a peer list is provided).
- Sortable headers.

### Color rules

- Own value: red foreground if richer than peer, green if cheaper than peer.
- Cohort chip: green if sector, amber if market fallback.

---

## 4. `<CrossMethodScatter>`

A horizontal scatter showing all 7 fair values with the ensemble band overlaid.

### Props

```typescript
interface CrossMethodScatterProps {
  models: Array<{
    key: string;                                     // "fcff_dcf"
    label: string;                                   // "FCFF DCF"
    fairValue: number | null;
    weight: number | null;                            // 0-1
    isProxy: boolean;
    isDiagnostic: boolean;
  }>;
  ensembleBase: number;
  modelDispersionLow: number;
  modelDispersionHigh: number;
  monteCarloLow: number;
  monteCarloHigh: number;
  currentPrice: number;
  currency: string;
}
```

### Visual

```
MAD 200 ┤●───●─────●─●●────●──┤ MAD 380
         ↑   ↑     ↑ ↑↑    ↑  ↑
       RelM Just  RI Mc Curr DDM
       240 295  224 268 285 290 380

Monte Carlo  ════════════════════
             P5=282         P95=340

Model spread ──────────────────
             Q1=240         Q3=312

Weighted mean ●  fair_value_base = 312
```

### Implementation

- SVG-based for precise control.
- Width: full card width (e.g. 720px).
- Height: 80px.
- Horizontal axis: min = floor(min model FV − 10%); max = ceil(max(model FV, current_price) + 10%).
- Markers: 6px circles, foreground color. Larger (10px) for weighted ensemble center.
- Monte Carlo band: gray rectangle at y=20, 6px tall.
- Model dispersion band: hairline at y=40, 1px tall.
- Current price: vertical accent line + label "Current MAD 380".
- Model labels: small (text-xs) below the markers, vertically rotated 45° to avoid overlap.

### Interactions

- Click a model marker → call `onModelClick(key)` prop, parent scrolls/expands that model's card.
- Hover a marker → tooltip with full label, weight, fair value, confidence.

---

## 5. `<EnsembleSidebar>`

Permanent right rail showing the consolidated picture. Always visible on the Valuation tab; collapsible on others.

### Props

```typescript
interface EnsembleSidebarProps {
  ensemble: FundamentalEnsembleResult;
  modelOrder: Array<{                                // top-3 weighted models for inline summary
    key: string;
    label: string;
    weight: number;
    fairValue: number;
  }>;
  reverseDcf: { impliedGrowth: number; sustainableGrowth?: number | null } | null;
  technicalSignal?: { label: string; score: number } | null;
  snapshotMeta: {
    importedAt: string;                              // ISO date
    fiscalYear: number;
    currency: string;
    workbookVersion?: string;
  };
}
```

### Sections (vertical stack)

1. **Fair value band** — `<EnsembleBandViz>` mini-component showing MC and model-dispersion overlap.
2. **Confidence ladder** — `<ScoreBar>` with the ensemble confidence_score.
3. **Models used** — vertical list of model entries with weight % and fair value.
4. **Cross-check** — 3 lines: reverse DCF implied g, sustainable g, verdict.
5. **Snapshot data** — source, imported_at, FY, currency.
6. **Cross-layer** — technical signal status (if present).

### Layout

- Width: 320px on desktop. Collapsible on tablets (< 1024px) to a vertical icon strip.
- Position: `sticky top-16` so it follows scroll.
- Padding: 16px. Section gap: 16px. Hairline separator between sections.

### Sub-component `<EnsembleBandViz>`

```html
<svg width="280" height="48" viewBox="0 0 280 48">
  <!-- background scale: min to max -->
  <line x1="20" y1="24" x2="260" y2="24" stroke="var(--color-border-default)" />
  <!-- MC band -->
  <rect x={mcLowX} y="18" width={mcWidth} height="12" fill="var(--color-accent-subtle)" />
  <!-- Model dispersion band -->
  <line x1={modelLowX} x2={modelHighX} y1="32" y2="32" stroke="var(--color-fg-muted)" stroke-width="2" />
  <!-- Base marker -->
  <circle cx={baseX} cy="24" r="4" fill="var(--color-fg-primary)" />
  <!-- Current price marker -->
  <line x1={currentX} y1="14" x2={currentX} y2="34" stroke="var(--color-accent)" stroke-width="1.5" />
  <text x={currentX} y="46" text-anchor="middle" class="text-xs font-mono">{currentPrice}</text>
</svg>
```

---

## 6. `<UniverseTreeTable>`

Grouped universe table. Replaces the current flat universe table.

### Props

```typescript
interface UniverseTreeTableProps {
  rows: FundamentalUniverseRow[];
  selectedSymbol: string | null;
  onSelect: (symbol: string) => void;
  groupBy: "market_region" | "sector";               // default "market_region"
  visibleColumns: UniverseColumn[];
  sortKey: UniverseColumn;
  sortDirection: "asc" | "desc";
  onSort: (key: UniverseColumn, dir: "asc" | "desc") => void;
}

type UniverseColumn =
  | "symbol"
  | "overall_score"
  | "upside_pct"
  | "confidence"
  | "altman_zone"
  | "magic_formula_score"
  | "peg_value"
  | "eva_score"
  | "regression_richness_avg"
  | "market_cap";
```

### Structure

```html
<div class="universe-tree-container">
  <div class="universe-tree-header">
    <h3>Univers fondamental</h3>
    <span class="muted">{rows.length} titres</span>
    <ColumnToggle visibleColumns={...} onChange={...} />
  </div>
  <div class="universe-tree-scroll">
    {groupedRows.map(([groupName, items]) => (
      <Group key={groupName} label={groupName} count={items.length} defaultExpanded={true}>
        <table class="fund-table universe-table">
          <thead>
            <tr>
              <SortableHeader key="symbol">Ticker</SortableHeader>
              <SortableHeader key="overall_score" align="right">Score</SortableHeader>
              <SortableHeader key="upside_pct" align="right">Upside</SortableHeader>
              <SortableHeader key="confidence">Conf.</SortableHeader>
              {visibleColumns.includes("altman_zone") && (
                <SortableHeader key="altman_zone">Z</SortableHeader>
              )}
              ...
            </tr>
          </thead>
          <tbody>
            {items.map(row => (
              <UniverseRow row={row} active={row.symbol === selectedSymbol} onClick={() => onSelect(row.symbol)} />
            ))}
          </tbody>
        </table>
      </Group>
    ))}
  </div>
</div>
```

### Visual rules

- Group rows: 28px tall, light background (`bg-bg-subtle`), bold label, count badge on right, chevron for expand/collapse.
- Item rows: 24px tall, very subtle hover background.
- Active row: 2px left border in accent color, no background change.
- Sortable headers: small arrow indicator when active sort.

### Column rendering rules

```typescript
function UniverseRow({ row, active, onClick }) {
  return (
    <tr class={cn(active && "active")} onClick={onClick}>
      <td class="font-medium">{row.symbol}</td>
      <td class="r font-mono">
        <ScoreBar value={row.overall_score} compact />
      </td>
      <td class={cn("r font-mono", upsideClass(row.upside_pct))}>
        {fmtPct(row.upside_pct)}
      </td>
      <td><Chip type={confType(row.confidence)}>{row.confidence}</Chip></td>
      {visibleColumns.includes("altman_zone") && (
        <td><Chip type={altmanType(row.altman_zone)}>{row.altman_zone}</Chip></td>
      )}
      ...
    </tr>
  )
}
```

---

## 7. `<DetailStrip>`

Top strip of the detail area. 5 KPIs, each carrying scenario context.

### Props

```typescript
interface DetailStripProps {
  symbol: string;
  displayName: string;
  sector: string | null;
  fiscalYear: number | null;
  currency: string;
  freshnessLabel: string;                            // "12d ago"
  onRefresh?: () => void;
  scenarios: Record<"bear" | "base" | "bull", {
    overallScore: number | null;
    fairValueBase: number | null;
    upsidePct: number | null;
    confidence: string | null;
    modelsUsedCount: number;
    qualityScore: number | null;
    mcLow?: number | null;
    mcHigh?: number | null;
  }>;
  selectedScenario: "bear" | "base" | "bull";
}
```

### Structure

```html
<div class="detail-strip">
  <div class="strip-header">
    <span class="symbol-large">{symbol}</span>
    <span class="display-name">{displayName}</span>
    <span class="muted">·</span>
    <span class="sector">{sector}</span>
    <span class="muted">· FY {fiscalYear} · {currency} · {freshnessLabel}</span>
    {onRefresh && <Button size="sm" onClick={onRefresh}>Refresh</Button>}
  </div>
  <div class="strip-kpis">
    <KpiTile
      label="Score"
      value={scenarios.base.overallScore}
      bear={scenarios.bear.overallScore}
      bull={scenarios.bull.overallScore}
    />
    <KpiTile
      label="Fair value"
      value={fmtMoney(scenarios.base.fairValueBase, currency)}
      bear={scenarios.bear.fairValueBase}
      bull={scenarios.bull.fairValueBase}
    />
    <KpiTile
      label="Upside"
      value={fmtPct(scenarios.base.upsidePct)}
      tone={upsideTone(scenarios.base.upsidePct)}
      bear={scenarios.bear.upsidePct}
      bull={scenarios.bull.upsidePct}
    />
    <KpiTile
      label="Confidence"
      value={scenarios.base.confidence}
      sub={`${scenarios.base.modelsUsedCount} of 7 models`}
    />
    <KpiTile
      label="Quality"
      value={scenarios.base.qualityScore}
      sub={`MC band ${scenarios.base.mcLow}–${scenarios.base.mcHigh}`}
    />
  </div>
</div>
```

### `<KpiTile>` shape

```
┌─────────────────────────┐
│ FAIR VALUE              │ ← label (text-xs uppercase muted)
│ 312                     │ ← value (text-2xl font-mono)
│ bear 278 │ bull 355     │ ← scenario fly-outs (text-xs muted)
└─────────────────────────┘
```

---

## 8. `<PillarRow>`

Expandable row in the Summary tab showing one pillar score with drill-down on click.

### Props

```typescript
interface PillarRowProps {
  pillarKey: "value" | "quality" | "growth" | "risk" | "cash_flow" | "health";
  label: string;                                     // localized
  score: number | null;
  scope: "sector" | "market" | null;
  components?: {
    raw_percentile?: number | null;
    accounting_discipline?: number | null;
    piotroski_lite?: number | null;
    dupont_bridge?: number | null;
    accrual_quality?: number | null;
  };
  contributingMetrics?: Array<{
    metric: string;
    value: number | null;
    median: number | null;
    percentile: number | null;
    scope: "sector" | "market";
  }>;
  trend?: "up" | "down" | "flat";                    // vs prior import
}
```

### Structure

```html
<div class="pillar-row">
  <button class="pillar-summary" onClick={toggleExpand}>
    <ChevronIcon expanded={isExpanded} />
    <span class="pillar-label">{label}</span>
    <ScoreBar value={score} />
    <span class="font-mono">{fmtNumber(score)}</span>
    {scope && <Chip type={scope === "sector" ? "positive" : "warning"}>{scope}</Chip>}
    {trend && <TrendArrow direction={trend} />}
  </button>
  {isExpanded && (
    <div class="pillar-drilldown">
      {components && (
        <div class="pillar-components">
          <span class="text-xs uppercase muted">Components</span>
          {Object.entries(components).map(([key, value]) => value != null && (
            <div class="component-row">
              <span>{humanizeKey(key)}</span>
              <ScoreBar value={value} compact />
              <span class="font-mono">{fmtNumber(value)}</span>
            </div>
          ))}
        </div>
      )}
      {contributingMetrics && contributingMetrics.length > 0 && (
        <table class="fund-table">
          <thead>
            <tr><th>Metric</th><th class="r">Value</th><th class="r">Median</th><th class="r">Pct</th><th>Scope</th></tr>
          </thead>
          <tbody>
            {contributingMetrics.map(m => (
              <tr>
                <td>{humanizeMetric(m.metric)}</td>
                <td class="r font-mono">{fmtMetricValue(m.metric, m.value)}</td>
                <td class="r font-mono muted">{fmtMetricValue(m.metric, m.median)}</td>
                <td class="r font-mono">{fmtNumber(m.percentile)}</td>
                <td><Chip type={m.scope === "sector" ? "positive" : "warning"}>{m.scope}</Chip></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )}
</div>
```

---

## 9. `<DiagnosticPanel>`

Quality tab body. Renders DuPont bridge + Piotroski-lite + Accrual quality + per-metric breakdown.

### Props

```typescript
interface DiagnosticPanelProps {
  diagnostics: {
    dupont: DuPontDiagnostic;
    piotroski_lite: PiotroskiDiagnostic;
    accrual_quality: AccrualDiagnostic;
    accounting_discipline: number | null;
    metric_breakdown?: Record<string, {
      score: number | null;
      scope: "sector" | "market";
      value: number;
      median: number;
      z_score: number;
      pct_dev: number;
    }>;
    smoothing?: Record<string, {
      latest: number | null;
      trailing_3y: number | null;
      trailing_5y: number | null;
    }>;
  };
}
```

### Sections

1. **DuPont bridge** card with 5 rows (Net Margin, Asset Turnover, Equity Multiplier, Reported ROE, Implied ROE) + gap + score.
2. **Piotroski-lite** card with 9 check rows, each row showing check name / status chip / value.
3. **Accrual quality** card with 3 lines (FCF, NI, cash conversion ratio).
4. **Metric breakdown** table — sortable by z-score / pct deviation. Useful for "find the most extreme metric drivers".
5. **Smoothing** card — per metric, show latest / 3y / 5y with sparkline.

---

## 10. `<AnnualTable>`

Financials tab body. Annual metrics with sparklines per row.

### Props

```typescript
interface AnnualTableProps {
  metrics: AnnualMetricRow[];                       // raw data from API
  visibleMetrics: string[];                         // canonical names to render
  fiscalYears: number[];                             // last 5 years
  currency: string;
}
```

### Structure

```html
<table class="fund-table annual-table">
  <thead>
    <tr>
      <th>Metric</th>
      {fiscalYears.map(yr => <th class="r">FY {yr}</th>)}
      <th class="r">YoY</th>
      <th>Trend</th>
    </tr>
  </thead>
  <tbody>
    {visibleMetrics.map(metric => {
      const series = buildSeries(metrics, metric, fiscalYears)
      const yoy = computeYoy(series)
      return (
        <tr>
          <td>{humanizeMetric(metric)}</td>
          {series.map(value => (
            <td class="r font-mono">{fmtMetricValue(metric, value)}</td>
          ))}
          <td class={cn("r font-mono", yoyClass(yoy))}>{fmtPct(yoy)}</td>
          <td><Sparkline values={series} /></td>
        </tr>
      )
    })}
  </tbody>
</table>
```

---

## 11. `<AssumptionEditor>`

Assumptions tab body. Editor with defaults + scenarios + Δ-FV preview.

### Props

```typescript
interface AssumptionEditorProps {
  current: Record<string, number>;                  // active assumption set
  defaults: Record<string, number>;                  // global DEFAULT_ASSUMPTIONS
  scenarios: Record<"bear" | "base" | "bull", number | null>;
  symbol: string;
  scenario: "bear" | "base" | "bull";
  onSave: (assumptions: Record<string, number>) => Promise<void>;
  onPreview?: (assumptions: Record<string, number>) => Promise<number>;  // returns new fair value
}
```

### Structure

Per-field row:

```html
<div class="assumption-row">
  <span class="label">Cost of equity</span>
  <input
    type="number"
    step="0.005"
    value={draft.cost_of_equity}
    onChange={...}
  />
  <span class="text-xs muted">Default: {fmtPct(defaults.cost_of_equity)}</span>
  <span class="text-xs muted">
    Bear {scenarios.bear} · Base {scenarios.base} · Bull {scenarios.bull}
  </span>
  <button onClick={() => resetField("cost_of_equity")}>Reset</button>
</div>
```

Below the form:

```html
<div class="assumption-footer">
  <span>New ensemble fair value: <b>MAD 295.30</b> (was MAD 312.00 — Δ −5.4%)</span>
  <Button onClick={save}>Save assumptions</Button>
</div>
```

The Δ-FV is computed live via `onPreview` if the parent supports it; otherwise just show "Save to recompute".

---

## 12. `<ScreenCard>`

Per-screen card for Tab 6 (Screens). Reuses `<MethodologyCard>` with screen-specific renderers.

### Magic Formula card

```html
<MethodologyCard
  modelKey="magic_formula"
  headline={{ primaryLabel: "Score", primaryValue: fmtNumber(screen.score), ... }}
  methodology={screen.methodology}
  inputs={{
    EBIT: { value: screen.components.ebit, unit: "MAD M" },
    "Invested Op Capital": { value: screen.components.invested_op_capital, unit: "MAD M" },
    "Enterprise Value": { value: screen.components.enterprise_value, unit: "MAD M" },
  }}
  outputs={{
    "ROC": { value: screen.roc, unit: "%", highlight: true },
    "Earnings Yield": { value: screen.earnings_yield, unit: "%", highlight: true },
    "ROC rank": { value: screen.roc_rank, unit: "percentile" },
    "EY rank": { value: screen.ey_rank, unit: "percentile" },
  }}
  stepsRenderer={() => <MagicFormulaSteps screen={screen} />}
  warnings={screen.warnings}
/>
```

### Altman Z card — special: include `<ZoneGauge>` in the headline

```html
<div class="screen-card altman-card">
  <MethodologyCard ... />
  <div class="zone-section">
    <ZoneGauge
      zones={[
        { color: "negative", weight: 1.81, label: "Distress" },
        { color: "warning", weight: 1.18, label: "Grey" },
        { color: "positive", weight: 2.01, label: "Safe" },
      ]}
      value={screen.z_value}
      max={5.0}
    />
  </div>
</div>
```

### PEG / GARP card — special: include zone chart

Per the 5-zone discretization from 16-institutional-screens.md.

### EVA card — special: ROIC vs WACC dual bar

```html
<div class="eva-spread-viz">
  <div class="bar-row">
    <span class="label">ROIC</span>
    <div class="bar" style={{ width: `${screen.roic * 800}px` }}></div>
    <span class="value font-mono">{fmtPct(screen.roic)}</span>
  </div>
  <div class="bar-row">
    <span class="label">WACC</span>
    <div class="bar muted" style={{ width: `${screen.wacc_used * 800}px` }}></div>
    <span class="value font-mono">{fmtPct(screen.wacc_used)}</span>
  </div>
  <div class="spread">
    Spread: {fmtPct(screen.roic_spread)} → EVA {fmtMoney(screen.eva_value)} MAD M
  </div>
</div>
```

### Regression-adjusted card — special: per-multiple richness divergent bars

```html
<div class="richness-viz">
  {Object.entries(screen.regression_richness).map(([metric, data]) => (
    <div class="richness-row">
      <span class="label">{humanizeMetric(metric)}</span>
      <DivergentBar value={data.richness_z} maxAbs={3.0} />
      <span class="value font-mono">{fmtNumber(data.richness_z, 2)} σ</span>
    </div>
  ))}
</div>
```

`<DivergentBar>`: a horizontal bar centered on zero. Positive (right) red; negative (left) green. Width proportional to |z|.

---

## 13. `<SensitivityHeatmap>`

Improved version of the current heatmap.

### Props

```typescript
interface SensitivityHeatmapProps {
  sensitivity: FundamentalSensitivity;               // from API
  current: { wacc: number; terminal_growth: number };  // current assumption values for highlighting
  currency: string;
}
```

### Visual

- Cells: 64×24px.
- Color: linear interpolation min → max as per design language.
- Axis labels: x-axis below (`WACC` values), y-axis on left (`terminal_growth`).
- Current marker: 2px accent-color inset border on the cell matching current assumptions.
- Hover tooltip: shows `(wacc, g) → fair value MAD X (vs current MAD Y, Δ %)`.

---

## 14. `<ZoneGauge>`

Horizontal bar split into colored zones with a marker.

### Props

```typescript
interface ZoneGaugeProps {
  zones: Array<{ color: "positive" | "negative" | "warning"; weight: number; label?: string }>;
  value: number;
  max: number;
  unit?: string;
}
```

### Structure (per 17-ui-design-language.md §9)

```html
<div class="zone-gauge">
  <div class="zone-gauge-track">
    {zones.map(z => <div class={`zone zone-${z.color}`} style={{ flex: z.weight }} />)}
  </div>
  <div class="zone-gauge-marker" style={{ left: `${(value / max) * 100}%` }} />
  <div class="zone-gauge-labels">
    {zoneBoundaries(zones).map(b => <span>{b}</span>)}
  </div>
</div>
```

---

## 15. `<ScoreBar>`

Per design language §8. Inline 4px tall, optional `compact` prop reduces width to 80px.

```typescript
interface ScoreBarProps {
  value: number | null;
  compact?: boolean;
  showValue?: boolean;
  threshold?: { positive: number; negative: number };  // default: {pos: 70, neg: 30}
}
```

---

## 16. `<Sparkline>`

Per design language §4. 80×20 SVG, single hairline.

```typescript
interface SparklineProps {
  values: (number | null)[];
  color?: "default" | "positive" | "negative";
  width?: number;
  height?: number;
}
```

---

## 17. `<Chip>`

```typescript
interface ChipProps {
  type: "positive" | "negative" | "warning" | "neutral" | "muted" | "accent";
  size?: "xs" | "sm";       // default xs
  uppercase?: boolean;       // default true
  children: ReactNode;
}
```

Per design language §5.

---

## 18. `<TearSheet>`

Print-only layout. See [19-ui-tear-sheet-spec.md](19-ui-tear-sheet-spec.md) for the full spec.

```typescript
interface TearSheetProps {
  symbol: string;
  detail: FundamentalStockDetail;
  ensemble: FundamentalEnsembleResult;
}
```

---

## Utility: `warning-dictionary.ts`

```typescript
// frontend/lib/fundamentals/warning-dictionary.ts
export const WARNING_DICTIONARY: Record<string, string> = {
  "missing_positive_fcf": "FCF history missing or non-positive; DCFs could not run reliably.",
  "missing_shares": "Shares outstanding missing; per-share fair value cannot be computed.",
  "missing_net_debt_bridge": "Net debt missing; FCFF DCF assumes zero (overstates equity for leveraged firms).",
  "wacc_not_above_terminal_growth": "WACC ≤ terminal growth; DCF formula degenerate.",
  "cost_of_equity_not_above_terminal_growth": "Cost of equity ≤ terminal growth; FCFE/DDM degenerate.",
  "using_stable_payout_assumption": "Dividend payout missing/invalid; engine substituted default.",
  "using_earnings_growth_proxy": "ROE missing for DDM; using earnings growth as proxy.",
  "fcfe_proxy_from_free_cash_flow": "Debt-flow data missing; FCFE computed from FCF (capped weight).",
  "no_usable_peer_multiple": "Relative multiples couldn't find enough peers.",
  "no_usable_justified_multiple": "Justified multiples computation failed (likely ROE missing).",
  "model_not_eligible": "Model excluded by eligibility rule (e.g. DCF on a bank).",
  "missing_fcf_yield_for_reverse_dcf": "FCF Yield missing; reverse DCF cannot compute implied growth.",
  "currency_mismatch": "Snapshot currency differs from assumption currency.",
  "mixed_model_currencies": "Models within the ensemble reported different currencies.",
  "earnings_growth_proxy": "Growth source is income-statement, not cash-flow.",
  "revenue_growth_proxy": "Growth source is revenue; may misrepresent FCF trajectory.",
  // Screens
  "missing_ebit": "EBIT missing; this screen cannot compute its result.",
  "missing_total_assets": "Total assets missing.",
  "missing_total_liabilities": "Total liabilities missing.",
  "missing_retained_earnings": "Retained earnings missing.",
  "missing_market_cap": "Market cap missing.",
  "missing_sales": "Sales missing.",
  "missing_balance_sheet": "Balance sheet items missing.",
  "missing_growth": "Growth metric unavailable.",
  "missing_per": "PER ratio missing.",
  "invested_capital_non_positive": "Invested capital ≤ 0; ROC cannot be computed.",
  "enterprise_value_non_positive": "Enterprise value ≤ 0; earnings yield cannot be computed.",
  "insufficient_cohort": "Peer cohort too small for ranking; screen returned null.",
  "insufficient_cohort_for_regression": "Cohort < 8; regression-adjusted multiples skipped.",
  "eva_not_applicable_for_financials": "EVA not methodologically applicable to banks/insurers.",
  "missing_debt_assumed_zero": "Total debt missing; EVA assumed zero (may understate invested capital).",
}
```

---

---

# Claude Design components (added per [20-claude-design-handoff.md](20-claude-design-handoff.md))

The Claude Design handoff introduced 13 new components and reclassified several from the original 18-component list. The deltas:

## Reclassified components from the original list

The Claude Design supersedes some of my speculative components. The new fundamentals UI uses the 5-tab structure (Thèse / Valorisation / Qualité & ROE / Estimations / Comparables) inside the unified `/signals` page, not the 7-tab standalone `/fundamentals` page I originally drafted.

| Original component | New status |
|---|---|
| `<DetailStrip>` (#7) | **Replaced** by `<ResearchTicket>` (#20) — richer, with BUY/HOLD/SELL recommendation card + conviction meter + analyst attribution |
| `<EnsembleSidebar>` (#5) | **Removed** — no permanent right rail in the Claude Design. Ensemble info lives inline in Valorisation tab via `<FootballField>` + methodology card stack |
| `<UniverseTreeTable>` (#6) | **Replaced** by `<UniverseScreen>` (#19a) — the Claude Design's research-overlay table with Rec / Rev / BUY-HOLD-SELL filter chips. Not grouped by market region in the prototype, but the column structure is different |
| `<DiagnosticPanel>` (#9) | **Broken up.** DuPont → `<DuPontDecomposition>` (#25). Piotroski + Accrual move to small cards inside Qualité tab |
| `<AnnualTable>` (#10) | **Replaced** by `<EstimationsTable>` (#27) — richer (3A + 3E forecast columns) |
| `<AssumptionEditor>` (#11) | **Merged.** The DCF assumptions card in Valorisation displays the values; a "Modifier" link opens a modal that uses the original `<AssumptionEditor>` (kept) |
| `<PillarRow>` (#8) | **Folded.** The 4-KPI grid at the top of Qualité tab carries the pillar scores. Drill-down moves into the DuPont decomposition |
| `<ScreenCard>` (#12) | **Removed as standalone.** Each screen (Altman / EVA / Magic Formula / PEG / Regression-adj) becomes a per-screen card embedded in Qualité or Comparables tab (see [16-institutional-screens.md](16-institutional-screens.md)) |

## Retained from original list

These align with the Claude Design and remain valid:

- `<MethodologyCard>` (#1) — used for **the per-method drill-down inside Valorisation tab**.
- `<ComputationStepsTable>` (#2) — inside each MethodologyCard.
- `<PerMultipleBreakdown>` (#3) — used inside `<MethodologyCard>` for relative multiples; also used inside Comparables tab.
- `<CrossMethodScatter>` (#4) — inline inside Valorisation tab (below the football field, optional condensed view).
- `<SensitivityHeatmap>` (#13) — updated to use oklch coloration per Claude Design.
- `<ZoneGauge>` (#14) — used for Altman Z, GARP, confidence ladders.
- `<ScoreBar>` (#15), `<Sparkline>` (#16), `<Chip>` (#17), `<TearSheet>` (#18) — unchanged.

## New components from Claude Design (#19–#31)

### 19. `<ModeSwitcher>`

Top-of-page mode selector with 3 pills: Technical / Fundamental / Quantitative.

**File:** `frontend/components/signals/mode-switcher.tsx`

**Props:**
```typescript
interface ModeSwitcherProps {
  mode: "technical" | "fundamental" | "quantitative";
  onChange: (mode: ModeSwitcherProps["mode"]) => void;
}
```

**Structure:** `.mode-bar` container with 3 `.mode-pill` children. Each pill contains `.mode-pill-icon` + `.mode-pill-text` (title + description). Active pill carries `.active` modifier.

**Pills:**

| Mode | Icon | Title | Description |
|---|---|---|---|
| `technical` | `Zap` | Analyse Technique | Indicateurs · WFO · Backtest |
| `fundamental` | `BarChart3` | Analyse Fondamentale | DCF · Qualité · Comparables |
| `quantitative` | `TrendingUp` | Analyse Quantitative | Stat-arb · Facteurs · Macro |

**Styling:** CSS reference in [20-claude-design-handoff.md](20-claude-design-handoff.md) §"Mode switcher".

**URL state:** `?mode=...` query param. Default `technical`.

### 19a. `<UniverseScreen>`

The left-rail universe panel for fundamentals (380px wide).

**File:** `frontend/components/signals/fundamental/universe-screen.tsx`

**Props:**
```typescript
interface UniverseScreenProps {
  rows: FundamentalUniverseRow[];
  selectedSymbol: string | null;
  onSelect: (symbol: string) => void;
}
```

**Structure:**
```html
<aside className="fund-univ">
  <div className="fund-univ-hdr">
    <div>Coverage · {N} titres   FY 2025E</div>
    <input placeholder="Rechercher un titre..." />
    <div className="seg">[Tous] [BUY] [HOLD] [SELL]</div>
    <select>Upside / Score / Conviction / Mkt Cap</select>
  </div>
  <table className="tbl">
    <thead><tr><th>Titre</th><th>Rec.</th><th>Score</th><th>Upside</th><th>Rev</th></tr></thead>
    <tbody>{rows.map(row => <UniverseRow ... />)}</tbody>
  </table>
  <footer>
    {n_buy} Buy · {n_hold} Hold · {n_sell} Sell   |   Upside moy. +X.X%
  </footer>
</aside>
```

**Row structure:** Each row is a `<tr>` with:
- Symbol (mono 11 weight 700, color `--pri-dim` when active) + sector (9px fg3, truncated) stacked vertically.
- Recommendation chip (BUY green / HOLD muted / SELL red): 9px weight 800 letter-spacing .06em, padding 2px 5px, radius 3px, oklch-tinted background.
- Score chip: mono 11 weight 700, color green if ≥70, red if ≤35, else fg2.
- Upside: mono weight 700, color pos/neg.
- Rev arrow: ▲ (pos), ▼ (neg), — (flat), font-size 10 centered.

Active row: tinted `oklch(0.94 .04 260 / .22)`, weight 600.

### 20. `<ResearchTicket>`

Research-ticket-grade header replacing the current DetailStrip.

**File:** `frontend/components/signals/fundamental/research-ticket.tsx`

**Props:**
```typescript
interface ResearchTicketProps {
  symbol: string;
  companyName: string;
  sector: string;
  region: string;
  capClass: string;          // "Large Cap" / "Mid Cap" / "Small Cap"
  currency: string;          // "MAD"
  freeFloatPct: number | null;
  currentPrice: number;
  asOfDate: string;          // "au 24 mai 2026"
  targetPrice: number;
  revisionDirection: "up" | "down" | "=";
  upsidePct: number;
  marketCapBn: number;
  recommendation: "BUY" | "HOLD" | "SELL";
  conviction: 1 | 2 | 3 | 4 | 5;
  analyst: string | null;
  analystVersion: string | null;
}
```

**Structure:** CSS reference in [20-claude-design-handoff.md](20-claude-design-handoff.md) §"Research Ticket header".

**Layout:** grid `1fr auto`, gap 24px.

**Left column (`rt-left`):**
- Name row: symbol large (22px weight 700) + co name (14px fg2) + meta chip (`<sector> · <region> · <capClass> · <currency>`).
- 4 price blocks (`rt-prices`):
  1. Cours actuel · {currentPrice mono 18 weight 700} · "au {asOfDate}"
  2. Objectif 12M · {targetPrice color `--pri-dim`} · "{arrow} dernière révision {haussière/baissière/inchangée}"
  3. Upside / Downside · {upsidePct color pos/neg} · "vs cours actuel"
  4. Capitalisation · {marketCapBn} Bn · "Free float ~{freeFloatPct}%"

**Right column (`rt-right`):** min-width 200px, padding-left 24px, border-left.
- Rec card (variant `buy|hold|sell`): label "Recommandation" + value (22px weight 800 colored) + conviction dots row.
- Below the card: analyst attribution row.

### 21. `<FootballField>`

SVG range chart showing valuation methods' price ranges + current/target lines.

**File:** `frontend/components/signals/fundamental/football-field.tsx`

**Props:**
```typescript
interface FootballFieldProps {
  methods: Array<{
    method: string;        // e.g. "DCF · FCFF" or "Ensemble pondéré"
    low: number;
    mid: number;
    high: number;
    isEnsemble?: boolean;  // styling differs for the ensemble row
  }>;
  currentPrice: number;
  targetPrice: number;
  currency?: string;
}
```

**Construction:** SVG layout per [20-claude-design-handoff.md](20-claude-design-handoff.md) §"Football Field SVG":
- viewBox: `0 0 720 {H}` where `H = methods.length × 30 + 70`.
- Padding: left 130 (for method labels), right 80.
- minV = min(allVals) × 0.94, maxV × 1.06.
- Per-row: method label + range bar (`<line>`) + mid-point dot + low/high labels.
- Current price line: vertical dashed (4 3) red, label at top.
- Target price line: vertical solid green, label at bottom.
- X-axis ticks: 5 evenly spaced, mono 9px.

Implementation: use vanilla SVG (React JSX inside SVG namespace). No charting library.

### 22. `<ScenarioCards>`

3-card grid showing bear/base/bull scenarios.

**File:** `frontend/components/signals/fundamental/scenario-cards.tsx`

**Props:**
```typescript
interface ScenarioCardsProps {
  scenarios: {
    bear: { probability: number; price: number; upside: number; drivers: string[] };
    base: { probability: number; price: number; upside: number; drivers: string[] };
    bull: { probability: number; price: number; upside: number; drivers: string[] };
  };
  currency?: string;
}
```

**Structure:** `.scn-grid` 3-column grid. Each `.scn-card` has variant `bear|base|bull` (different gradient bg).

Per card:
```
[BEAR · 25%]                P=0.25       ← header
158 MAD                                  ← price (mono 22 weight 700)
-12.7%                                   ← upside (mono 12 weight 600)
• Régulation 5G défavorable
• Concurrence accrue d'Inwi
• Dégradation FX MAD/USD                 ← drivers list (11px fg2)
```

Below the grid: expected-price line (right-aligned, 11px muted):
```
E[Prix] = 158·0.25 + 202·0.55 + 248·0.20 = **200.2 MAD** · ≈ objectif central
```

The bold expected price is computed live from the scenarios.

### 23. `<CatalystList>`

Timeline list of upcoming catalysts.

**File:** `frontend/components/signals/fundamental/catalyst-list.tsx`

**Props:**
```typescript
interface CatalystListProps {
  catalysts: Array<{
    date: string;          // "30 jul 2026"
    title: string;
    desc: string;
    importance: "high" | "medium" | "low";
  }>;
}
```

**Structure:** Each `.cat-item` is a grid `80px 1fr auto`:
- Date column (mono 11 weight 600 fg2).
- Title (12 weight 600 fg1) + desc (11 muted) stacked.
- Importance chip (10px weight 700 uppercase). Labels: "Élevé" / "Modéré" / "Faible". Color per `cat-imp-{high|medium|low}` from §2.

### 24. `<RiskRegister>`

Vertical list of risks with severity meters.

**File:** `frontend/components/signals/fundamental/risk-register.tsx`

**Props:**
```typescript
interface RiskRegisterProps {
  risks: Array<{
    category: string;       // "Réglementaire", "Concurrentiel", etc.
    text: string;
    severity: 1 | 2 | 3;    // 1 = low, 2 = medium, 3 = high
    direction: "Baissier" | "Haussier";
  }>;
}
```

**Structure:** Each `.risk-row` is a grid `110px 1fr 60px 70px`:
- Category (11px weight 600 fg2).
- Text (11px fg2 line-height 1.5).
- Severity meter: 3 vertical bars (6px × 14px). Bars are filled (`.on`) based on severity, tone class by severity level (`l` = low / yellow hue 80, `m` = medium / orange hue 50, `h` = high / red hue 25).
- Direction tag: 10px weight 700, color `--neg` for "Baissier" or `--pos` for "Haussier".

### 25. `<DuPontDecomposition>`

4-box layout showing Marge × Rotation × Levier = ROE.

**File:** `frontend/components/signals/fundamental/dupont-decomposition.tsx`

**Props:**
```typescript
interface DuPontDecompositionProps {
  netMargin: number;
  assetTurnover: number;
  equityMultiplier: number;
  reportedRoe: number;
  impliedRoe: number;
  peerMargin: number | null;
  peerAssetTurnover: number | null;
  peerLeverage: number | null;
  peerRoe: number | null;
  interpretation: string;    // "Lecture :" paragraph
}
```

**Structure:** `.dp-row` flex container with 4 `.dp-box` + 3 `.dp-op` operators (`×`, `×`, `=`).

Each `.dp-box`:
- Label (10px UPPER 700 fg3).
- Value (mono 22 weight 700).
- Peer comparison line (10px muted): "Peers MENA : X · Δ Y bps".
- Mini bar fill (4px height).

Result box (rightmost): `.dp-box.result` modifier — tinted `oklch(0.94 .04 260 / .25)`, primary border, value color `--pri-dim`.

Below the row: "Lecture :" interpretive paragraph in a sub-card (bg2, border, padding 10px 14px, 11px fg2 line-height 1.5). The "Lecture :" prefix is bold `--fg1`.

### 26. `<PeerComparisonBar>`

Horizontal comparison bar with peer marker.

**File:** `frontend/components/signals/fundamental/peer-comparison-bar.tsx`

**Props:**
```typescript
interface PeerComparisonBarProps {
  rows: Array<{
    label: string;           // "ROIC", "Marge opér.", etc.
    ownValue: string;        // "18.4%"
    peerValue: string;       // "14.2%"
    percentile: number;      // 0..1, position along bar
    direction: "pos" | "neg" | "neu";  // bar color: pos=green (own > peer is good)
  }>;
}
```

**Structure:** Each row is a grid `160px 1fr 70px 70px`:
- Label (12 weight 500 fg2).
- `.peer-bar-wrap` with `.peer-bar` track and `.peer-bar-fill` filled to `percentile × 100%`, with a `.peer-bar-mark` vertical line at the peer-median position (opacity 0.4).
- Own value (mono 11 weight 700, color pos/neg/fg1 per direction).
- Peer value (mono 10 fg3): "peers · {value}".

Bar fill color:
- `direction === "pos"` → `--pos`.
- `direction === "neg"` → `--neg`.
- `direction === "neu"` → `--primary`.

### 27. `<EstimationsTable>`

P&L table with 3 actual years + 3 estimated years.

**File:** `frontend/components/signals/fundamental/estimations-table.tsx`

**Props:**
```typescript
interface EstimationsTableProps {
  years: string[];          // ["2022A", "2023A", "2024A", "2025E", "2026E", "2027E"]
  rows: Array<{
    label: string;
    values: string[];       // formatted strings, length === years.length
    format: "bn" | "pct" | "mad" | "x";
    isSubRow?: boolean;     // margin / growth / payout rows
  }>;
  currency?: string;
}
```

**Header:** Estimated columns (those ending with "E") shaded `oklch(0.94 .04 260 / .25)` with color `--pri-dim`.

**Body:**
- Main rows: weight 600, font-size 12, color `--fg1`.
- Sub-rows (`isSubRow=true`): weight 400, font-size 11, color `--fg3`, padding-left 22px, label is indented.
- Sub-row values colored by sign prefix: starts with `+` → `--pos`, `-` → `--neg`, else `--fg2`.
- Estimated cells (year column ends with "E"): shaded `oklch(0.94 .04 260 / .18)`.

**Card header aside (legend):** 2 chips with swatches: `[Actuel]` (bg2) and `[Estimé]` (oklch tinted).

### 28. `<ConsensusVsHouse>`

Comparison table of consensus market estimates vs the house's estimates.

**File:** `frontend/components/signals/fundamental/consensus-vs-house.tsx`

**Props:**
```typescript
interface ConsensusVsHouseProps {
  rows: Array<{
    label: string;
    consensusValue: string;     // formatted
    houseValue: string;         // formatted
    diffPct: string;            // formatted e.g. "+0.9%"
    position: "Au-dessus" | "En-dessous";
  }>;
  consensusCount?: number;     // for header "Consensus (n=14)"
  fiscalYear?: string;         // for header "FY 2026E"
}
```

**Columns:** Métrique | Consensus (n=14) | Maison | Écart | Position.

**Styling:**
- Maison column: weight 700.
- Écart column: weight 700, color `--pos` if starts with `+`, else `--neg`.
- Position column: 11px weight 600, color `--pos` for "Au-dessus", `--neg` for "En-dessous".

### 29. `<ComparablesTable>`

MENA + global peer comparables table with relative coloration.

**File:** `frontend/components/signals/fundamental/comparables-table.tsx`

**Props:**
```typescript
interface ComparablesTableProps {
  peers: Array<{
    sym: string;
    name: string;
    country: string;
    marketCap: number | null;
    pe: number;
    evEbitda: number;
    pbv: number;
    roe: number;
    divYield: number;
    growthCa: number;
    isSelf?: boolean;     // the target symbol — tinted highlight
    isMedian?: boolean;   // the median row — italic muted
  }>;
}
```

**Columns:** Ticker | Nom | Pays | Mkt Cap (Bn $) | P/E | EV/EBITDA | P/B | ROE | Div Yield | g CA (min-width 880px, table overflow-x auto).

**Row tinting:**
- Self-row: `background: oklch(0.94 .04 260 / .22)`, weight 600, ticker color `--pri-dim`.
- Median row: `background: var(--bg2)`, italic, color `--fg3`.

**Cell coloring (vs median, computed live):**
- `lower="bad"` columns (PE, EV/EBITDA, P/B): green if value < median, red if value > median.
- `lower="good"` columns (ROE, DivYield, gCa): green if value > median, red if value < median.
- `|diff| < 5%`: default color `--fg1`.
- `|diff| > 10%`: weight 700.

### 30. `<RelativeValuationTiles>`

3-tile grid at the bottom of Comparables tab.

**File:** `frontend/components/signals/fundamental/relative-valuation-tiles.tsx`

**Props:**
```typescript
interface RelativeValuationTilesProps {
  decoteVsMedian: { value: number; subText: string };
  decoteVsHistorical5y: { value: number; subText: string };
  totalReturnEst: { value: number; subText: string };
}
```

**Structure:** `.g3` grid (3 columns gap 8px). Each tile = `.card` with padding 14px 16px:
- Label (10px UPPER 700 letter-spacing .08em fg3).
- Value (mono 22 weight 700, color `--pos` or `--neg` based on metric).
- Sub-text (11px muted).

### 31. `<TweaksPanel>`

Floating settings panel (bottom-right corner).

**File:** `frontend/components/shell/tweaks-panel.tsx`

**Props:**
```typescript
interface TweaksPanelProps {
  open: boolean;
  onClose: () => void;
  preferences: {
    dark: boolean;
    sidebarWidth: 200 | 240 | 280;
    defaultMode: "technical" | "fundamental" | "quantitative";
  };
  onPreferenceChange: <K extends keyof Preferences>(key: K, value: Preferences[K]) => void;
}
```

**Structure:** Floating panel `position: fixed; bottom: 20px; right: 20px; width: 230px`:
- Header: "Tweaks" label + close button.
- Body: 3 segmented controls:
  1. Theme: ☀ Clair / ☾ Sombre
  2. Largeur sidebar: S / M / L (200 / 240 / 280px)
  3. Mode par défaut: TA / FA / QA

Persistence: server-backed via `frontend/app/api/account/preferences/dashboard/route.ts` (extend existing schema; do NOT use localStorage). On change, optimistic update + server PUT.

Open trigger: `Cmd/Ctrl + ,` keyboard shortcut, or a small gear icon in the page header.

## Implementation order — updated for Claude Design

Phased per [14-implementation-roadmap.md](14-implementation-roadmap.md) Phase F (D5.0 → D5.9):

1. **D5.0 — Foundation:** DM Sans/Mono fonts + oklch tokens + Chip + ScoreBar + Sparkline (atoms).
2. **D5.1 — App shell + mode switcher:** `<ModeSwitcher>` (#19), `/signals` route restructure, URL state.
3. **D5.2 — Fundamental shell:** `<UniverseScreen>` (#19a) + `<ResearchTicket>` (#20) + 5-tab nav skeleton.
4. **D5.3 — Thèse tab:** `<ScenarioCards>` (#22), `<CatalystList>` (#23), `<RiskRegister>` (#24).
5. **D5.4 — Valorisation tab (user's chief pain point):** `<FootballField>` (#21), `<MethodologyCard>` (#1) reused inside expandable rows, `<ComputationStepsTable>` (#2), per-model step traces, `<SensitivityHeatmap>` (#13 updated).
6. **D5.5 — Qualité tab:** `<DuPontDecomposition>` (#25), `<PeerComparisonBar>` (#26), Altman card + EVA card (from Addendum #3 backend).
7. **D5.6 — Estimations tab:** `<EstimationsTable>` (#27), `<ConsensusVsHouse>` (#28).
8. **D5.7 — Comparables tab:** `<ComparablesTable>` (#29), `<RelativeValuationTiles>` (#30), Magic Formula + PEG + regression-adj cards (from Addendum #3 backend).
9. **D5.8 — Quantitative view:** `<QuantitativeView>` per `sr-quantitative.jsx` spec (outside fundamentals-layer scope).
10. **D5.9 — Polish:** `<TweaksPanel>` (#31), `<TearSheet>` (#18) print stylesheet, accessibility pass.

Each PR ships behind `NEXT_PUBLIC_FUNDAMENTALS_V2_UI=true` until D5.9 ships.

---

## Layout in `15-ui-goals-and-design.md`

How these components compose into the actual page is described in `15-ui-goals-and-design.md`. This document is the **per-component contract**; the layout file is the **per-tab assembly**.

## Implementation order

Phased per `14-implementation-roadmap.md`:

1. **Foundation** (PR-1): tokens (17), Chip (17), ScoreBar (15), Sparkline (16), Section helper.
2. **Layout shell** (PR-2): UniverseTreeTable (6), DetailStrip (7), EnsembleSidebar (5), tab nav.
3. **Methodology cards** (PR-3): MethodologyCard (1), ComputationStepsTable (2), warning-dictionary, model-step-traces for 7 models. **This is the user's biggest pain point — surfaces inputs/outputs/steps for every valuation model.**
4. **Cross-method viz** (PR-4): CrossMethodScatter (4), PerMultipleBreakdown (3).
5. **Pillar drilldowns + diagnostics** (PR-5): PillarRow (8), DiagnosticPanel (9).
6. **Financials + Assumptions** (PR-6): AnnualTable (10), AssumptionEditor (11).
7. **Screens** (PR-7, depends on Addendum #3 backend): ScreenCard (12), ZoneGauge (14), regression viz.
8. **Sensitivity + Tear-sheet** (PR-8): SensitivityHeatmap (13), TearSheet (18), print stylesheet.

Each PR ships behind `NEXT_PUBLIC_FUNDAMENTALS_V2_UI=true` flag until all 8 land.

## See also

- [15-ui-goals-and-design.md](15-ui-goals-and-design.md) — page-level rebuild.
- [17-ui-design-language.md](17-ui-design-language.md) — tokens.
- [19-ui-tear-sheet-spec.md](19-ui-tear-sheet-spec.md) — print layout.
- [16-institutional-screens.md](16-institutional-screens.md) — backend for screen cards.
