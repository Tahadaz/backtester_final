import test from "node:test"
import assert from "node:assert/strict"

import { buildDcfViewModel } from "./fundamental-dcf-utils.js"

function closeTo(actual, expected, tolerance = 1e-9) {
  assert.ok(actual != null, "actual value should be present")
  assert.ok(Math.abs(actual - expected) <= tolerance, `${actual} should be within ${tolerance} of ${expected}`)
}

function dcfBridge(cashFlows, rate, terminalGrowth, terminalPeriod = cashFlows.length) {
  const periods = cashFlows.map((_, index) => index + 1)
  const explicitPv = cashFlows.reduce((acc, cashFlow, index) => acc + cashFlow / ((1 + rate) ** periods[index]), 0)
  const terminalValue = cashFlows.at(-1) * (1 + terminalGrowth) / (rate - terminalGrowth)
  const terminalPv = terminalValue / ((1 + rate) ** terminalPeriod)
  return {
    cash_flows: cashFlows,
    periods,
    explicit_pv: explicitPv,
    terminal_value: terminalValue,
    terminal_period: terminalPeriod,
    terminal_pv: terminalPv,
    total_value: explicitPv + terminalPv,
    terminal_value_pct: terminalPv / (explicitPv + terminalPv),
  }
}

function makeDetail() {
  return {
    metrics: {
      Shares_Outstanding: 10,
      Current_Price: 80,
    },
    assumptions: {
      wacc: 0.1,
      cost_of_equity: 0.12,
      terminal_growth: 0.03,
    },
    ensemble: {
      current_price: 80,
    },
  }
}

test("FCFF bridge reconciles PV, net debt, and fair value per share", () => {
  const bridge = dcfBridge([110, 121], 0.1, 0.03)
  const fairValue = (bridge.total_value - 100) / 10
  const view = buildDcfViewModel({
    model: "fcff_dcf",
    fair_value: fairValue,
    current_price: 80,
    inputs: {
      fcf_start: 100,
      wacc: 0.1,
      terminal_growth: 0.03,
      net_debt: 100,
      net_debt_source: "reported",
    },
    outputs: {
      dcf_bridge: bridge,
      implied_exit_ev_to_ebitda: 8.5,
    },
  }, makeDetail())

  assert.equal(view.available, true)
  assert.equal(view.mode, "fcff")
  assert.equal(view.netDebt, 100)
  closeTo(view.explicitPvComputed, bridge.explicit_pv)
  closeTo(view.equityValue, bridge.total_value - 100)
  closeTo(view.finalFairValueComputed, fairValue)
  assert.equal(view.reconciliations.every((item) => item.ok), true)
  assert.equal(view.bridgeSteps.some((step) => step.key === "net_debt"), true)
})

test("FCFE bridge does not subtract net debt", () => {
  const bridge = dcfBridge([90, 95], 0.12, 0.03)
  const fairValue = bridge.total_value / 10
  const view = buildDcfViewModel({
    model: "fcfe_dcf",
    fair_value: fairValue,
    current_price: 80,
    inputs: {
      fcfe_start: 85,
      cost_of_equity: 0.12,
      terminal_growth: 0.03,
      net_debt: 999,
    },
    outputs: {
      dcf_bridge: bridge,
    },
  }, makeDetail())

  assert.equal(view.available, true)
  assert.equal(view.mode, "fcfe")
  assert.equal(view.netDebt, null)
  closeTo(view.equityValue, bridge.total_value)
  closeTo(view.finalFairValueComputed, fairValue)
  assert.equal(view.bridgeSteps.some((step) => step.key === "net_debt"), false)
})

test("terminal value share above 75 percent is flagged", () => {
  const bridge = dcfBridge([100, 103, 106], 0.09, 0.04)
  const view = buildDcfViewModel({
    model: "fcff_dcf",
    inputs: {
      wacc: 0.09,
      terminal_growth: 0.04,
      net_debt: 0,
    },
    outputs: {
      dcf_bridge: bridge,
    },
  }, makeDetail())

  assert.equal(view.available, true)
  assert.equal(view.flags.terminalHeavy, true)
})

test("missing DCF bridge returns an unavailable view model", () => {
  const view = buildDcfViewModel({
    model: "fcff_dcf",
    inputs: {
      wacc: 0.1,
      terminal_growth: 0.03,
    },
    outputs: {},
  }, makeDetail())

  assert.equal(view.available, false)
  assert.equal(view.reason, "Missing DCF cash-flow bridge.")
})
