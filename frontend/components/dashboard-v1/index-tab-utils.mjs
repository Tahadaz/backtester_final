export function normalizeDashboardIndexName(name) {
  return String(name ?? "").trim()
}

export function buildDashboardIndexPayload(name, symbols) {
  const normalizedName = normalizeDashboardIndexName(name)
  if (!normalizedName) return null

  return {
    name: normalizedName,
    symbols: Array.isArray(symbols) ? [...symbols] : [],
  }
}
