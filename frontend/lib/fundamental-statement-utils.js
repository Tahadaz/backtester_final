export const FINANCIAL_STATEMENT_TABS = [
  { value: "summary", label: "Resume financier" },
  { value: "income", label: "Compte de resultat" },
  { value: "balance", label: "Bilan" },
  { value: "cashflow", label: "Flux de tresorerie" },
  { value: "ratios", label: "Ratios" },
  { value: "dividends", label: "Dividendes" },
  { value: "earnings", label: "Resultats" },
]

const PERIOD_ORDER = {
  annual: 0,
  quarterly: 1,
  semiannual: 2,
}

const PERIOD_LABELS = {
  annual: "Annuel",
  quarterly: "Trimestriel",
  semiannual: "Semestriel",
}

const MAX_PERIOD_COLUMNS = 6

const METRIC_ALIASES = {
  revenue: ["Clean_Chiffre_daffaires", "Chiffre_daffaires", "Revenue", "Total_Revenue", "Total_Revenues", "TotalRevenue"],
  gross_profit: ["Gross_Profit", "GrossProfit", "Marge_Brute"],
  ebitda: ["EBITDA", "Normalized_EBITDA"],
  ebit: ["EBIT", "Operating_Income", "OperatingIncome", "Resultat_Exploitation"],
  net_income: ["Clean_Resultat_net", "Resultat_net", "NetIncome", "Net_Income", "IS_Net_Income"],
  total_assets: ["Total_Assets", "Total_Actif", "Actif_Total"],
  current_assets: ["Current_Assets", "Total_Current_Assets", "Actif_Courant"],
  cash: ["Cash_and_Equivalents", "BS_Cash_and_Equivalents", "Cash", "Tresorerie"],
  total_liabilities: ["Total_Liabilities", "Total_Passif", "Passif_Total"],
  current_liabilities: ["Current_Liabilities", "Total_Current_Liabilities", "Passif_Courant"],
  total_debt: ["Total_Debt", "Debt", "Financial_Debt", "Dette_Financiere", "Dettes"],
  net_debt: ["NetDebt", "Net_Debt"],
  total_equity: [
    "Clean_Capitaux_Propres",
    "Clean_Capitaux_propres",
    "Capitaux_Propres",
    "Capitaux_propres",
    "Capitaux_propres_part_groupe",
    "Total_Equity",
    "Book_Equity",
    "Equity",
    "Fonds_Propres",
  ],
  retained_earnings: ["Retained_Earnings", "Reserves"],
  operating_cf: ["CF_Operating", "Operating_Cash_Flow", "Cash_from_Operations", "Cash_From_Operations", "Flux_Tresorerie_Exploitation"],
  investing_cf: ["CF_Investing", "Investing_Cash_Flow", "Cash_from_Investing", "Cash_From_Investing"],
  financing_cf: ["CF_Financing", "Financing_Cash_Flow", "Cash_from_Financing", "Cash_From_Financing"],
  fx_effect: ["CF_FX_Effect", "FX_Effect"],
  beginning_cash: ["CFS_Beginning_Cash", "Beginning_Cash"],
  ending_cash: ["CFS_Ending_Cash", "Ending_Cash"],
  capex: ["Capex", "CAPEX", "Capital_Expenditure"],
  free_cash_flow: ["Free_Cash_Flow", "Levered_Free_Cash_Flow"],
  dividends_paid: ["Clean_Dividendes", "Dividendes", "Dividends_Paid", "Cash_Dividends_Paid"],
  per: ["PER", "Price_to_Earnings", "PE_Ratio"],
  price_to_book: ["Price_to_Book", "P_B"],
  price_to_sales: ["Price_to_Sales", "P_S"],
  ev_to_ebitda: ["EV_to_EBITDA", "Enterprise_Value_to_EBITDA"],
  debt_to_equity: ["Debt_to_Equity", "Debt_Equity"],
  net_debt_to_ebitda: ["NetDebt_to_EBITDA", "Net_Debt_to_EBITDA"],
  roe: ["ROE"],
  roa: ["ROA"],
  operating_margin: ["Operating_Margin"],
  net_margin: ["Net_Margin"],
  fcf_margin: ["FCF_Margin"],
  current_ratio: ["Current_Ratio"],
  cash_ratio: ["Cash_Ratio"],
  dividend_yield: ["Dividend_Yield"],
  dividend_payout: ["Dividend_Payout"],
  dividend_coverage: ["Dividend_Coverage"],
  revenue_growth: ["Revenue_Growth_YoY", "Revenue_Growth"],
  net_income_growth: ["NetIncome_Growth", "Net_Income_Growth"],
  eps: ["EPS", "Diluted_EPS", "Basic_EPS"],
}

