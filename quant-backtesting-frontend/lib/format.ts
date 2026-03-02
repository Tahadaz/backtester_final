export function formatNumber(n: number | null | undefined, decimals = 2): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "--"
  return n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

export function formatPercent(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "--"
  return (n * 100).toFixed(2) + "%"
}

export function formatCurrency(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "--"
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n)
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "--"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  })
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "--"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function signalLabel(value: number | null | undefined): string {
  if (value === null || value === undefined) return "HOLD"
  if (value > 0) return "BUY"
  if (value < 0) return "SELL"
  return "HOLD"
}

export type SignalType = "buy" | "sell" | "hold"

export function signalType(value: number | null | undefined): SignalType {
  if (value === null || value === undefined) return "hold"
  if (value > 0) return "buy"
  if (value < 0) return "sell"
  return "hold"
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "--"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const now = Date.now()
  const diff = now - d.getTime()
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return "just now"
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}
