function asNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function asPositiveNumber(value) {
  const numberValue = asNumber(value)
  return numberValue != null && numberValue > 0 ? numberValue : null
}

function asRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {}
}

function numberArray(value) {
  return Array.isArray(value) ? value.map(asNumber).filter((item) => item != null) : []
}

function nearEqual(left, right) {
  if (left == null || right == null) return false
  const tolerance = Math.max(1e-4, Math.abs(right) * 1e-5)
  return Math.abs(left - right) <= tolerance
}

function sum(values) {
  return values.reduce((acc, value) => acc + (asNumber(value) ?? 0), 0)
}

function detailMetric(detail, key) {
  return asNumber(asRecord(detail?.metrics)[key])
}

function detailAssumption(detail, key) {
  return asNumber(asRecord(detail?.assumptions)[key])
}

function resolveMode(row, requestedMode) {
  if (requestedMode === "fcff" || requestedMode === "fcfe") return requestedMode
  if (row?.model === "fcff_dcf") return "fcff"
  if (row?.model === "fcfe_dcf") return "fcfe"
  return null
}

function terminalGrowthValue(inputs, detail, mode) {
  const keyed = mode === "fcff" ? "terminal_growth_firm" : "terminal_growth_equity"
  return (
    asNumber(inputs.terminal_growth) ??
    asNumber(inputs[keyed]) ??
    detailAssumption(detail, keyed) ??
    detailAssumption(detail, "terminal_growth")
  )
}

function growthFromPrevious(cashFlow, previous) {
  if (previous == null || previous === 0) return null
  return cashFlow / previous - 1
}

