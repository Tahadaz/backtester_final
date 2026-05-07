# Codex Task: Cleanup — Legend Update + Documentation

## Goal

1. Replace the generic chart legend with family-specific legend items
2. Update documentation to reflect the new per-family visual encoding

## File 1: `quant-backtesting-frontend/components/strategy/signal-zone-chart.tsx`

### Replace the legend

Find the legend block (near the bottom of the JSX return):

```tsx
      {/* Zone legend */}
      <div className="flex items-center gap-3 text-[9px] text-muted-foreground">
        <div className="flex items-center gap-1">
          <span className="inline-block h-2 w-3 rounded-sm bg-green-500/30" />
          Zone de support
        </div>
        <div className="flex items-center gap-1">
          <span className="inline-block h-2 w-3 rounded-sm bg-red-500/30" />
          Zone de resistance
        </div>
        <span className="text-[8px] opacity-50">
          Intensite = nombre de familles en accord
        </span>
      </div>
```

Replace with:

```tsx
      {/* Family layer legend */}
      <div className="flex flex-wrap items-center gap-3 text-[9px] text-muted-foreground">
        {enabledFamilies.includes("sma") && (
          <div className="flex items-center gap-1">
            <span className="inline-block h-0.5 w-3 rounded-full bg-green-500" />
            <span>Tendance (SMA)</span>
          </div>
        )}
        {enabledFamilies.includes("macd") && (
          <div className="flex items-center gap-1">
            <span className="text-green-500 text-[8px]">&#9650;</span>
            <span className="text-red-500 text-[8px]">&#9660;</span>
            <span>Momentum (MACD)</span>
          </div>
        )}
        {enabledFamilies.includes("rsi") && (
          <div className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm bg-orange-500/30" />
            <span>Oscillation (RSI 0-100)</span>
          </div>
        )}
        {enabledFamilies.includes("obv") && (
          <div className="flex items-center gap-1">
            <span className="inline-block h-2 w-1.5 rounded-sm bg-green-500/50" />
            <span className="inline-block h-2 w-1.5 rounded-sm bg-red-500/50" />
            <span>Volume (OBV)</span>
          </div>
        )}
      </div>
```

### Also update the title

Find the chart header:

```tsx
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Zones de signal - {data.symbol}
        </span>
```

Change to:

```tsx
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Signal — {data.symbol}
        </span>
```

### Remove unused constants

If `ZONE_COLORS` is no longer used anywhere in the file (the old zone shading was replaced with RSI-specific shading), remove:

```typescript
const ZONE_COLORS = {
  support: "34,197,94",
  resistance: "239,68,68",
}
```

Also remove `FAMILY_LINE_COLORS` if no longer referenced (each family now has its color inline in its render function).

## File 2: `docs/signal-generation/10-methodology-and-sources.md`

### Replace section 7

Find section `### 7. Indicator Selection` (around line 127). Replace the entire section (up to but not including `### 8. Horizon-Aware Parameter Scaling`) with:

```markdown
### 7. Indicator Selection — Four Pillars of Trend Following

**Choice**: Decompose trend following into 4 orthogonal dimensions, each captured by a classical indicator family.

| Pillar | Family | What It Detects | Visual Encoding |
|--------|--------|----------------|-----------------|
| **Direction** | SMA | Is price trending up or down? | SMA curves on price chart |
| **Acceleration** | MACD | Is the trend strengthening or weakening? | Arrows at crossover points |
| **Exhaustion** | RSI | Has price stretched too far? | Overbought/oversold bands (0-100 axis) |
| **Confirmation** | OBV | Does volume confirm the move? | Colored volume bars |

**Why these four?**
Each captures a dimension the others cannot:
- SMA sees direction but not speed — MACD fills this gap
- SMA and MACD are trend-following — RSI provides mean-reversion counterbalance
- All three are price-based — OBV adds volume as an independent information source

This decomposition follows Elder's "Triple Screen" principle (Elder 1993): use indicators from different categories to avoid redundant confirmation.

> *"The first rule of using indicators is that you should never use two indicators from the same group. Combining two trend-following indicators... or two oscillators is redundant — they just confirm each other's blind spots."* — Alexander Elder (1993), *Trading for a Living*

| Family | Category | Justification |
|--------|----------|---------------|
| SMA | Trend | The simplest and most robust trend indicator. Price > MA indicates uptrend. Used by practitioners for decades (Murphy 1999). |
| MACD | Momentum | Captures trend acceleration via short/long EMA difference. More responsive than SMA to momentum changes (Appel 2005). |
| RSI | Oscillator | Measures relative strength of recent gains vs losses. Captures mean-reversion at extremes (Wilder 1978). |
| OBV | Volume | Accumulates volume directionally. Provides independent (non-price) confirmation of trends (Granville 1963). |

**Why not more families?**
Each additional family adds 30 candidates to the multiple testing burden. We start with 4 well-established families and will add more only if there is clear economic justification.

**Planned additions** (not yet implemented):
- Bollinger Bands — volatility-based mean-reversion
- Ichimoku — Japanese cloud-based trend/support/resistance
- Stochastic VWAP — volume-weighted price oscillator
```

## File 3: `docs/strategy-layer/05-signal-selection-layer.md`

### Update the visual encoding section

Find the `### Visual encoding` subsection inside the "Signal Zone Chart" section (around lines 125-129). Replace everything from `### Visual encoding` up to (but not including) `### Design principle` with:

```markdown
### Visual encoding (per-family layers)

Each family uses a distinct visual language that reflects what it detects:

- **SMA (Trend)**: Multiple SMA curves on the price chart, one per representative variant. Line opacity proportional to reliability weight. Shows the trend direction directly on price.
- **MACD (Momentum)**: Directional arrows at crossover points. Green up-arrow = bullish crossover (momentum accelerating). Red down-arrow = bearish crossover (momentum fading). Arrow opacity proportional to weight. Stacking at same bar = consensus.
- **RSI (Stretch)**: RSI oscillator lines on a secondary 0-100 Y-axis overlaid on the main chart. Horizontal threshold lines (e.g., 30/70) with red shading above overbought and green shading below oversold. Per-representative shading with additive opacity at overlaps.
- **OBV (Volume)**: Volume bars at chart bottom colored by accumulation/distribution consensus. Green = accumulation (OBV > EMA), red = distribution, gray = neutral. Intensity proportional to weighted consensus across representatives.

All layers are independently toggleable. When a family is toggled off, its visual elements (lines, arrows, shading, axes) disappear entirely.
```

### Update the "Not yet implemented" section

Find `### Not yet implemented` in the same file. Remove or update:
```
- oscillator sub-panes for MACD/RSI/OBV (indicators with `type: secondary_yaxis` are returned by the backend but not rendered below the chart)
```

Replace with:
```
- per-family layers fully implemented: SMA curves, MACD arrows, RSI bands, OBV colored bars
```

Keep the other not-yet-implemented items if they still apply.

## Do NOT modify

- The render functions from previous phases
- Any backend code
- Any test files

## Verification

1. `npx tsc --noEmit` — zero type errors
2. Visual: legend shows only the families that are currently enabled with appropriate icons
3. Docs: `10-methodology-and-sources.md` section 7 reflects the four-pillar decomposition with Elder quote
4. Docs: `05-signal-selection-layer.md` reflects the per-family visual encoding
