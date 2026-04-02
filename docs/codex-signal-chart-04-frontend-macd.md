# Codex Task: Frontend — MACD Arrows Layer

## Goal

Add MACD crossover arrow rendering to the signal zone chart. Green up-arrows at bullish crossovers, red down-arrows at bearish crossovers. Arrow opacity proportional to representative weight.

## Prerequisite

Phases 01 (backend) and 02 (schema) must be completed first. The backend now returns `indicator.crossovers` for MACD representatives.

## File to modify

`quant-backtesting-frontend/components/strategy/signal-zone-chart.tsx`

## Step 1: Add MACD render function

Add this function alongside the existing `renderSmaLayer` and `renderObvLayer`:

```typescript
function renderMacdMarkers(
  famData: { representatives: Array<{ weight: number; label: string; indicator?: Record<string, any> | null }> },
  bars: Array<{ date: string }>,
): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = []

  for (const rep of famData.representatives) {
    const crossovers = rep.indicator?.crossovers as
      | Array<{ bar_index: number; direction: string }>
      | undefined
    if (!crossovers) continue

    const alpha = Math.max(0.4, rep.weight).toFixed(2)

    for (const xo of crossovers) {
      if (xo.bar_index < 0 || xo.bar_index >= bars.length) continue
      const isBullish = xo.direction === "bullish"
      markers.push({
        time: toTime(bars[xo.bar_index].date),
        position: isBullish ? "belowBar" : "aboveBar",
        color: isBullish
          ? `rgba(34, 197, 94, ${alpha})`
          : `rgba(239, 68, 68, ${alpha})`,
        shape: isBullish ? "arrowUp" : "arrowDown",
        text: rep.label,
      })
    }
  }

  return markers
}
```

## Step 2: Integrate MACD markers with existing markers

Find the existing entry/exit markers block (around lines 147-175). It builds a `markers` array and calls `createSeriesMarkers(candle, markers)`.

Modify to merge MACD markers before the `createSeriesMarkers` call:

```typescript
    // Entry/exit markers (existing code — keep as-is)
    const markers: SeriesMarker<Time>[] = []
    for (const t of data.transitions) {
      if (!enabledFamilies.includes(t.family)) continue
      // ... existing entry/exit logic ...
    }

    // MACD crossover arrows
    if (enabledFamilies.includes("macd") && data.families.macd) {
      const macdMarkers = renderMacdMarkers(data.families.macd, data.bars)
      markers.push(...macdMarkers)
    }

    // Sort all markers by time (required by lightweight-charts)
    markers.sort((a, b) => (a.time as string).localeCompare(b.time as string))
    createSeriesMarkers(candle, markers)
```

## Step 3: Add MACD to family rendering section

In the family-specific layers section (added in phase 03), the MACD rendering is handled by the marker merge above (Step 2). No separate `chart.addSeries` call needed for MACD — it uses `createSeriesMarkers` on the candlestick series.

Just add a comment for clarity in the family layers section:

```typescript
    // MACD: crossover arrows (handled via markers above)
```

## Do NOT modify

- The SMA/OBV render functions from phase 03
- The candlestick series setup
- Any other file

## Verification

Run `npx tsc --noEmit` from `quant-backtesting-frontend/`. Zero type errors.
Visual check: when MACD is enabled, green up-arrows should appear at bullish crossover points and red down-arrows at bearish crossover points. Arrow opacity should vary by representative weight. Multiple representatives' arrows can appear at the same or nearby bars.