const SUMMARY_KEY_RATIOS = [
  row("current_price", "Cours actuel", ["Current_Price"], "money"),
  row("market_cap", "Capitalisation boursiere", ["MarketCap_Calc"], "money"),
  row("per", "PER", METRIC_ALIASES.per, "ratio"),
  row("price_to_book", "Cours / valeur comptable", METRIC_ALIASES.price_to_book, "ratio"),
  row("debt_to_equity", "Dette / capitaux propres", METRIC_ALIASES.debt_to_equity, "percent"),
  row("roe", "Rentabilite des capitaux propres", METRIC_ALIASES.roe, "percent"),
  row("dividend_yield", "Rendement du dividende", METRIC_ALIASES.dividend_yield, "percent"),
  row("ebitda", "EBITDA", METRIC_ALIASES.ebitda, "money"),
  row("fair_value", "Juste valeur", ["Fair_Value", "Target_Price"], "money"),
  row("upside", "Potentiel vs juste valeur", ["Upside_Pct"], "percent"),
]

const SUMMARY_HIGHLIGHTS = [
  section("Compte de resultat"),
  row("revenue", "Chiffre d'affaires", METRIC_ALIASES.revenue, "money"),
  row("ebit", "Resultat d'exploitation", METRIC_ALIASES.ebit, "money"),
  row("net_income", "Resultat net", METRIC_ALIASES.net_income, "money"),
  section("Bilan"),
  row("total_assets", "Total actif", METRIC_ALIASES.total_assets, "money"),
  row("total_liabilities", "Total passif", METRIC_ALIASES.total_liabilities, "money"),
  row("total_equity", "Capitaux propres", METRIC_ALIASES.total_equity, "money"),
  section("Flux de tresorerie"),
  row("free_cash_flow", "Flux de tresorerie disponible", METRIC_ALIASES.free_cash_flow, "money"),
  row("operating_cf", "Flux d'exploitation", METRIC_ALIASES.operating_cf, "money"),
  row("investing_cf", "Flux d'investissement", METRIC_ALIASES.investing_cf, "money"),
  row("financing_cf", "Flux de financement", METRIC_ALIASES.financing_cf, "money"),
  row("net_change_cash", "Variation nette de tresorerie", [], "money", deriveNetChangeInCash),
]

