function asNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function asRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {}
}

function numberArray(value) {
  return Array.isArray(value) ? value.map(asNumber).filter((item) => item != null) : []
}

function median(values) {
  const clean = values.filter((value) => value != null).sort((left, right) => left - right)
  if (!clean.length) return null
  const mid = Math.floor(clean.length / 2)
  return clean.length % 2 ? clean[mid] : (clean[mid - 1] + clean[mid]) / 2
}

function nearEqual(left, right) {
  if (left == null || right == null) return false
  const tolerance = Math.max(1e-4, Math.abs(right) * 1e-5)
  return Math.abs(left - right) <= tolerance
}

function metric(detail, key) {
  return asNumber(asRecord(detail?.metrics)[key])
}

function assumption(detail, key) {
  return asNumber(asRecord(detail?.assumptions)[key])
}

function modelKeyLabel(key) {
  switch (key) {
    case "PER":
      return "P/E"
    case "Price_to_Book":
    case "justified_pb":
      return "P/B"
    case "Price_to_Sales":
      return "P/S"
    case "EV_to_EBITDA":
      return "EV/EBITDA"
    case "justified_pe":
      return "P/E"
    default:
      return key.replaceAll("_", " ")
  }
}

function humanSource(value) {
  if (typeof value !== "string" || !value.trim()) return null
  return value.replaceAll("_", " ")
}

function roeSourceLabel(value) {
  switch (value) {
    case "roe_3y_trailing":
      return "3Y trailing average of annual ROE"
    case "roe_spot_fallback":
      return "latest snapshot ROE"
    case "historical_roe":
      return "historical ROE"
    case "snapshot_roe":
      return "snapshot ROE"
    case "missing_roe":
      return "ROE missing"
    default:
      return humanSource(value)
  }
}

function cashFlowPvRows(cashFlows, periods, rate, startValue) {
  return cashFlows.map((cashFlow, index) => {
    const period = periods[index] ?? index + 1
    const discountFactor = rate != null && rate > -1 ? 1 / ((1 + rate) ** period) : null
    const previous = index === 0 ? startValue : cashFlows[index - 1]
    return {
      index: index + 1,
      cashFlow,
      growth: previous == null || previous === 0 ? null : cashFlow / previous - 1,
      period,
      discountFactor,
      pv: discountFactor == null ? null : cashFlow * discountFactor,
    }
  })
}

function buildDdmStory(row, detail) {
  const inputs = asRecord(row.inputs)
  const outputs = asRecord(row.outputs)
  const bridge = asRecord(outputs.dcf_bridge)
  const cashFlows = numberArray(bridge.cash_flows)
  const periods = numberArray(bridge.periods)
  const cost = asNumber(inputs.cost_of_equity) ?? assumption(detail, "cost_of_equity")
  const terminalGrowth = asNumber(inputs.terminal_growth) ?? asNumber(inputs.terminal_growth_equity) ?? assumption(detail, "terminal_growth_equity") ?? assumption(detail, "terminal_growth")
  const dividend = asNumber(inputs.dividend_per_share)
  const fairValue = asNumber(row.fair_value)
  const steps = [
    {
      title: "Base dividende",
      description: "Point de depart du modele: dividende par action observe ou reconstruit depuis le rendement.",
      metrics: [
        { label: "DPS", value: dividend, format: "money", source: inputs.dividend_source },
        { label: "Dividend yield", value: asNumber(inputs.dividend_yield), format: "pct" },
        { label: "Actions", value: asNumber(inputs.shares), format: "number" },
      ],
    },
    {
      title: "Croissance et cout equity",
      description: cashFlows.length ? "Les dividendes projetes sont actualises au cout des fonds propres." : "H-model: la croissance superieure converge vers le g terminal sur l'horizon de fade.",
      formula: cashFlows.length ? "FV = PV(DPS_1..n) + PV(TV)" : "FV = DPS x ((1 + g_terminal) + H x (g - g_terminal)) / (Ke - g_terminal)",
      metrics: [
        { label: "Ke", value: cost, format: "pct" },
        { label: "g terminal", value: terminalGrowth, format: "pct" },
        { label: "g initial", value: asNumber(inputs.growth), format: "pct", source: inputs.growth_source },
        { label: "H factor", value: asNumber(inputs.h_factor), format: "number" },
      ],
    },
  ]

  if (cashFlows.length) {
    const rows = cashFlowPvRows(cashFlows, periods, cost, dividend)
    steps.push({
      title: "Actualisation dividendes",
      description: "Chaque dividende projete est actualise, puis la valeur terminale est ajoutee.",
      table: {
        columns: ["Annee", "DPS", "Croissance", "t", "Facteur", "PV"],
        rows: rows.map((item) => [
          `Y${item.index}`,
          item.cashFlow,
          { value: item.growth, format: "pct" },
          item.period,
          { value: item.discountFactor, digits: 4 },
          { value: item.pv, format: "money" },
        ]),
      },
      metrics: [
        { label: "PV explicite", value: asNumber(bridge.explicit_pv), format: "money" },
        { label: "PV terminale", value: asNumber(bridge.terminal_pv), format: "money" },
        { label: "Poids TV", value: asNumber(bridge.terminal_value_pct), format: "pct" },
      ],
    })
  }

  return {
    model: "ddm",
    title: "Lecture du DDM",
    summary: cashFlows.length ? "Dividendes projetes, actualises a Ke, puis valeur terminale." : "H-model dividend discount model avec croissance qui converge vers le g terminal.",
    steps,
    checks: [
      { label: "Ke > g terminal", ok: cost != null && terminalGrowth != null && cost > terminalGrowth },
      { label: "DPS positif", ok: dividend != null && dividend > 0 },
      { label: "Fair value calculee", ok: fairValue != null },
    ],
  }
}

