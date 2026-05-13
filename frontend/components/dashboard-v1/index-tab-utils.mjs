export function normalizeDashboardIndexName(name) {
  return String(name ?? "").trim()
}

export function normalizeDashboardIndexSymbol(symbol) {
  return String(symbol ?? "").trim().toUpperCase()
}

export function normalizeDashboardIndexShares(value) {
  if (value == null || value === "") return null
  const parsed = Number(String(value).replace(",", "."))
  if (!Number.isInteger(parsed) || parsed <= 0) return null
  return parsed
}

export function buildDashboardIndexPayload(name, components) {
  const normalizedName = normalizeDashboardIndexName(name)
  if (!normalizedName) return null

  const seen = new Set()
  const normalizedComponents = []
  for (const component of Array.isArray(components) ? components : []) {
    const symbol = normalizeDashboardIndexSymbol(component?.symbol)
    const shares = normalizeDashboardIndexShares(component?.shares)
    if (!symbol || shares == null || seen.has(symbol)) continue
    seen.add(symbol)
    normalizedComponents.push({ symbol, shares })
  }

  if (normalizedComponents.length === 0) return null

  return {
    name: normalizedName,
    components: normalizedComponents,
  }
}
