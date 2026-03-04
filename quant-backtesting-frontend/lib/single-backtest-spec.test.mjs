import test from "node:test"
import assert from "node:assert/strict"

import { buildSingleBacktestPlotsConfig } from "./single-backtest-spec.js"

const ALL_SUPPORTED_PLOT_KINDS = [
  "price_indicators_trades",
  "drawdown",
  "cumreturn_vs_benchmark",
  "monthly_heatmap",
  "yearly_return_barplot",
]

test("buildSingleBacktestPlotsConfig includes required plot artifact settings", () => {
  const plots = buildSingleBacktestPlotsConfig(["IAM"])

  assert.equal(plots.enabled, true)
  assert.equal(plots.return_plot_artifacts, true)
  assert.deepEqual(plots.kinds, ALL_SUPPORTED_PLOT_KINDS)
  assert.deepEqual(plots.symbols, ["IAM"])
})

test("buildSingleBacktestPlotsConfig omits symbols when none is selected", () => {
  const plots = buildSingleBacktestPlotsConfig([])

  assert.equal(plots.enabled, true)
  assert.equal(plots.return_plot_artifacts, true)
  assert.deepEqual(plots.kinds, ALL_SUPPORTED_PLOT_KINDS)
  assert.equal(Object.prototype.hasOwnProperty.call(plots, "symbols"), false)
})