function buildResidualIncomeStory(row) {
  const inputs = asRecord(row.inputs)
  const outputs = asRecord(row.outputs)
  const rowsRaw = Array.isArray(outputs.projected_residual_income) ? outputs.projected_residual_income.map(asRecord) : []
  const cost = asNumber(inputs.cost_of_equity)
  const bookValue = asNumber(inputs.book_value_per_share)
  const terminalPv = asNumber(outputs.terminal_residual_income_pv) ?? 0
  const rows = rowsRaw.map((item, index) => {
    const period = asNumber(item.year) ?? index + 1
    const residualIncome = asNumber(item.residual_income)
    const pv = cost != null && residualIncome != null ? residualIncome / ((1 + cost) ** period) : null
    return {
      year: period,
      roe: asNumber(item.roe),
      bookValue: asNumber(item.book_value),
      residualIncome,
      pv,
    }
  })
  const pvResidual = rows.reduce((acc, item) => acc + (item.pv ?? 0), 0)
  const computedFairValue = bookValue == null ? null : Math.max(0, bookValue + pvResidual + terminalPv)
  const reportedFairValue = asNumber(row.fair_value)
  return {
    model: "residual_income",
    title: "Lecture du revenu residuel",
    summary: "La valeur part de la valeur comptable par action et ajoute la valeur actualisee de la creation de valeur au-dessus de Ke.",
    steps: [
      {
        title: "Base comptable",
        description: "Le modele commence avec la valeur comptable par action.",
        metrics: [
          { label: "BVPS", value: bookValue, format: "money" },
          { label: "Ke", value: cost, format: "pct" },
          { label: "Payout", value: asNumber(inputs.payout), format: "pct" },
          { label: "g terminal", value: asNumber(inputs.terminal_growth), format: "pct" },
        ],
      },
      {
        title: "Residual income projete",
        description: "RI = resultat net - Ke x capitaux propres. Les lignes sont par action quand la projection partagee est disponible.",
        formula: "FV = BVPS + PV(RI_1..n) + PV(RI terminal)",
        table: {
          columns: ["Annee", "ROE", "Book/share", "RI/share", "PV RI"],
          rows: rows.map((item) => [
            item.year,
            { value: item.roe, format: "pct" },
            { value: item.bookValue, format: "money" },
            { value: item.residualIncome, format: "money" },
            { value: item.pv, format: "money" },
          ]),
        },
        metrics: [
          { label: "PV RI", value: pvResidual, format: "money" },
          { label: "PV RI terminal", value: terminalPv, format: "money" },
          { label: "FV calculee", value: computedFairValue, format: "money" },
        ],
      },
    ],
    checks: [
      { label: "BVPS disponible", ok: bookValue != null },
      { label: "Ke positif", ok: cost != null && cost > 0 },
      { label: "Reconciliation FV", ok: reportedFairValue == null ? computedFairValue != null : nearEqual(computedFairValue, reportedFairValue) },
    ],
  }
}

