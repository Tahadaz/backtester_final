# Codex Task: Frontend — SMA and OBV Layers

## Goal

Refactor `signal-zone-chart.tsx` to render SMA and OBV families with their distinct visualizations:
- **SMA**: Multiple SMA curves (one per representative), opacity = weight
- **OBV**: Colored volume histogram bars (green = accumulation, red = distribution, gray = neutral)

## File to modify

`quant-backtesting-frontend/components/strategy/signal-zone-chart.tsx`

## Current state (what to replace)

Lines 117-143 contain a generic overlay loop that draws ONE line per family:

```typescript
    // Indicator overlays (e.g. SMA line on price pane)
    for (const fam of enabledFamilies) {
      const famData = data.families[fam]
      if (!famData) continue

      const indicator = famData.indicator
      if (indicator && indicator.type === "overlay" && indicator.values) {
        const lineColor = FAMILY_LINE_COLORS[fam] || "#888"
        const lineSeries = chart.addSeries(LineSeries, {
          color: lineColor,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        })

        const lineData: LineData[] = []
        const vals = indicator.values as (number | null)[]
        for (let i = 0; i < data.bars.length && i < vals.length; i++) {
          if (vals[i] != null) {
            lineData.push({
              time: toTime(data.bars[i].date),
              value: vals[i]!,
            })
          }
        }
        lineSeries.setData(lineData)
      }
    }
```

**Replace this entire block** with family-specific rendering calls.

## Step 1: Add imports

Add `HistogramSeries` to the imports from `lightweight-charts`:

```typescript
import {
  createChart,
  createSeriesMarkers,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type CandlestickData,
  type LineData,
  type Time,
  type SeriesMarker,
} from "lightweight-charts"
```

## Step 2: Add SMA render function

Add this function BEFORE the component definition (after the `toTime` helper):

```typescript
function renderSmaLayer(
  chart: IChartApi,
  famData: { representatives: Array<{ weight: number; indicator?: Record<string, any> | null }> },
  bars: Array<{ date: string }>,
) {
  for (const rep of famData.representatives) {
    if (!rep.indicator) continue
    const ind = rep.indicator
    const opacity = (0.3 + rep.weight * 0.7).toFixed(2)

    if (ind.type === "overlay" && ind.values) {
      const series = chart.addSeries(LineSeries, {
        color: `rgba(34, 197, 94, ${opacity})`,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      const lineData: LineData[] = []
      const vals = ind.values as (number | null)[]
      for (let i = 0; i < bars.length && i < vals.length; i++) {
        if (vals[i] != null) {
          lineData.push({ time: toTime(bars[i].date), value: vals[i]! })
        }
      }
      series.setData(lineData)
    }

    if (ind.type === "overlay_dual") {
      // Fast SMA line
      if (ind.fast) {
        const fastSeries = chart.addSeries(LineSeries, {
          color: `rgba(34, 197, 94, ${opacity})`,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
        const fastData: LineData[] = []
        const fVals = ind.fast as (number | null)[]
        for (let i = 0; i < bars.length && i < fVals.length; i++) {
          if (fVals[i] != null) {
            fastData.push({ time: toTime(bars[i].date), value: fVals[i]! })
          }
        }
        fastSeries.setData(fastData)
      }
      // Slow SMA line (slightly more transparent)
      if (ind.slow) {
        const slowOpacity = (0.2 + rep.weight * 0.5).toFixed(2)
        const slowSeries = chart.addSeries(LineSeries, {
          color: `rgba(34, 197, 94, ${slowOpacity})`,
          lineWidth: 1,
          lineStyle: 2, // dashed to distinguish from fast
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
        const slowData: LineData[] = []
        const sVals = ind.slow as (number | null)[]
        for (let i = 0; i < bars.length && i < sVals.length; i++) {
          if (sVals[i] != null) {
            slowData.push({ time: toTime(bars[i].date), value: sVals[i]! })
          }
        }
        slowSeries.setData(slowData)
      }
    }
  }
}
```

## Step 3: Add OBV render function

Add after the SMA function:

```typescript
function renderObvLayer(
  chart: IChartApi,
  famData: { representatives: Array<{ weight: number; indicator?: Record<string, any> | null }> },
  bars: Array<{ date: string; volume?: number | null }>,
) {
  const histSeries = chart.addSeries(HistogramSeries, {
    priceScaleId: "volume",
    lastValueVisible: false,
    priceLineVisible: false,
  })

  chart.priceScale("volume").applyOptions({
    scaleMargins: { top: 0.85, bottom: 0 },
    drawTicks: false,
  })

  const histData = bars.map((b, i) => {
    let accWeight = 0
    let distWeight = 0
    for (const rep of famData.representatives) {
      const barSignals = rep.indicator?.bar_signals as string[] | undefined
      if (!barSignals) continue
      const sig = barSignals[i]
      if (sig === "accumulation") accWeight += rep.weight
      else if (sig === "distribution") distWeight += rep.weight
    }

    let color = "rgba(161, 161, 170, 0.3)" // neutral gray
    if (accWeight > distWeight) {
      const intensity = Math.min(0.8, 0.3 + accWeight * 0.5).toFixed(2)
      color = `rgba(34, 197, 94, ${intensity})`
    } else if (distWeight > accWeight) {
      const intensity = Math.min(0.8, 0.3 + distWeight * 0.5).toFixed(2)
      color = `rgba(239, 68, 68, ${intensity})`
    }

    return { time: toTime(b.date), value: (b.volume ?? 0) as number, color }
  })

  histSeries.setData(histData)
}
```

## Step 4: Replace the generic overlay loop

Remove lines 117-143 (the `// Indicator overlays` block). Replace with:

```typescript
    // ── Family-specific layers ──────────────────────────────────
    // SMA: per-representative curves on price pane
    if (enabledFamilies.includes("sma") && data.families.sma) {
      renderSmaLayer(chart, data.families.sma, data.bars)
    }

    // OBV: colored volume histogram
    if (enabledFamilies.includes("obv") && data.families.obv) {
      renderObvLayer(chart, data.families.obv, data.bars)
    }
```

MACD and RSI layers will be added in later phases. For now, if MACD or RSI families have indicator data, they simply won't render overlay lines (which is fine — they'll get their own rendering in subsequent tasks).

## Do NOT modify

- The candlestick series setup (lines 95-114) — keep as-is
- The entry/exit markers (lines 147-175) — keep for now, will be updated in MACD phase
- The canvas zone shading (lines 178-229) — keep for now, will be replaced in RSI phase
- The legend (lines 302-314) — keep for now, will be updated in cleanup phase
- Any other file

## Verification

Run `npx tsc --noEmit` from `quant-backtesting-frontend/`. Zero type errors.
Visual check: when SMA is enabled, multiple green SMA curves should appear on the price chart with varying opacity. When OBV is enabled, volume bars at the bottom should be colored green/red/gray.
