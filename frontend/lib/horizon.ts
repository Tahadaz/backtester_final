export type TradingHorizon = "weekly" | "monthly" | "quarterly"
export type LegacyTradingHorizon = "short" | "medium" | "long"
export type HorizonAlias = TradingHorizon | LegacyTradingHorizon

export type HorizonPreset = {
  value: TradingHorizon
  label: string
  displayLabel: string
  trainWindow: number
  testWindow: number
  stepSize: number
  useTestWindow: boolean
}

export const HORIZON_PRESETS: Record<TradingHorizon, HorizonPreset> = {
  weekly: {
    value: "weekly",
    label: "Hebdomadaire",
    displayLabel: "Hebdomadaire - prediction 1-5j / train 252j / OOS 21j / 5 ans",
    trainWindow: 252,
    testWindow: 21,
    stepSize: 21,
    useTestWindow: true,
  },
  monthly: {
    value: "monthly",
    label: "Mensuel",
    displayLabel: "Mensuel - prediction 6-21j / train 504j / OOS 63j / 10 ans",
    trainWindow: 504,
    testWindow: 63,
    stepSize: 63,
    useTestWindow: true,
  },
  quarterly: {
    value: "quarterly",
    label: "Trimestriel",
    displayLabel: "Trimestriel - prediction 22-63j / train 756j / OOS 126j / 20 ans",
    trainWindow: 756,
    testWindow: 126,
    stepSize: 126,
    useTestWindow: true,
  },
}

export const HORIZON_OPTIONS: Array<{ value: TradingHorizon; label: string }> = [
  { value: "weekly", label: "Hebdomadaire" },
  { value: "monthly", label: "Mensuel" },
  { value: "quarterly", label: "Trimestriel" },
]

export const HORIZON_LABELS_FR: Record<TradingHorizon, string> = {
  weekly: "Hebdomadaire",
  monthly: "Mensuel",
  quarterly: "Trimestriel",
}

export const LEGACY_HORIZON_ALIASES: Record<LegacyTradingHorizon, TradingHorizon> = {
  short: "weekly",
  medium: "monthly",
  long: "quarterly",
}

export const CANONICAL_TO_LEGACY_HORIZON: Record<TradingHorizon, LegacyTradingHorizon> = {
  weekly: "short",
  monthly: "medium",
  quarterly: "long",
}

export const HORIZON_DAYS_LABELS_FR: Record<TradingHorizon, string> = {
  weekly: "Hebdomadaire (1-5j)",
  monthly: "Mensuel (6-21j)",
  quarterly: "Trimestriel (22-63j)",
}

export const LEGACY_HORIZON_DAYS_LABELS_FR: Record<LegacyTradingHorizon, string> = {
  short: "Hebdomadaire (1-5j)",
  medium: "Mensuel (6-21j)",
  long: "Trimestriel (22-200j)",
}

export function resolveHorizonPreset(raw: unknown): HorizonPreset {
  const rawToken = String(raw ?? "").trim().toLowerCase()
  const token = (LEGACY_HORIZON_ALIASES[rawToken as LegacyTradingHorizon] ?? rawToken) as TradingHorizon
  if (token === "weekly" || token === "monthly" || token === "quarterly") {
    return HORIZON_PRESETS[token]
  }
  return HORIZON_PRESETS.monthly
}

export function horizonLabel(raw: unknown): string {
  return resolveHorizonPreset(raw).label
}

export function horizonLabelWithDays(raw: unknown): string {
  const rawToken = String(raw ?? "").trim().toLowerCase()
  if (rawToken === "short" || rawToken === "medium" || rawToken === "long") {
    return LEGACY_HORIZON_DAYS_LABELS_FR[rawToken]
  }
  return HORIZON_DAYS_LABELS_FR[resolveHorizonPreset(raw).value]
}

export function legacyHorizonKey(raw: unknown): LegacyTradingHorizon {
  return CANONICAL_TO_LEGACY_HORIZON[resolveHorizonPreset(raw).value]
}
