export type TradingHorizon = "weekly" | "monthly" | "quarterly"

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

export function resolveHorizonPreset(raw: unknown): HorizonPreset {
  const rawToken = String(raw ?? "").trim().toLowerCase()
  const aliases: Record<string, TradingHorizon> = {
    short: "weekly",
    medium: "monthly",
    long: "quarterly",
  }
  const token = (aliases[rawToken] ?? rawToken) as TradingHorizon
  if (token === "weekly" || token === "monthly" || token === "quarterly") {
    return HORIZON_PRESETS[token]
  }
  return HORIZON_PRESETS.monthly
}
