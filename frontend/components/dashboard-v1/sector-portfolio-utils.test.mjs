import test from "node:test"
import assert from "node:assert/strict"

import {
  buildPortfolioWeightRows,
  normalizeShareQuantity,
  signalLabelFromNetWeight,
  stockPriceForWeight,
  summarizeWeightRows,
} from "./sector-portfolio-utils.mjs"

function stock(symbol, price, direction, sector = "Banks", expectedReturnNet = 0.02) {
  return {
    symbol,
    sector,
    last_price: price,
    prev_close: price ? price - 1 : null,
    best_signal: {
      source: "wfo",
      bucket: direction === "long" ? "buy" : direction === "short" ? "sell" : "hold",
      direction,
      action_expected_return_net: expectedReturnNet,
    },
    best_technical_signal: {
      direction,
    },
    classic_technical_signal: {
      direction: direction === "long" ? "short" : direction === "short" ? "long" : "none",
    },
    scores: {
      signal_engine: {
        technical_levels: {
          close_used: price,
        },
      },
    },
  }
}

test("normalizes share input", () => {
  assert.equal(normalizeShareQuantity("12"), 12)
  assert.equal(normalizeShareQuantity("12,5"), 12.5)
  assert.equal(normalizeShareQuantity(""), 0)
  assert.equal(normalizeShareQuantity("-4"), 0)
  assert.equal(normalizeShareQuantity("abc"), 0)
})

test("uses latest price with documented fallbacks", () => {
  assert.equal(stockPriceForWeight({ last_price: 101, prev_close: 99 }), 101)
  assert.equal(
    stockPriceForWeight({
      last_price: null,
      prev_close: 99,
      scores: { signal_engine: { technical_levels: { close_used: 100 } } },
    }),
    100,
  )
  assert.equal(stockPriceForWeight({ last_price: null, prev_close: 99 }), 99)
  assert.equal(stockPriceForWeight({}), null)
})

test("calculates weights from shares and prices", () => {
  const result = buildPortfolioWeightRows(
    [stock("AAA", 100, "long"), stock("BBB", 50, "short")],
    { AAA: "10", BBB: "20" },
  )

  assert.equal(result.totalMarketValue, 2000)
  assert.equal(result.rows.find((row) => row.symbol === "AAA")?.weightPct, 50)
  assert.equal(result.rows.find((row) => row.symbol === "BBB")?.weightPct, 50)
})

test("excludes zero shares and tracks missing prices", () => {
  const result = buildPortfolioWeightRows(
    [stock("AAA", 100, "long"), stock("BBB", null, "long"), stock("CCC", 20, "short")],
    { AAA: "10", BBB: "5", CCC: "0" },
  )

  assert.equal(result.enteredCount, 2)
  assert.equal(result.investedCount, 1)
  assert.equal(result.missingPriceCount, 1)
  assert.equal(result.rows.find((row) => row.symbol === "BBB")?.weightPct, 0)
})

test("summarizes weighted long short signal", () => {
  const result = buildPortfolioWeightRows(
    [stock("AAA", 100, "long"), stock("BBB", 100, "short"), stock("CCC", 100, "none")],
    { AAA: "6", BBB: "2", CCC: "2" },
  )
  const summary = summarizeWeightRows(result.rows)

  assert.equal(summary.longWeightPct, 60)
  assert.equal(summary.shortWeightPct, 20)
  assert.equal(summary.neutralWeightPct, 20)
  assert.equal(summary.netSignalPct, 40)
  assert.equal(summary.signalLabel, "Achat")
})

test("summarizes a sector subset as part of the full portfolio", () => {
  const result = buildPortfolioWeightRows(
    [stock("AAA", 100, "long", "Banks"), stock("BBB", 100, "short", "Mines")],
    { AAA: "3", BBB: "1" },
  )
  const banksSummary = summarizeWeightRows(result.rows.filter((row) => row.sector === "Banks"))

  assert.equal(banksSummary.totalWeightPct, 75)
  assert.equal(banksSummary.longWeightPct, 75)
  assert.equal(banksSummary.signalLabel, "Achat fort")
})

test("uses selected technical mode for weighted technical directions", () => {
  const result = buildPortfolioWeightRows(
    [stock("AAA", 100, "long"), stock("BBB", 100, "short")],
    { AAA: "1", BBB: "1" },
    { displayMode: "technical_directions", technicalDirectionMode: "classic" },
  )

  assert.equal(result.rows.find((row) => row.symbol === "AAA")?.direction, "short")
  assert.equal(result.rows.find((row) => row.symbol === "BBB")?.direction, "long")
})

test("labels net portfolio signal thresholds", () => {
  assert.equal(signalLabelFromNetWeight(60), "Achat fort")
  assert.equal(signalLabelFromNetWeight(20), "Achat")
  assert.equal(signalLabelFromNetWeight(0), "Neutre")
  assert.equal(signalLabelFromNetWeight(-20), "Vente")
  assert.equal(signalLabelFromNetWeight(-60), "Vente forte")
})
