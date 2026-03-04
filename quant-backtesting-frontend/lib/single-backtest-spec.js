export function buildSingleBacktestPlotsConfig(symbols = []) {
  const ALL_SUPPORTED_PLOT_KINDS = [
    "price_indicators_trades",
    "drawdown",
    "cumreturn_vs_benchmark",
    "monthly_heatmap",
    "yearly_return_barplot",
  ]

  const normalizedSymbols = Array.isArray(symbols)
    ? symbols
        .map((value) => String(value ?? "").trim())
        .filter(Boolean)
    : []

  const plots = {
    enabled: true,
    return_plot_artifacts: true,
    kinds: ALL_SUPPORTED_PLOT_KINDS,
  }

  if (normalizedSymbols.length > 0) {
    plots.symbols = [normalizedSymbols[0]]
  }

  return plots
}
