function formatDateValue(value) {
  if (typeof value !== "string") return null
  const trimmed = value.trim()
  if (!trimmed) return null
  const dateMatch = trimmed.match(/^(\d{4}-\d{2}-\d{2})/)
  return dateMatch ? dateMatch[1] : trimmed
}

function formatBarValue(value) {
  if (typeof value === "number" && Number.isFinite(value)) return `bar ${value}`
  if (typeof value !== "string") return null

  const trimmed = value.trim()
  if (!trimmed) return null
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) return `bar ${trimmed}`
  return formatDateValue(trimmed)
}

function formatFoldEndpoint(fold, phase, boundary) {
  const dateValue = formatDateValue(fold?.[`${phase}_${boundary}_date`])
  if (dateValue) return dateValue

  const legacyValue = fold?.[`${phase}_${boundary}`]
  const legacyDisplay = formatBarValue(legacyValue)
  if (legacyDisplay) return legacyDisplay

  return formatBarValue(fold?.[`${phase}_${boundary}_idx`])
}

export function formatWfoFoldRange(fold, phase) {
  const start = formatFoldEndpoint(fold, phase, "start")
  const end = formatFoldEndpoint(fold, phase, "end")
  if (!start && !end) return "--"
  return `${start ?? "--"} to ${end ?? "--"}`
}
