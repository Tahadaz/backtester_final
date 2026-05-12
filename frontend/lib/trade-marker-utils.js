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

function dateKey(value) {
  const text = asText(value)
  if (!text) return null
  const key = text.slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(key) ? key : null
}

function markerKindFromLabel(value) {
  const label = asText(value).toLowerCase()
  if (!label) return null
  if (label.includes("short")) return "short"
  if (label.includes("cover")) return "cover"
  if (label.includes("sell") || label.includes("vente")) return "sell"
  if (label.includes("buy") || label.includes("achat")) return "buy"
  return null
}

function markerKindFromSide(row) {
  const side = asText(row.side ?? row.trade_side ?? row.direction).toLowerCase()
  if (!side) return null
  const position = asNumber(row.position)

  if (side.includes("cover")) return "cover"
  if (side.includes("short")) return "short"
  if (side.includes("achat") || side.includes("buy")) {
    return position != null && position > 0 ? "buy" : "cover"
  }
  if (side.includes("vente") || side.includes("sell")) {
    return position != null && position < 0 ? "short" : "sell"
  }
  return null
}

export function normalizeTradeMarkers(rows) {
  if (!Array.isArray(rows)) return []

  return rows
    .map((row, index) => {
      if (!row || typeof row !== "object") return null
      const date =
        dateKey(row.date)
        ?? dateKey(row.timestamp)
        ?? dateKey(row.open_date)
        ?? dateKey(row.close_date)
      if (!date) return null

      const markerLabel = asText(row.marker_label)
      const kind = markerKindFromLabel(markerLabel) ?? markerKindFromSide(row)
      if (!kind) return null

      return { date, kind, label: markerLabel, index }
    })
    .filter((marker) => marker != null)
    .sort((left, right) => {
      if (left.date < right.date) return -1
      if (left.date > right.date) return 1
      return left.index - right.index
    })
    .map(({ date, kind, label }) => (label ? { date, kind, label } : { date, kind }))
}
