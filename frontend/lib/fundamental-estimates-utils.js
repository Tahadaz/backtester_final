export const FUNDAMENTAL_ESTIMATE_METRICS = [
  ["Chiffre_daffaires", "Chiffre d'affaires", "money"],
  ["Resultat_net", "Resultat net", "money"],
  ["Free_Cash_Flow", "Flux de tresorerie disponible", "money"],
  ["ROE", "ROE", "pct"],
  ["Operating_Margin", "Marge operationnelle", "pct"],
]

function asNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function metricValueForYear(detail, year, metric) {
  const row = Array.isArray(detail?.annual)
    ? detail.annual.find((item) => item?.statement_year === year)
    : null
  return asNumber(row?.metrics?.[metric])
}

function latestCompletedYear(detail, currentYear) {
  const annualYears = Array.isArray(detail?.annual)
    ? detail.annual
        .map((row) => asNumber(row?.statement_year))
        .filter((year) => year != null && year < currentYear)
    : []
  const latestStatementYear = asNumber(detail?.latest_statement_year)
  if (latestStatementYear != null && latestStatementYear < currentYear) {
    annualYears.push(latestStatementYear)
  }
  return annualYears.length > 0 ? Math.max(...annualYears) : currentYear - 1
}

export function buildFundamentalEstimateTable(detail, options = {}) {
  const currentYear = asNumber(options.currentYear) ?? new Date().getFullYear()
  const completedYear = latestCompletedYear(detail, currentYear)
  const actualYears = Array.isArray(detail?.annual)
    ? [...new Set(
        detail.annual
          .map((row) => asNumber(row?.statement_year))
          .filter((year) => year != null && year <= completedYear),
      )]
        .sort((a, b) => a - b)
        .slice(-3)
    : []
  const forecastYears = [completedYear + 1, completedYear + 2, completedYear + 3]
  const years = [...actualYears.map((year) => `${year}A`), ...forecastYears.map((year) => `${year}E`)]
  const requestedEstimateIndex = years.indexOf(`${currentYear}E`)
  const fallbackEstimateIndex = years.findIndex((year) => year.endsWith("E"))
  const currentEstimateIndex = requestedEstimateIndex >= 0
    ? requestedEstimateIndex
    : fallbackEstimateIndex >= 0
      ? fallbackEstimateIndex
      : null

  const rows = FUNDAMENTAL_ESTIMATE_METRICS.map(([metric, label, format]) => {
    const actualValues = actualYears.map((year) => metricValueForYear(detail, year, metric))
    const first = actualValues.find((value) => value != null)
    const latest =
      [...actualValues].reverse().find((value) => value != null)
      ?? asNumber(detail?.metrics?.[metric])
    const periods = Math.max(1, actualValues.filter((value) => value != null).length - 1)
    const fallbackGrowth = asNumber(detail?.metrics?.NetIncome_Growth) ?? 0.03
    const rawGrowth = first != null && latest != null && first > 0 && latest > 0
      ? (latest / first) ** (1 / periods) - 1
      : fallbackGrowth
    const growth = Math.max(-0.05, Math.min(0.10, rawGrowth))
    const forecastValues = forecastYears.map((_, index) => {
      if (latest == null) return null
      if (format === "pct") return latest
      return latest * (1 + growth) ** (index + 1)
    })
    return {
      label,
      format,
      values: [...actualValues, ...forecastValues],
    }
  })

  return {
    currentEstimateIndex,
    currentEstimateLabel: currentEstimateIndex == null ? null : years[currentEstimateIndex],
    years,
    rows,
  }
}
