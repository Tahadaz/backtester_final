export const HORIZONS = [
  { value: "short" as const, label: "Court terme" },
  { value: "medium" as const, label: "Moyen terme" },
  { value: "long" as const, label: "Long terme" },
] as const

export const VIEWS = [
  { value: "stocks" as const, label: "Actions" },
  { value: "sectors" as const, label: "Secteurs" },
  { value: "index" as const, label: "Indices" },
] as const

export const FAMILY_LABELS: Record<string, string> = {
  trend: "Tendance",
  momentum: "Momentum",
  oscillation: "Oscillation",
  volume: "Volume",
}

export const FAMILY_SHORT_LABELS: Record<string, string> = {
  trend: "Tendance",
  momentum: "Momentum",
  oscillation: "Oscillation",
  volume: "Volume",
}

export const FAMILY_ORDER = ["trend", "momentum", "oscillation", "volume"] as const

const GREEN_STRONG = "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
const GREEN = "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
const GREY = "bg-zinc-500/10 text-zinc-600 dark:text-zinc-400"
const RED = "bg-red-500/10 text-red-600 dark:text-red-400"
const RED_STRONG = "bg-red-500/15 text-red-700 dark:text-red-400"

export const SIGNAL_BADGE_COLORS: Record<string, string> = {
  "Tres haussier": GREEN_STRONG,
  "Très haussier": GREEN_STRONG,
  Haussier: GREEN,
  Neutre: GREY,
  "Pas disponible": GREY,
  Indisponible: GREY,
  Baissier: RED,
  "Tres baissier": RED_STRONG,
  "Très baissier": RED_STRONG,

  "Tres survendu": GREEN_STRONG,
  "Très survendu": GREEN_STRONG,
  Survendu: GREEN,
  Normal: GREY,
  Surachete: RED,
  Suracheté: RED,
  "Tres surachete": RED_STRONG,
  "Très suracheté": RED_STRONG,

  "Forte accumulation": GREEN_STRONG,
  Accumulation: GREEN,
  Distribution: RED,
  "Forte distribution": RED_STRONG,

  "Achat fort": GREEN_STRONG,
  Achat: GREEN,
  Vente: RED,
  "Vente forte": RED_STRONG,
}

export const SIGNAL_BADGE_FALLBACK = GREY

export function scoreBarColor(score: number): string {
  if (score > 15) return "bg-emerald-500"
  if (score < -15) return "bg-red-500"
  return "bg-zinc-400"
}

export function formatScore(score: number | null | undefined): string {
  if (score == null) return "-"
  const sign = score > 0 ? "+" : ""
  return `${sign}${score.toFixed(1)}`
}

function signalTypeLabel(signalType: "trend" | "oscillator" | "volume" | "aggregate", score: number): string {
  if (signalType === "trend") {
    if (score > 50) return "Très haussier"
    if (score > 15) return "Haussier"
    if (score >= -15) return "Neutre"
    if (score >= -50) return "Baissier"
    return "Très baissier"
  }
  if (signalType === "oscillator") {
    if (score > 50) return "Très survendu"
    if (score > 15) return "Survendu"
    if (score >= -15) return "Normal"
    if (score >= -50) return "Suracheté"
    return "Très suracheté"
  }
  if (signalType === "volume") {
    if (score > 50) return "Forte accumulation"
    if (score > 15) return "Accumulation"
    if (score >= -15) return "Neutre"
    if (score >= -50) return "Distribution"
    return "Forte distribution"
  }
  if (score > 50) return "Achat fort"
  if (score > 15) return "Achat"
  if (score >= -15) return "Neutre"
  if (score >= -50) return "Vente"
  return "Vente forte"
}

export function aggregateScoreLabel(score: number): string {
  return signalTypeLabel("aggregate", score)
}

export function familyScoreLabel(family: string, score: number): string {
  if (family === "oscillation") return signalTypeLabel("oscillator", score)
  if (family === "volume") return signalTypeLabel("volume", score)
  return signalTypeLabel("trend", score)
}
