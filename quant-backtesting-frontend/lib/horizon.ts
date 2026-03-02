export type TradingHorizon = "short" | "medium" | "long"

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
  short: {
    value: "short",
    label: "Court terme",
    displayLabel: "Court terme — train 252j / test 63j / 5 ans",
    trainWindow: 252,
    testWindow: 63,
    stepSize: 21,
    useTestWindow: true,
  },
  medium: {
    value: "medium",
    label: "Moyen terme",
    displayLabel: "Moyen terme — train 504j / test 126j / 10 ans",
    trainWindow: 504,
    testWindow: 126,
    stepSize: 21,
    useTestWindow: true,
  },
  long: {
    value: "long",
    label: "Long terme",
    displayLabel: "Long terme — train 756j / test 252j / 20 ans",
    trainWindow: 756,
    testWindow: 252,
    stepSize: 21,
    useTestWindow: true,
  },
}

export const HORIZON_OPTIONS: Array<{ value: TradingHorizon; label: string }> = [
  { value: "short", label: "Court terme" },
  { value: "medium", label: "Moyen terme" },
  { value: "long", label: "Long terme" },
]

export function resolveHorizonPreset(raw: unknown): HorizonPreset {
  const token = String(raw ?? "").trim().toLowerCase() as TradingHorizon
  if (token === "short" || token === "long" || token === "medium") {
    return HORIZON_PRESETS[token]
  }
  return HORIZON_PRESETS.medium
}
