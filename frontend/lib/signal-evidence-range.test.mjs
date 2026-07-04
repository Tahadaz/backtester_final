import test from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

import {
  buildSignalEvidenceRangeView,
  sortEvidenceLedgerRows,
} from "./signal-evidence-range.js"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const goldenPath = path.resolve(__dirname, "../../services/api/tests/fixtures/evidence_metrics_golden.json")

function assertMetric(actual, expected, key) {
  if (typeof expected === "number") {
    assert.ok(Math.abs(actual - expected) <= 1e-9, `${key}: expected ${expected}, got ${actual}`)
  } else {
    assert.equal(actual, expected, key)
  }
}

test("golden fixture JS metrics parity", () => {
  // Change a formula -> regenerate this fixture and update BOTH sides.
  const fixture = JSON.parse(fs.readFileSync(goldenPath, "utf8"))
  const { inputs, expected } = fixture
  const trades = inputs.net_returns.map((value, index) => ({
    trade_id: `t${index}`,
    direction: "long",
    entry_date: inputs.dates[Math.min(index, inputs.dates.length - 1)],
    exit_date: inputs.dates[Math.min(index + 1, inputs.dates.length - 1)],
    action_return_net: value,
    action_return_gross: inputs.gross_returns[index],
    stock_return: inputs.stock_returns[index],
  }))
  const trade_ledger = inputs.equity.map((value, index) => ({
    trade_id: "t0",
    date: inputs.dates[index],
    marker_label: index === 0 ? "Buy 0" : `Mark ${index}`,
    transaction_index: index + 1,
    price_kind: index === 0 ? "open" : "close",
    notional_ouvert: index === 0 ? 1 : null,
    pnl_realise: index === 0 ? 0 : value - inputs.equity[index - 1],
  }))
  const view = buildSignalEvidenceRangeView({
    dates: inputs.dates,
    close_series: inputs.equity.map((value) => value * 100),
    benchmark_returns: inputs.benchmark_returns,
    benchmark_symbol: inputs.benchmark_symbol,
    trades,
    trade_ledger,
  }, null)

  for (const [key, value] of Object.entries(expected)) {
    assertMetric(view.metrics[key], value, key)
  }
  assert.equal("expectancy_net" in view.metrics, false)
})

test("buildSignalEvidenceRangeView recalculates metrics from opened-in-range trades", () => {
  const stitched = {
    dates: ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"],
    open_series: [99, 100, 101, 102, 103],
    high_series: [101, 102, 103, 104, 105],
    low_series: [98, 99, 100, 101, 102],
    close_series: [100, 101, 102, 103, 104],
    position_series: [1, 1, 0, 1, 0],
    trades: [
      {
        trade_id: "first",
        direction: "long",
        entry_date: "2026-01-01",
        exit_date: "2026-01-03",
        entry_price: 100,
        action_return_net: 0.1,
        action_return_gross: 0.12,
        stock_return: 0.05,
      },
      {
        trade_id: "second",
        direction: "long",
        entry_date: "2026-01-04",
        exit_date: "2026-01-05",
        entry_price: 100,
        action_return_net: -0.05,
        action_return_gross: -0.04,
        stock_return: -0.01,
      },
    ],
    trade_ledger: [
      { trade_id: "second", date: "2026-01-05", marker_label: "Sell 2", transaction_index: 4, price_kind: "close", pnl_realise: -5 },
      { trade_id: "first", date: "2026-01-03", marker_label: "Sell 1", transaction_index: 2, price_kind: "close", pnl_realise: 10 },
      { trade_id: "second", date: "2026-01-04", marker_label: "Buy 2", transaction_index: 3, price_kind: "open", pnl_realise: 0 },
      { trade_id: "first", date: "2026-01-01", marker_label: "Buy 1", transaction_index: 1, price_kind: "open", pnl_realise: 0 },
    ],
  }

  const view = buildSignalEvidenceRangeView(stitched, "2026-01-04")

  assert.deepEqual(view.dates, ["2026-01-04", "2026-01-05"])
  assert.deepEqual(view.open, [102, 103])
  assert.deepEqual(view.high, [104, 105])
  assert.deepEqual(view.low, [101, 102])
  assert.deepEqual(view.close, [103, 104])
  assert.equal(view.metrics.n_trades, 1)
  assert.equal(view.metrics.expected_return_net, -0.05)
  assert.equal(view.metrics.var95, null)
  assert.equal(view.metrics.cvar95, null)
  assert.equal(view.metrics.hit_rate, 0)
  assert.equal(view.metrics.total_return, -0.050000000000000044)
  assert.deepEqual(view.equity, [1, 0.95])
  assert.deepEqual(view.position, [1, 0])
  assert.deepEqual(view.ledger.map((row) => row.position), [1, 0])
  assert.deepEqual(view.ledger.map((row) => row.marker_label), ["Buy 2", "Sell 2"])
})

