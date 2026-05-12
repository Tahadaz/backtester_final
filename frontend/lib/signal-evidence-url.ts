import type { Horizon } from "@/lib/dashboard-types"

type EvidenceSource = "auto" | "signal_engine" | "wfo"

export function signalPageHorizon(horizon: Horizon | string): "weekly" | "monthly" | "quarterly" {
  const token = String(horizon ?? "").trim().toLowerCase()
  if (token === "weekly" || token === "short") return "weekly"
  if (token === "quarterly" || token === "long") return "quarterly"
  return "monthly"
}

export function signalEvidenceUrl({
  symbol,
  horizon,
  view = "expanded",
  source = "auto",
  side,
  evidenceVariant,
  variant,
  tab = "evidence",
}: {
  symbol: string
  horizon: Horizon | string
  view?: string
  source?: EvidenceSource
  side?: string
  evidenceVariant?: string
  variant?: string
  tab?: string
}): string {
  const params = new URLSearchParams()
  params.set("symbol", symbol)
  params.set("horizon", signalPageHorizon(horizon))
  params.set("view", view)
  params.set("source", source)
  params.set("tab", tab)
  if (side) params.set("side", side)
  if (evidenceVariant) params.set("evidence_variant", evidenceVariant)
  if (variant) params.set("variant", variant)
  return `/signals?${params.toString()}`
}