const STATEMENT_ROWS = {
  income: [
    row("revenue", "Chiffre d'affaires", METRIC_ALIASES.revenue, "money"),
    row("gross_profit", "Marge brute", METRIC_ALIASES.gross_profit, "money"),
    row("ebitda", "EBITDA", METRIC_ALIASES.ebitda, "money"),
    row("ebit", "Resultat d'exploitation", METRIC_ALIASES.ebit, "money"),
    row("net_income", "Resultat net", METRIC_ALIASES.net_income, "money"),
  ],
  balance: [
    section("Actif"),
    row("total_assets", "Total actif", METRIC_ALIASES.total_assets, "money"),
    row("current_assets", "Actif courant", METRIC_ALIASES.current_assets, "money"),
    row("cash", "Tresorerie et equivalents", METRIC_ALIASES.cash, "money"),
    section("Passif"),
    row("total_liabilities", "Total passif", METRIC_ALIASES.total_liabilities, "money"),
    row("current_liabilities", "Passif courant", METRIC_ALIASES.current_liabilities, "money"),
    row("total_debt", "Dette totale", METRIC_ALIASES.total_debt, "money"),
    row("net_debt", "Dette nette", METRIC_ALIASES.net_debt, "money"),
    section("Capitaux propres"),
    row("total_equity", "Capitaux propres", METRIC_ALIASES.total_equity, "money"),
    row("retained_earnings", "Resultats reportes", METRIC_ALIASES.retained_earnings, "money"),
  ],
  cashflow: [
    row("operating_cf", "Flux d'exploitation", METRIC_ALIASES.operating_cf, "money"),
    row("investing_cf", "Flux d'investissement", METRIC_ALIASES.investing_cf, "money"),
    row("financing_cf", "Flux de financement", METRIC_ALIASES.financing_cf, "money"),
    row("capex", "Depenses d'investissement", METRIC_ALIASES.capex, "money"),
    row("free_cash_flow", "Flux de tresorerie disponible", METRIC_ALIASES.free_cash_flow, "money"),
    row("dividends_paid", "Dividendes verses", METRIC_ALIASES.dividends_paid, "money"),
    row("beginning_cash", "Tresorerie debut periode", METRIC_ALIASES.beginning_cash, "money"),
    row("ending_cash", "Tresorerie fin periode", METRIC_ALIASES.ending_cash, "money"),
    row("net_change_cash", "Variation nette de tresorerie", [], "money", deriveNetChangeInCash),
  ],
  ratios: [
    row("per", "PER", METRIC_ALIASES.per, "ratio"),
    row("price_to_book", "Cours / valeur comptable", METRIC_ALIASES.price_to_book, "ratio"),
    row("price_to_sales", "Cours / chiffre d'affaires", METRIC_ALIASES.price_to_sales, "ratio"),
    row("ev_to_ebitda", "EV/EBITDA", METRIC_ALIASES.ev_to_ebitda, "ratio"),
    row("debt_to_equity", "Dette / capitaux propres", METRIC_ALIASES.debt_to_equity, "percent"),
    row("net_debt_to_ebitda", "Dette nette / EBITDA", METRIC_ALIASES.net_debt_to_ebitda, "ratio"),
    row("roe", "Rentabilite des capitaux propres", METRIC_ALIASES.roe, "percent"),
    row("roa", "Rentabilite des actifs", METRIC_ALIASES.roa, "percent"),
    row("operating_margin", "Marge operationnelle", METRIC_ALIASES.operating_margin, "percent"),
    row("net_margin", "Marge nette", METRIC_ALIASES.net_margin, "percent"),
    row("fcf_margin", "Marge de flux de tresorerie disponible", METRIC_ALIASES.fcf_margin, "percent"),
    row("current_ratio", "Ratio de liquidite generale", METRIC_ALIASES.current_ratio, "ratio"),
    row("cash_ratio", "Ratio de tresorerie", METRIC_ALIASES.cash_ratio, "ratio"),
  ],
  dividends: [
    row("dividends_paid", "Dividendes verses", METRIC_ALIASES.dividends_paid, "money"),
    row("dividend_per_share", "Dividende par action", [], "per_share", derivePerShare(METRIC_ALIASES.dividends_paid)),
    row("dividend_yield", "Rendement du dividende", METRIC_ALIASES.dividend_yield, "percent"),
    row("dividend_payout", "Taux de distribution", METRIC_ALIASES.dividend_payout, "percent"),
    row("dividend_coverage", "Couverture du dividende", METRIC_ALIASES.dividend_coverage, "ratio"),
  ],
  earnings: [
    row("revenue", "Chiffre d'affaires", METRIC_ALIASES.revenue, "money"),
    row("net_income", "Resultat net", METRIC_ALIASES.net_income, "money"),
    row("eps", "Resultat par action", METRIC_ALIASES.eps, "per_share", derivePerShare(METRIC_ALIASES.net_income)),
    row("revenue_growth", "Croissance du chiffre d'affaires", METRIC_ALIASES.revenue_growth, "percent"),
    row("net_income_growth", "Croissance du resultat net", METRIC_ALIASES.net_income_growth, "percent"),
    row("operating_margin", "Marge operationnelle", METRIC_ALIASES.operating_margin, "percent"),
  ],
}