test("buildSignalEvidenceRangeView computes historical VaR and CVaR from range-filtered net trades", () => {
  const stitched = {
    dates: [
      "2026-01-01",
      "2026-01-02",
      "2026-01-03",
      "2026-01-04",
      "2026-01-05",
      "2026-01-06",
    ],
    close_series: [100, 101, 102, 103, 104, 105],
    trades: [
      { trade_id: "old", direction: "long", entry_date: "2026-01-01", exit_date: "2026-01-02", entry_price: 100, action_return_net: -0.5, action_return_gross: -0.5 },
      { trade_id: "t1", direction: "long", entry_date: "2026-01-02", exit_date: "2026-01-03", entry_price: 100, action_return_net: -0.1, action_return_gross: -0.1 },
      { trade_id: "t2", direction: "long", entry_date: "2026-01-03", exit_date: "2026-01-04", entry_price: 100, action_return_net: -0.05, action_return_gross: -0.05 },
      { trade_id: "t3", direction: "long", entry_date: "2026-01-04", exit_date: "2026-01-05", entry_price: 100, action_return_net: 0, action_return_gross: 0 },
      { trade_id: "t4", direction: "long", entry_date: "2026-01-05", exit_date: "2026-01-06", entry_price: 100, action_return_net: 0.02, action_return_gross: 0.02 },
      { trade_id: "t5", direction: "long", entry_date: "2026-01-06", exit_date: "2026-01-06", entry_price: 100, action_return_net: 0.05, action_return_gross: 0.05 },
    ],
    trade_ledger: [
      { trade_id: "old", date: "2026-01-01", marker_label: "Buy old", transaction_index: 1, price_kind: "open", pnl_realise: 0 },
      { trade_id: "old", date: "2026-01-02", marker_label: "Sell old", transaction_index: 2, price_kind: "close", pnl_realise: -50 },
      { trade_id: "t1", date: "2026-01-02", marker_label: "Buy 1", transaction_index: 3, price_kind: "open", pnl_realise: 0 },
      { trade_id: "t1", date: "2026-01-03", marker_label: "Sell 1", transaction_index: 4, price_kind: "close", pnl_realise: -10 },
      { trade_id: "t2", date: "2026-01-03", marker_label: "Buy 2", transaction_index: 5, price_kind: "open", pnl_realise: 0 },
      { trade_id: "t2", date: "2026-01-04", marker_label: "Sell 2", transaction_index: 6, price_kind: "close", pnl_realise: -5 },
      { trade_id: "t3", date: "2026-01-04", marker_label: "Buy 3", transaction_index: 7, price_kind: "open", pnl_realise: 0 },
      { trade_id: "t3", date: "2026-01-05", marker_label: "Sell 3", transaction_index: 8, price_kind: "close", pnl_realise: 0 },
      { trade_id: "t4", date: "2026-01-05", marker_label: "Buy 4", transaction_index: 9, price_kind: "open", pnl_realise: 0 },
      { trade_id: "t4", date: "2026-01-06", marker_label: "Sell 4", transaction_index: 10, price_kind: "close", pnl_realise: 2 },
      { trade_id: "t5", date: "2026-01-06", marker_label: "Buy 5", transaction_index: 11, price_kind: "open", pnl_realise: 0 },
      { trade_id: "t5", date: "2026-01-06", marker_label: "Sell 5", transaction_index: 12, price_kind: "close", pnl_realise: 5 },
    ],
  }

  const view = buildSignalEvidenceRangeView(stitched, "2026-01-02")

  assert.equal(view.metrics.n_trades, 5)
  assert.equal(Math.abs(view.metrics.var95 - -0.09) < 1e-12, true)
  assert.equal(view.metrics.cvar95, -0.1)
})

test("buildSignalEvidenceRangeView excludes transactions for trades opened before the selected range", () => {
  const stitched = {
    dates: ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"],
    close_series: [100, 101, 102, 103, 104],
    position_series: [1, 1, 0, 1, 0],
    trades: [
      { trade_id: "first", direction: "long", entry_date: "2026-01-01", exit_date: "2026-01-03", entry_price: 100, action_return_net: 0.1, action_return_gross: 0.12 },
      { trade_id: "second", direction: "long", entry_date: "2026-01-04", exit_date: "2026-01-05", entry_price: 100, action_return_net: -0.05, action_return_gross: -0.04 },
    ],
    trade_ledger: [
      { trade_id: "first", date: "2026-01-01", marker_label: "Buy 1", transaction_index: 1, price_kind: "open", pnl_realise: 0 },
      { trade_id: "first", date: "2026-01-03", marker_label: "Sell 1", transaction_index: 2, price_kind: "close", pnl_realise: 10 },
      { trade_id: "second", date: "2026-01-04", marker_label: "Buy 2", transaction_index: 3, price_kind: "open", pnl_realise: 0 },
      { trade_id: "second", date: "2026-01-05", marker_label: "Sell 2", transaction_index: 4, price_kind: "close", pnl_realise: -5 },
    ],
  }

  const view = buildSignalEvidenceRangeView(stitched, "2026-01-02")

  assert.equal(view.metrics.n_trades, 1)
  assert.equal(view.metrics.expected_return_net, -0.05)
  assert.deepEqual(view.ledger.map((row) => row.marker_label), ["Buy 2", "Sell 2"])
  assert.deepEqual(view.ledger.map((row) => row.position), [1, 0])
  assert.deepEqual(view.position, [0, 0, 1, 0])
})