function buildJustifiedMultiplesStory(row, detail) {
  const inputs = asRecord(row.inputs)
  const outputs = asRecord(row.outputs)
  const implied = asRecord(outputs.implied_prices)
  const persistedJustifiedMultiples = asRecord(outputs.justified_multiples)
  const current = asNumber(row.current_price) ?? metric(detail, "Current_Price")
  const ownPb = metric(detail, "Price_to_Book")
  const ownPe = metric(detail, "PER")
  const roe = asNumber(inputs.roe)
  const growth = asNumber(inputs.growth)
  const costOfEquity = asNumber(inputs.cost_of_equity)
  const payout = asNumber(inputs.payout)
  const roeSource = roeSourceLabel(inputs.roe_source)
  const rows = [
    ["justified_pb", "P/B", ownPb],
    ["justified_pe", "P/E", ownPe],
  ].map(([key, label, own]) => {
    const impliedPrice = asNumber(implied[key])
    const persistedJustifiedMultiple = key === "justified_pb" ? asNumber(persistedJustifiedMultiples.implied_pb) : asNumber(persistedJustifiedMultiples.implied_pe)
    const fallbackJustifiedMultiple = current != null && own != null && current > 0 && impliedPrice != null ? impliedPrice * own / current : null
    const justifiedMultiple = persistedJustifiedMultiple ?? fallbackJustifiedMultiple
    const calculation = key === "justified_pb"
      ? `(${formatPctText(roe)} - ${formatPctText(growth)}) / (${formatPctText(costOfEquity)} - ${formatPctText(growth)})`
      : `${formatPctText(payout)} x (1 + ${formatPctText(growth)}) / (${formatPctText(costOfEquity)} - ${formatPctText(growth)})`
    return { key, label, own, justifiedMultiple, impliedPrice, calculation }
  }).filter((item) => item.impliedPrice != null)
  const computedFairValue = median(rows.map((item) => item.impliedPrice))
  const reportedFairValue = asNumber(row.fair_value)
  return {
    model: "justified_multiples",
    title: "Lecture des multiples justifies",
    summary: "Le modele transforme ROE, payout, croissance et Ke en multiples P/B et P/E justifies, puis en prix implicites.",
    steps: [
      {
        title: "Drivers fondamentaux",
        description: "Ces drivers determinent les multiples theoriques.",
        formula: "Justified P/B = (ROE - g) / (Ke - g); Justified P/E = payout x (1 + g) / (Ke - g)",
        metrics: [
          { label: "ROE", value: roe, format: "pct", source: roeSource },
          { label: "Payout", value: payout, format: "pct" },
          { label: "Retention", value: payout == null ? null : Math.max(0, Math.min(1, 1 - payout)), format: "pct" },
          { label: "g durable", value: asNumber(inputs.sustainable_growth), format: "pct", source: "ROE x retention" },
          { label: "g justifie", value: growth, format: "pct" },
          { label: "Ke", value: costOfEquity, format: "pct" },
        ],
      },
      {
        title: "Prix implicites",
        description: "Chaque multiple justifie est applique au multiple observe du titre.",
        table: {
          columns: ["Multiple", "Observe", "Justifie", "Calcul", "Prix implicite"],
          rows: rows.map((item) => [
            item.label,
            { value: item.own, format: "ratio" },
            { value: item.justifiedMultiple, format: "ratio" },
            item.calculation,
            { value: item.impliedPrice, format: "money" },
          ]),
        },
        metrics: [
          { label: "Median prix", value: computedFairValue, format: "money" },
          { label: "FV reportee", value: reportedFairValue, format: "money" },
        ],
      },
    ],
    checks: [
      { label: "Ke > g", ok: asNumber(inputs.cost_of_equity) != null && asNumber(inputs.growth) != null && asNumber(inputs.cost_of_equity) > asNumber(inputs.growth) },
      { label: "ROE source connue", ok: roe != null && roeSource != null },
      { label: "Prix courant disponible", ok: current != null && current > 0 },
      { label: "Au moins un multiple", ok: rows.length > 0 },
      { label: "Reconciliation mediane", ok: reportedFairValue == null ? computedFairValue != null : nearEqual(computedFairValue, reportedFairValue) },
    ],
  }
}

function formatPctText(value) {
  const numberValue = asNumber(value)
  return numberValue == null ? "-" : `${(numberValue * 100).toFixed(2)}%`
}

