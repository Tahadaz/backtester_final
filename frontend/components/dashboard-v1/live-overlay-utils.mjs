function hasOwn(value, key) {
  return Object.prototype.hasOwnProperty.call(value ?? {}, key)
}

export function applyDashboardLiveOverlays(stocks, liveOverlayMap = {}, liveQuoteMap = {}, taxonomyMap = {}) {
  return (stocks ?? []).map((stock) => {
    const symbol = String(stock?.symbol ?? "").toUpperCase()
    const overlay = liveOverlayMap?.[symbol]
    const quote = overlay?.live_quote ?? liveQuoteMap?.[symbol] ?? null
    const quoteLast = quote?.is_fresh && quote.last_price != null ? quote.last_price : null
    const overlayPerformance = overlay?.performance
    const taxonomy = taxonomyMap?.[symbol]

    return {
      ...stock,
      last_price: overlay?.last_price ?? quoteLast ?? stock.last_price,
      prev_close: overlay?.prev_close ?? stock.prev_close,
      var1j_pct: overlay?.var1j_pct ?? stock.var1j_pct,
      performance: overlayPerformance
        ? { ...(stock.performance ?? {}), ...overlayPerformance }
        : stock.performance,
      best_signal: hasOwn(overlay, "best_signal") ? overlay.best_signal : stock.best_signal,
      best_technical_signal: hasOwn(overlay, "best_technical_signal")
        ? overlay.best_technical_signal
        : stock.best_technical_signal,
      classic_technical_signal: hasOwn(overlay, "classic_technical_signal")
        ? overlay.classic_technical_signal
        : stock.classic_technical_signal,
      live_quote: quote,
      asset_class: stock.asset_class ?? taxonomy?.asset_class ?? "equity",
      asset_type: stock.asset_type ?? taxonomy?.asset_type ?? "equity",
      market_region: stock.market_region ?? taxonomy?.market_region ?? null,
    }
  })
}