test("buildSignalEvidenceRangeView uses realized PnL over opened notional instead of compounding returns", () => {
  const stitched = {
    dates: ["2026-01-01", "2026-01-02", "2026-01-03"],
    close_series: [100, 100, 200],
    trades: [
      { trade_id: "first", direction: "long", entry_date: "2026-01-01", exit_date: "2026-01-03", entry_price: 100, action_return_net: 1, action_return_gross: 1 },
      { trade_id: "second", direction: "long", entry_date: "2026-01-02", exit_date: "2026-01-03", entry_price: 100, action_return_net: 1, action_return_gross: 1 },
    ],
    trade_ledger: [
      { trade_id: "first", date: "2026-01-01", marker_label: "Buy 1", transaction_index: 1, price_kind: "open", pnl_realise: 0 },
      { trade_id: "second", date: "2026-01-02", marker_label: "Buy 2", transaction_index: 2, price_kind: "open", pnl_realise: 0 },
      { trade_id: "first", date: "2026-01-03", marker_label: "Sell 1", transaction_index: 3, price_kind: "close", pnl_realise: 100 },
      { trade_id: "second", date: "2026-01-03", marker_label: "Sell 2", transaction_index: 4, price_kind: "close", pnl_realise: 100 },
    ],
  }

  const view = buildSignalEvidenceRangeView(stitched, null)

  assert.equal(view.metrics.total_return, 1)
  assert.deepEqual(view.equity, [1, 1, 2])
})

test("buildSignalEvidenceRangeView treats neutral samples as no action trades", () => {
  const stitched = {
    dates: ["2026-01-01", "2026-01-02", "2026-01-03"],
    close_series: [100, 101, 102],
    trades: [
      {
        trade_id: "neutral-one",
        direction: "none",
        entry_date: "2026-01-01",
        exit_date: "2026-01-03",
        entry_price: 100,
        action_return_net: null,
        action_return_gross: null,
        stock_return: 0.04,
      },
      {
        trade_id: "neutral-two",
        direction: "none",
        entry_date: "2026-01-02",
        exit_date: "2026-01-03",
        entry_price: 100,
        action_return_net: null,
        action_return_gross: null,
        stock_return: 0.02,
      },
    ],
    trade_ledger: [
      { trade_id: "neutral-one", date: "2026-01-01", marker_label: "Buy 1", transaction_index: 1, price_kind: "open", pnl_realise: 0 },
      { trade_id: "neutral-one", date: "2026-01-03", marker_label: "Sell 1", transaction_index: 2, price_kind: "close", pnl_realise: 4 },
    ],
  }

  const view = buildSignalEvidenceRangeView(stitched, null)

  assert.equal(view.metrics.n_trades, 0)
  assert.equal(view.metrics.expected_return_net, null)
  assert.equal(view.metrics.hit_rate, null)
  assert.equal(view.metrics.sharpe, null)
  assert.equal(view.metrics.var95, null)
  assert.equal(view.metrics.cvar95, null)
  assert.equal(Math.abs(view.metrics.stock_expected_return - 0.03) < 1e-12, true)
  assert.deepEqual(view.trades, [])
  assert.equal(view.sampleTrades.length, 2)
  assert.deepEqual(view.ledger, [])
  assert.deepEqual(view.position, [0, 0, 0])
})

test("sortEvidenceLedgerRows falls back to date then execution timing when transaction indexes are absent", () => {
  const sorted = sortEvidenceLedgerRows([
    { date: "2026-01-02", marker_label: "Sell 1", price_kind: "close", trade_sequence: 1 },
    { date: "2026-01-02", marker_label: "Buy 2", price_kind: "open", trade_sequence: 2 },
    { date: "2026-01-01", marker_label: "Buy 1", price_kind: "open", trade_sequence: 1 },
  ])

  assert.deepEqual(sorted.map((row) => row.marker_label), ["Buy 1", "Buy 2", "Sell 1"])
})