function row(key, label, aliases, format, derive) {
  return { type: "row", key, label, aliases, format, derive }
}

function section(label) {
  return { type: "section", key: `section:${label}`, label }
}

function asNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function normalizeMetricName(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]/g, "")
}

function metricLookup(metrics) {
  const exact = metrics && typeof metrics === "object" ? metrics : {}
  const normalized = new Map()
  for (const key of Object.keys(exact)) {
    normalized.set(normalizeMetricName(key), key)
  }
  return { exact, normalized }
}

function pickMetric(metrics, aliases) {
  const lookup = metricLookup(metrics)
  for (const alias of aliases) {
    const exactValue = asNumber(lookup.exact[alias])
    if (exactValue != null) return { value: exactValue, sourceMetric: alias }
    const actualKey = lookup.normalized.get(normalizeMetricName(alias))
    const normalizedValue = actualKey == null ? null : asNumber(lookup.exact[actualKey])
    if (normalizedValue != null) return { value: normalizedValue, sourceMetric: actualKey }
  }
  return { value: null, sourceMetric: null }
}

function sharesOutstanding(detail) {
  return pickMetric(detail?.metrics || {}, ["Shares_Outstanding", "shares_outstanding"]).value
}

function derivePerShare(aliases) {
  return (metrics, detail) => {
    const numerator = pickMetric(metrics, aliases)
    const shares = sharesOutstanding(detail)
    if (numerator.value == null || shares == null || shares <= 0) return { value: null, sourceMetric: numerator.sourceMetric }
    return { value: numerator.value / shares, sourceMetric: numerator.sourceMetric }
  }
}

function deriveNetChangeInCash(metrics) {
  const direct = pickMetric(metrics, ["Net_Change_in_Cash", "Net_Change_Cash"])
  if (direct.value != null) return direct
  const ending = pickMetric(metrics, METRIC_ALIASES.ending_cash)
  const beginning = pickMetric(metrics, METRIC_ALIASES.beginning_cash)
  if (ending.value == null || beginning.value == null) return { value: null, sourceMetric: null }
  return { value: ending.value - beginning.value, sourceMetric: `${ending.sourceMetric}-${beginning.sourceMetric}` }
}

function periodKey(periodType, fiscalYear, label) {
  return `${periodType}:${fiscalYear}:${label || ""}`
}

function cleanPeriodLabel(value, fallback) {
  const label = String(value || "").trim()
  return label || fallback
}

function addPeriodMetric(groups, period, metricName, value) {
  if (!metricName) return
  const current = groups.get(period.key) || { ...period, metrics: {}, sourceMetrics: {} }
  const numeric = asNumber(value)
  if (numeric != null && current.metrics[metricName] == null) {
    current.metrics[metricName] = numeric
    current.sourceMetrics[metricName] = metricName
  }
  groups.set(period.key, current)
}

function collectPeriods(detail, periodType) {
  const groups = new Map()
  if (periodType === "annual") {
    for (const item of Array.isArray(detail?.annual) ? detail.annual : []) {
      const fiscalYear = asNumber(item?.statement_year)
      if (fiscalYear == null) continue
      const label = String(fiscalYear)
      const key = periodKey("annual", fiscalYear, "FY")
      const period = { key, fiscalYear, periodType: "annual", periodLabel: "FY", label, subLabel: null, metrics: {}, sourceMetrics: {} }
      for (const [metricName, value] of Object.entries(item?.metrics || {})) {
        addPeriodMetric(groups, period, metricName, value)
      }
    }
  }

  for (const item of Array.isArray(detail?.period_metrics) ? detail.period_metrics : []) {
    const itemPeriodType = String(item?.period_type || "annual").toLowerCase()
    if (itemPeriodType !== periodType) continue
    const fiscalYear = asNumber(item?.fiscal_year)
    if (fiscalYear == null) continue
    const periodLabel = cleanPeriodLabel(item?.period_label, itemPeriodType === "annual" ? "FY" : "")
    const label = itemPeriodType === "annual" ? String(fiscalYear) : `${fiscalYear} ${periodLabel}`.trim()
    const key = periodKey(itemPeriodType, fiscalYear, periodLabel)
    const period = {
      key,
      fiscalYear,
      periodType: itemPeriodType,
      periodLabel,
      label,
      subLabel: item?.period_end_date ? String(item.period_end_date).slice(5, 10) : null,
      metrics: {},
      sourceMetrics: {},
    }
    addPeriodMetric(groups, period, item.metric_name, item.metric_value)
  }

  return Array.from(groups.values())
    .filter((period) => Object.keys(period.metrics).length > 0)
    .sort((left, right) => {
      if (left.fiscalYear !== right.fiscalYear) return left.fiscalYear - right.fiscalYear
      return String(left.periodLabel).localeCompare(String(right.periodLabel))
    })
    .slice(-MAX_PERIOD_COLUMNS)
}

