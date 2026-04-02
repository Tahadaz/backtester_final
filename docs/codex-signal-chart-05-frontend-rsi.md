# Codex Task: Frontend — RSI Layer (Secondary Axis + Canvas Shading)

## Goal

Add RSI visualization to the signal zone chart:
- RSI oscillator lines on a **secondary 0-100 Y-axis** overlaid on the main chart (NOT a sub-panel)
- Horizontal threshold lines (overbought/oversold) per representative
- Red shading above overbought line, green shading below oversold line
- Shading opacity proportional to representative weight
- Overlapping zones from multiple representatives intensify additively
- When RSI is toggled off, ALL RSI elements AND the secondary axis disappear

## Prerequisite

Phases 01-04 must be completed first.

## File to modify

`quant-backtesting-frontend/components/strategy/signal-zone-chart.tsx`

## Step 1: Add RSI render function

Add alongside the other render functions:

```typescript
interface RsiSeriesRef {
  series: ReturnType<IChartApi["addSeries"]>
  rep: { weight: number; indicator: Record<string, any> }
}

function renderRsiLayer(
  chart: IChartApi,
  famData: { representatives: Array<{ weight: number; indicator?: Record<string, any> | null }> },
  bars: Array<{ date: string }>,
): RsiSeriesRef[] {
  const rsiRefs: RsiSeriesRef[] = []

  for (const rep of famData.representatives) {
    if (!rep.indicator || rep.indicator.type !== "secondary_yaxis") continue
    if (!rep.indicator.values) continue

    const opacity = (0.3 + rep.weight * 0.7).toFixed(2)
    const series = chart.addSeries(LineSeries, {
      color: `rgba(249, 115, 22, ${opacity})`,
      lineWidth: 1,
      priceScaleId: "rsi-scale",
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // Set RSI data (0-100 values)
    const vals = rep.indicator.values as (number | null)[]
    const lineData: LineData[] = []
    for (let i = 0; i < bars.length && i < vals.length; i++) {
      if (vals[i] != null) {
        lineData.push({ time: toTime(bars[i].date), value: vals[i]! })
      }
    }
    series.setData(lineData)

    // Threshold lines
    const thresholds = rep.indicator.thresholds as [number, number]
    if (thresholds) {
      const [oversold, overbought] = thresholds
      series.createPriceLine({
        price: overbought,
        color: "rgba(239, 68, 68, 0.4)",
        lineWidth: 1,
        lineStyle: 2, // Dashed
        axisLabelVisible: false,
        title: "",
      })
      series.createPriceLine({
        price: oversold,
        color: "rgba(34, 197, 94, 0.4)",
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: false,
        title: "",
      })
    }

    rsiRefs.push({ series, rep: { weight: rep.weight, indicator: rep.indicator } })
  }

  // Configure RSI price scale — occupies bottom ~30% of chart
  if (rsiRefs.length > 0) {
    chart.priceScale("rsi-scale").applyOptions({
      scaleMargins: { top: 0.7, bottom: 0 },
      drawTicks: false,
    })
  }

  return rsiRefs
}
```

## Step 2: Call renderRsiLayer in the main useEffect

In the family-specific layers section, add:

```typescript
    // RSI: oscillator on secondary axis
    let rsiSeriesRefs: RsiSeriesRef[] = []
    if (enabledFamilies.includes("rsi") && data.families.rsi) {
      rsiSeriesRefs = renderRsiLayer(chart, data.families.rsi, data.bars)
    }
```

## Step 3: Replace the old canvas zone shading

Find the existing `drawZones` function (around lines 178-229). It currently draws full-height green/red columns based on family scores. **Replace the entire body** of `drawZones` with RSI threshold shading:

```typescript
    const drawZones = () => {
      const zoneCanvas = zoneCanvasRef.current
      const wrapper = wrapperRef.current
      if (!zoneCanvas || !wrapper) return

      const dpr = window.devicePixelRatio || 1
      const width = wrapper.clientWidth
      const chartHeight = wrapper.clientHeight
      if (width === 0 || chartHeight === 0) return

      if (
        zoneCanvas.width !== Math.round(width * dpr) ||
        zoneCanvas.height !== Math.round(chartHeight * dpr)
      ) {
        zoneCanvas.width = Math.round(width * dpr)
        zoneCanvas.height = Math.round(chartHeight * dpr)
      }
      zoneCanvas.style.width = `${width}px`
      zoneCanvas.style.height = `${chartHeight}px`

      const ctx = zoneCanvas.getContext("2d")
      if (!ctx) return

      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.clearRect(0, 0, zoneCanvas.width, zoneCanvas.height)
      ctx.scale(dpr, dpr)

      const timeScale = chart.timeScale()

      // RSI threshold shading
      for (const { series, rep } of rsiSeriesRefs) {
        const thresholds = rep.indicator.thresholds as [number, number] | undefined
        if (!thresholds) continue
        const [oversold, overbought] = thresholds
        const shadeOpacity = (0.03 + rep.weight * 0.07).toFixed(3)

        const overboughtY = series.priceToCoordinate(overbought)
        const oversoldY = series.priceToCoordinate(oversold)

        const vals = rep.indicator.values as (number | null)[]

        for (let i = 0; i < data.bars.length && i < vals.length; i++) {
          const rsiVal = vals[i]
          if (rsiVal == null) continue

          const x = timeScale.timeToCoordinate(toTime(data.bars[i].date))
          if (x === null) continue

          const nextX =
            i + 1 < data.bars.length
              ? timeScale.timeToCoordinate(toTime(data.bars[i + 1].date))
              : null
          const barWidth = nextX !== null ? Math.max(nextX - x, 1) : 4

          if (rsiVal > overbought && overboughtY !== null) {
            const rsiY = series.priceToCoordinate(rsiVal)
            if (rsiY !== null) {
              ctx.fillStyle = `rgba(239, 68, 68, ${shadeOpacity})`
              ctx.fillRect(x, Math.min(rsiY, overboughtY), barWidth, Math.abs(overboughtY - rsiY))
            }
          } else if (rsiVal < oversold && oversoldY !== null) {
            const rsiY = series.priceToCoordinate(rsiVal)
            if (rsiY !== null) {
              ctx.fillStyle = `rgba(34, 197, 94, ${shadeOpacity})`
              ctx.fillRect(x, Math.min(rsiY, oversoldY), barWidth, Math.abs(oversoldY - rsiY))
            }
          }
        }
      }
    }
```

**Important:** The `rsiSeriesRefs` variable must be in scope when `drawZones` is defined. Since both are inside the same `useEffect`, this works naturally — just make sure `renderRsiLayer` is called BEFORE `drawZones` is defined.

## Do NOT modify

- The SMA/OBV/MACD render functions from previous phases
- The candlestick series setup
- The ResizeObserver, cleanup, or chart creation logic
- Any other file

## Verification

Run `npx tsc --noEmit` from `quant-backtesting-frontend/`. Zero type errors.

Visual checks:
1. RSI enabled: orange RSI lines appear, dashed threshold lines visible, red shading above overbought, green shading below oversold
2. Multiple RSI representatives: overlapping shading zones show intensified color
3. RSI disabled: no RSI lines, no threshold lines, no shading, no secondary 0-100 axis
4. RSI + SMA + OBV + MACD all enabled: all four layers coexist without conflict
