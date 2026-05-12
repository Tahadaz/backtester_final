function asText(value) {
  return typeof value === "string" ? value.trim() : ""
}

function asNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

export function tradeLedgerPositionDelta(row) {
  if (!row || typeof row !== "object") return 0

  const label = asText(row.marker_label).toLowerCase()
  if (label.includes("cover") || label.includes("buy") || label.includes("achat")) return 1
  if (label.includes("short") || label.includes("sell") || label.includes("vente")) return -1

  const side = asText(row.side ?? row.trade_side ?? row.direction).toLowerCase()
  if (side.includes("cover") || side.includes("buy") || side.includes("achat")) return 1
  if (side.includes("short") || side.includes("sell") || side.includes("vente")) return -1

  return 0
}

export function ledgerRowsWithDisplayPositions(rows) {
  if (!Array.isArray(rows)) return []
  if (rows.length === 0) return []

  const first = rows[0]
  const firstDelta = tradeLedgerPositionDelta(first)
  const firstBackendPosition = asNumber(first?.position)
  let currentPosition = firstBackendPosition != null ? firstBackendPosition - firstDelta : 0

  return rows.map((row) => {
    currentPosition += tradeLedgerPositionDelta(row)
    return { row, displayPosition: currentPosition }
  })
}