function buildRelativeMultiplesStory(row) {
  const inputs = asRecord(row.inputs)
  const peerStats = asRecord(inputs.peer_stats)
  const ownMultiples = asRecord(inputs.own_multiples)
  const implied = asRecord(asRecord(row.outputs).implied_prices)
  const rows = Object.entries(implied).map(([key, impliedPrice]) => {
    const peer = asNumber(asRecord(peerStats[key]).median)
    return {
      key,
      label: modelKeyLabel(key),
      own: asNumber(ownMultiples[key]),
      peer,
      impliedPrice: asNumber(impliedPrice),
      peerCount: asNumber(asRecord(peerStats[key]).count),
      scope: asRecord(peerStats[key]).scope,
    }
  })
  const evBridge = asRecord(inputs.ev_to_ebitda_bridge)
  const computedFairValue = median(rows.map((item) => item.impliedPrice))
  const reportedFairValue = asNumber(row.fair_value)
  return {
    model: "relative_multiples",
    title: "Lecture des comparables",
    summary: "Chaque ratio produit sa propre fair value/action; le modele retient ensuite la mediane de ces fair values.",
    steps: [
      {
        title: "Fair value par ratio",
        description: "Chaque ligne produit sa propre juste valeur/action: P/E, P/B, P/S et EV/EBITDA quand disponibles. EV/EBITDA passe par le pont EV vers capitaux propres.",
        table: {
          columns: ["Ratio", "Multiple titre", "Multiple pairs", "n/scope", "Fair value / action"],
          rows: rows.map((item) => [
            item.label,
            { value: item.own, format: "ratio" },
            { value: item.peer, format: "ratio" },
            [item.peerCount != null ? `n=${item.peerCount}` : null, item.scope].filter(Boolean).join(" / "),
            { value: item.impliedPrice, format: "money" },
          ]),
        },
        metrics: [
          ...rows.map((item) => ({ label: `FV ${item.label}`, value: item.impliedPrice, format: "money" })),
          { label: "Median FV", value: computedFairValue, format: "money" },
          { label: "FV reportee", value: reportedFairValue, format: "money" },
          { label: "Multiples", value: rows.length, format: "number" },
        ],
      },
      {
        title: "Pont EV/EBITDA",
        description: "Quand EV/EBITDA est retenu: EV = multiple pair x EBITDA, puis dette nette et actions donnent la valeur par action.",
        metrics: [
          { label: "EBITDA", value: asNumber(evBridge.ebitda), format: "money" },
          { label: "Dette nette", value: asNumber(evBridge.net_debt), format: "money", source: evBridge.net_debt_source },
          { label: "Actions", value: asNumber(evBridge.shares), format: "number" },
          { label: "FV EV/EBITDA", value: rows.find((item) => item.key === "EV_to_EBITDA")?.impliedPrice ?? null, format: "money" },
        ],
      },
    ],
    checks: [
      { label: "Pairs disponibles", ok: rows.length > 0 },
      { label: "Au moins 2 multiples", ok: rows.length >= 2 },
      { label: "Reconciliation mediane", ok: reportedFairValue == null ? computedFairValue != null : nearEqual(computedFairValue, reportedFairValue) },
    ],
  }
}

function buildReverseDcfStory(row, detail) {
  const inputs = asRecord(row.inputs)
  const outputs = asRecord(row.outputs)
  const wacc = asNumber(inputs.wacc)
  const fcfYield = asNumber(inputs.fcf_yield)
  const impliedGrowth = asNumber(outputs.implied_perpetual_growth)
  const terminalGrowth = assumption(detail, "terminal_growth_firm") ?? assumption(detail, "terminal_growth")
  return {
    model: "reverse_dcf",
    title: "Reverse DCF: hypothese implicite, pas pricing",
    summary: "Le resultat final n'est pas une juste valeur/action. C'est l'hypothese de croissance perpetuelle que le prix actuel exige.",
    steps: [
      {
        title: "Assumption implied by the current price",
        description: "Sous une perpetuite simple, le prix de marche impose une hypothese: g implicite = WACC - FCF yield.",
        formula: "g implicite = WACC - FCF yield",
        metrics: [
          { label: "Market cap", value: asNumber(inputs.market_cap), format: "money" },
          { label: "WACC", value: wacc, format: "pct" },
          { label: "FCF yield", value: fcfYield, format: "pct" },
          { label: "Resultat: g implicite", value: impliedGrowth, format: "pct", source: "assumption output" },
        ],
      },
      {
        title: "How to read it",
        description: typeof outputs.interpretation === "string" ? `${outputs.interpretation} This is an assumption diagnostic, not a valuation price.` : "Comparer g implicite au g terminal fondamental pour juger si le cours exige une croissance exigeante. Ce n'est pas une cible de prix.",
        metrics: [
          { label: "g terminal modele", value: terminalGrowth, format: "pct" },
          { label: "Ecart vs modele", value: impliedGrowth != null && terminalGrowth != null ? impliedGrowth - terminalGrowth : null, format: "pct" },
          { label: "Fair value/share", value: "N/A - diagnostic" },
        ],
      },
    ],
    checks: [
      { label: "FCF yield disponible", ok: fcfYield != null && fcfYield > 0 },
      { label: "WACC disponible", ok: wacc != null && wacc > 0 },
      { label: "g implicite calcule", ok: impliedGrowth != null },
      { label: "Pas un prix", ok: row.fair_value == null },
    ],
  }
}

export function buildValuationModelStory(row, detail) {
  switch (row?.model) {
    case "ddm":
      return buildDdmStory(row, detail)
    case "residual_income":
      return buildResidualIncomeStory(row, detail)
    case "justified_multiples":
      return buildJustifiedMultiplesStory(row, detail)
    case "relative_multiples":
      return buildRelativeMultiplesStory(row, detail)
    case "reverse_dcf":
      return buildReverseDcfStory(row, detail)
    default:
      return null
  }
}