function latestPeriod(detail) {
  const metrics = {
    ...(detail?.metrics || {}),
    Fair_Value: detail?.ensemble?.fair_value_base,
    Upside_Pct: detail?.ensemble?.upside_pct,
  }
  return {
    key: "latest",
    fiscalYear: asNumber(detail?.latest_statement_year) || 0,
    periodType: "latest",
    periodLabel: "Recent",
    label: detail?.latest_statement_year ? `Ex. ${detail.latest_statement_year}` : "Recent",
    subLabel: null,
    metrics,
    sourceMetrics: {},
  }
}

function buildRows(definitions, periods, detail) {
  const rows = []
  let activeSection = null
  for (const definition of definitions) {
    if (definition.type === "section") {
      activeSection = definition.label
      continue
    }
    const values = periods.map((period) => {
      const direct = pickMetric(period.metrics, definition.aliases || [])
      const resolved = direct.value == null && definition.derive
        ? definition.derive(period.metrics, detail)
        : direct
      return {
        periodKey: period.key,
        value: resolved.value,
        sourceMetric: resolved.sourceMetric,
      }
    })
    if (!values.some((item) => item.value != null)) continue
    rows.push({
      key: definition.key,
      label: definition.label,
      format: definition.format,
      section: activeSection,
      values,
    })
  }
  return rows
}

function definitionsFor(tab) {
  if (tab === "summary") return SUMMARY_HIGHLIGHTS
  return STATEMENT_ROWS[tab] || []
}

export function financialPeriodLabel(periodType) {
  return PERIOD_LABELS[periodType] || periodType
}

export function availableFinancialPeriodTypes(detail) {
  const types = new Set()
  if (Array.isArray(detail?.annual) && detail.annual.length > 0) types.add("annual")
  for (const item of Array.isArray(detail?.period_metrics) ? detail.period_metrics : []) {
    if (item?.metric_value == null) continue
    const type = String(item?.period_type || "annual").toLowerCase()
    if (type) types.add(type)
  }
  if (types.size === 0 && detail?.metrics && Object.keys(detail.metrics).length > 0) types.add("annual")
  return Array.from(types).sort((left, right) => (PERIOD_ORDER[left] ?? 99) - (PERIOD_ORDER[right] ?? 99))
}

export function buildFinancialStatementTable(detail, tab, periodType = "annual") {
  let periods = collectPeriods(detail, periodType)
  let rows = buildRows(definitionsFor(tab), periods, detail)
  if (rows.length === 0 && detail?.metrics && Object.keys(detail.metrics).length > 0) {
    periods = [latestPeriod(detail)]
    rows = buildRows(definitionsFor(tab), periods, detail)
  }
  return { periods, rows }
}

export function buildFinancialSummary(detail, periodType = "annual") {
  const latest = latestPeriod(detail)
  const keyRatios = buildRows(SUMMARY_KEY_RATIOS, [latest], detail).map((item) => ({
    ...item,
    value: item.values[0]?.value ?? null,
    sourceMetric: item.values[0]?.sourceMetric ?? null,
  }))
  return {
    keyRatios,
    highlights: buildFinancialStatementTable(detail, "summary", periodType),
  }
}