export function buildDcfViewModel(row, detail, requestedMode) {
  const mode = resolveMode(row, requestedMode)
  if (!mode) return { available: false, reason: "Unsupported DCF model." }

  const inputs = asRecord(row?.inputs)
  const outputs = asRecord(row?.outputs)
  const bridge = asRecord(outputs.dcf_bridge)
  const cashFlows = numberArray(bridge.cash_flows)
  const periods = numberArray(bridge.periods)
  const discountRate =
    mode === "fcff"
      ? asNumber(inputs.wacc) ?? detailAssumption(detail, "wacc")
      : asNumber(inputs.cost_of_equity) ?? detailAssumption(detail, "cost_of_equity")
  const terminalGrowth = terminalGrowthValue(inputs, detail, mode)
  const shares =
    asPositiveNumber(inputs.shares) ??
    asPositiveNumber(detailMetric(detail, "Shares_Outstanding")) ??
    asPositiveNumber(detailMetric(detail, "shares_outstanding"))
  const fairValue = asNumber(row?.fair_value)
  const currentPrice = asNumber(row?.current_price) ?? asNumber(asRecord(detail?.ensemble).current_price) ?? detailMetric(detail, "Current_Price")

  const unavailableBase = {
    available: false,
    mode,
    discountRate,
    terminalGrowth,
    shares,
    fairValue,
    currentPrice,
    reason: "",
  }

  if (!cashFlows.length) return { ...unavailableBase, reason: "Missing DCF cash-flow bridge." }
  if (discountRate == null) return { ...unavailableBase, reason: "Missing discount rate." }
  if (terminalGrowth == null) return { ...unavailableBase, reason: "Missing terminal growth." }

  const startCashFlow = mode === "fcff" ? asNumber(inputs.fcf_start) : asNumber(inputs.fcfe_start)
  const pvRows = cashFlows.map((cashFlow, index) => {
    const period = periods[index] ?? index + 1
    const discountFactor = discountRate > -1 ? 1 / ((1 + discountRate) ** period) : null
    const previous = index === 0 ? startCashFlow : cashFlows[index - 1]
    return {
      index: index + 1,
      cashFlow,
      growth: growthFromPrevious(cashFlow, previous),
      period,
      discountFactor,
      pv: discountFactor == null ? null : cashFlow * discountFactor,
    }
  })

  const explicitPvComputed = sum(pvRows.map((item) => item.pv))
  const explicitPv = asNumber(bridge.explicit_pv) ?? explicitPvComputed
  const terminalValue = asNumber(bridge.terminal_value)
  const terminalPeriod = asNumber(bridge.terminal_period) ?? periods.at(-1) ?? cashFlows.length
  const terminalDiscountFactor = discountRate > -1 ? 1 / ((1 + discountRate) ** terminalPeriod) : null
  const terminalPv = asNumber(bridge.terminal_pv)
  const totalValueComputed = explicitPvComputed + (terminalPv ?? 0)
  const totalValue = asNumber(bridge.total_value) ?? totalValueComputed
  const terminalValuePct = asNumber(bridge.terminal_value_pct) ?? (terminalPv != null && totalValue ? terminalPv / totalValue : null)
  const netDebt = mode === "fcff" ? asNumber(inputs.net_debt) ?? 0 : null
  const equityValue = totalValue == null ? null : mode === "fcff" ? totalValue - (netDebt ?? 0) : totalValue
  const finalFairValueComputed = shares != null && equityValue != null ? Math.max(0, equityValue) / shares : null
  const finalFairValue = fairValue ?? finalFairValueComputed
  const basis = asRecord(inputs.terminal_growth_basis)
  const terminalFormulaValue =
    cashFlows.length && discountRate > terminalGrowth
      ? cashFlows.at(-1) * (1 + terminalGrowth) / (discountRate - terminalGrowth)
      : null

  const bridgeSteps =
    mode === "fcff"
      ? [
          { key: "explicit_pv", label: "PV explicite", value: explicitPv, kind: "add" },
          { key: "terminal_pv", label: "PV terminale", value: terminalPv, kind: "add" },
          { key: "enterprise_value", label: "Valeur entreprise", value: totalValue, kind: "total" },
          { key: "net_debt", label: "Dette nette", value: netDebt == null ? null : -netDebt, kind: "subtract" },
          { key: "equity_value", label: "Capitaux propres", value: equityValue, kind: "total" },
          { key: "shares", label: "Actions", value: shares, kind: "divide" },
          { key: "fair_value", label: "Juste valeur/action", value: finalFairValue, kind: "result" },
        ]
      : [
          { key: "explicit_pv", label: "PV explicite", value: explicitPv, kind: "add" },
          { key: "terminal_pv", label: "PV terminale", value: terminalPv, kind: "add" },
          { key: "equity_value", label: "Capitaux propres", value: equityValue, kind: "total" },
          { key: "shares", label: "Actions", value: shares, kind: "divide" },
          { key: "fair_value", label: "Juste valeur/action", value: finalFairValue, kind: "result" },
        ]

  return {
    available: true,
    mode,
    cashFlowLabel: mode === "fcff" ? "FCFF" : "FCFE",
    rateLabel: mode === "fcff" ? "WACC" : "Ke",
    discountRate,
    terminalGrowth,
    terminalBasis: basis,
    shares,
    fairValue,
    currentPrice,
    netDebt,
    netDebtSource: typeof inputs.net_debt_source === "string" ? inputs.net_debt_source : null,
    midYearDiscounting: Boolean(inputs.mid_year_discounting),
    midYearTerminal: Boolean(inputs.mid_year_terminal),
    pvRows,
    explicitPv,
    explicitPvComputed,
    terminalValue,
    terminalFormulaValue,
    terminalPeriod,
    terminalDiscountFactor,
    terminalPv,
    terminalValuePct,
    totalValue,
    totalValueComputed,
    equityValue,
    finalFairValue,
    finalFairValueComputed,
    impliedExitEvToEbitda: mode === "fcff" ? asNumber(outputs.implied_exit_ev_to_ebitda) : null,
    bridgeSteps,
    flags: {
      gBelowRate: discountRate > terminalGrowth,
      terminalHeavy: terminalValuePct != null && terminalValuePct > 0.75,
    },
    reconciliations: [
      {
        key: "explicit_pv",
        label: "PV explicite",
        reported: explicitPv,
        computed: explicitPvComputed,
        diff: explicitPv == null ? null : explicitPvComputed - explicitPv,
        ok: nearEqual(explicitPvComputed, explicitPv),
      },
      {
        key: "total_value",
        label: mode === "fcff" ? "EV" : "Equity value",
        reported: totalValue,
        computed: totalValueComputed,
        diff: totalValue == null ? null : totalValueComputed - totalValue,
        ok: nearEqual(totalValueComputed, totalValue),
      },
      {
        key: "fair_value",
        label: "Fair value/share",
        reported: fairValue,
        computed: finalFairValueComputed,
        diff: fairValue == null || finalFairValueComputed == null ? null : finalFairValueComputed - fairValue,
        ok: fairValue == null ? finalFairValueComputed != null : nearEqual(finalFairValueComputed, fairValue),
      },
    ],
  }
}
