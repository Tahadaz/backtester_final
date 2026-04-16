"use client"

export type SortBy = "adv20" | "signal_score"
export type SortDir = "asc" | "desc"
export type StrategyType = "trend_following" | "mean_reversion"
export type FamilyId = "sma" | "rsi" | "macd" | "obv"
export type HorizonKey = "short" | "medium" | "long"
export type ConfigOption = "A" | "B" | "C" | "D" | "E"
export type RuleOperator = ">" | ">=" | "<" | "<="
export type ScoreVariable = string
export type SignalSourceMode = "family_ensemble" | "indicator_rows"

export type WFOParamSearchSpace<T = number> = {
  scan_min: T
  scan_max: T
  scan_step: T
}

export type WFOParam<T = number> = {
  mode: "manual" | "wfo"
  value: T
  scan_min?: T
  scan_max?: T
  scan_step?: T
  search_spaces_by_horizon?: Partial<Record<HorizonKey, WFOParamSearchSpace<T>>>
}

export type IndicatorRowConfigV2 = {
  id: string
  enabled: boolean
  score_key: string
  label: string
  params: Record<string, WFOParam<number>>
}

export type FamilyConfigV2 = {
  enabled: boolean
  source_mode: SignalSourceMode
  rows: IndicatorRowConfigV2[]
}

export type RuleConditionV2 = {
  id: string
  variable: ScoreVariable
  operator: RuleOperator
  threshold: WFOParam<number>
}

export type EntryRuleV2 = {
  id: string
  label: string
  config_option: ConfigOption
  conditions: RuleConditionV2[]
  sizing: {
    mode: "manual" | "kelly_wfo" | "wfo"
    manual_pct?: number
    size_pct?: WFOParam<number> | null
    kelly_modifier?: WFOParam<number> | null
  }
}

export type ExitRuleV2 = {
  id: string
  label: string
  config_option: ConfigOption
  conditions: RuleConditionV2[]
  sizing: {
    mode: "manual" | "kelly_wfo" | "wfo"
    manual_pct?: number
    reduction_pct?: WFOParam<number> | null
    kelly_modifier?: WFOParam<number> | null
  }
}

export type RiskConfigV2 = {
  stop_loss: {
    mode: "manual_pct" | "atr_based" | "wfo"
    manual_pct?: number
    atr_multiplier?: WFOParam<number>
  }
  take_profit: {
    mode: "manual_pct" | "rr_target" | "wfo"
    manual_pct?: number
    rr_ratio?: WFOParam<number>
  }
  cooldown_bars: WFOParam<number>
  time_stop: {
    enabled: boolean
    bars: WFOParam<number>
  }
  trailing_stop_enabled: boolean
  max_position_pct: number
  max_sector_pct: number
}

export type StockStrategyConfigV2 = {
  strategy_type: StrategyType
  signal_construction: {
    families: Record<FamilyId, FamilyConfigV2>
  }
  entry_rules: EntryRuleV2[]
  exit_rules: ExitRuleV2[]
  risk: RiskConfigV2
}

export type StrategyConfigV2 = {
  schema_version: 3
  app_domain: "four_pages"
  legacy_snapshot: Record<string, unknown> | null
  portfolio: {
    total_capital_mad: number
    universe: {
      basket: string[]
      sector_filter: string[]
      min_abs_signal: number
      min_adv20: number
      sort_by: SortBy
      sort_dir: SortDir
    }
    allocation: {
      method: "hrp"
      hrp_lookback_bars: number
      manual_overrides_by_symbol: Record<string, { enabled: boolean; capital_mad: number }>
    }
  }
  stocks: Record<string, StockStrategyConfigV2>
  snapshot: Record<string, unknown> | null
}

const FAMILY_SCORE_KEYS: Record<FamilyId, string> = {
  sma: "trend_score",
  macd: "momentum_score",
  rsi: "oscillation_score",
  obv: "volume_score",
}

const FAMILY_SCORE_LABELS: Record<FamilyId, string> = {
  sma: "Trend Score",
  macd: "Momentum Score",
  rsi: "Oscillation Score",
  obv: "Volume Score",
}

export const HORIZON_KEYS: HorizonKey[] = ["short", "medium", "long"]

const SIGNAL_CONSTRUCTION_WFO_DEFAULTS: Record<
  FamilyId,
  Partial<Record<string, Record<HorizonKey, WFOParamSearchSpace<number>>>>
> = {
  sma: {
    window: {
      short: { scan_min: 5, scan_max: 20, scan_step: 1 },
      medium: { scan_min: 21, scan_max: 80, scan_step: 1 },
      long: { scan_min: 120, scan_max: 250, scan_step: 5 },
    },
  },
  rsi: {
    period: {
      short: { scan_min: 5, scan_max: 14, scan_step: 1 },
      medium: { scan_min: 14, scan_max: 28, scan_step: 1 },
      long: { scan_min: 21, scan_max: 50, scan_step: 1 },
    },
  },
  macd: {
    fast: {
      short: { scan_min: 5, scan_max: 10, scan_step: 1 },
      medium: { scan_min: 10, scan_max: 18, scan_step: 1 },
      long: { scan_min: 18, scan_max: 30, scan_step: 1 },
    },
    slow: {
      short: { scan_min: 12, scan_max: 20, scan_step: 1 },
      medium: { scan_min: 22, scan_max: 45, scan_step: 1 },
      long: { scan_min: 50, scan_max: 100, scan_step: 2 },
    },
    signal: {
      short: { scan_min: 5, scan_max: 9, scan_step: 1 },
      medium: { scan_min: 7, scan_max: 12, scan_step: 1 },
      long: { scan_min: 9, scan_max: 18, scan_step: 1 },
    },
  },
  obv: {
    ema_period: {
      short: { scan_min: 5, scan_max: 20, scan_step: 1 },
      medium: { scan_min: 21, scan_max: 80, scan_step: 1 },
      long: { scan_min: 120, scan_max: 250, scan_step: 5 },
    },
  },
}

const POSITIVE_CONTINUOUS_THRESHOLD_DEFAULTS: Record<HorizonKey, WFOParamSearchSpace<number>> = {
  short: { scan_min: 0.5, scan_max: 2.0, scan_step: 0.25 },
  medium: { scan_min: 0.5, scan_max: 3.0, scan_step: 0.5 },
  long: { scan_min: 1.0, scan_max: 4.0, scan_step: 0.5 },
}

const NEGATIVE_CONTINUOUS_THRESHOLD_DEFAULTS: Record<HorizonKey, WFOParamSearchSpace<number>> = {
  short: { scan_min: -2.0, scan_max: -0.5, scan_step: 0.25 },
  medium: { scan_min: -3.0, scan_max: -0.5, scan_step: 0.5 },
  long: { scan_min: -4.0, scan_max: -1.0, scan_step: 0.5 },
}

const LOW_OSCILLATION_THRESHOLD_DEFAULTS: Record<HorizonKey, WFOParamSearchSpace<number>> = {
  short: { scan_min: 10, scan_max: 35, scan_step: 5 },
  medium: { scan_min: 15, scan_max: 40, scan_step: 5 },
  long: { scan_min: 20, scan_max: 45, scan_step: 5 },
}

const HIGH_OSCILLATION_THRESHOLD_DEFAULTS: Record<HorizonKey, WFOParamSearchSpace<number>> = {
  short: { scan_min: 65, scan_max: 90, scan_step: 5 },
  medium: { scan_min: 60, scan_max: 85, scan_step: 5 },
  long: { scan_min: 55, scan_max: 80, scan_step: 5 },
}

const KELLY_MODIFIER_WFO_DEFAULTS: Record<HorizonKey, WFOParamSearchSpace<number>> = {
  short: { scan_min: 0.25, scan_max: 0.75, scan_step: 0.25 },
  medium: { scan_min: 0.25, scan_max: 1.0, scan_step: 0.25 },
  long: { scan_min: 0.25, scan_max: 1.0, scan_step: 0.25 },
}

const DIRECT_RULE_SIZING_WFO_DEFAULTS: Record<HorizonKey, WFOParamSearchSpace<number>> = {
  short: { scan_min: 25, scan_max: 100, scan_step: 25 },
  medium: { scan_min: 25, scan_max: 100, scan_step: 25 },
  long: { scan_min: 25, scan_max: 100, scan_step: 25 },
}

const ATR_MULTIPLIER_WFO_DEFAULTS: Record<HorizonKey, WFOParamSearchSpace<number>> = {
  short: { scan_min: 1.0, scan_max: 2.5, scan_step: 0.25 },
  medium: { scan_min: 1.5, scan_max: 3.0, scan_step: 0.25 },
  long: { scan_min: 2.0, scan_max: 4.0, scan_step: 0.5 },
}

const RR_RATIO_WFO_DEFAULTS: Record<HorizonKey, WFOParamSearchSpace<number>> = {
  short: { scan_min: 1.0, scan_max: 2.5, scan_step: 0.25 },
  medium: { scan_min: 1.5, scan_max: 3.5, scan_step: 0.25 },
  long: { scan_min: 2.0, scan_max: 5.0, scan_step: 0.5 },
}

const COOLDOWN_BARS_WFO_DEFAULTS: Record<HorizonKey, WFOParamSearchSpace<number>> = {
  short: { scan_min: 0, scan_max: 10, scan_step: 1 },
  medium: { scan_min: 0, scan_max: 15, scan_step: 1 },
  long: { scan_min: 0, scan_max: 20, scan_step: 2 },
}

const TIME_STOP_BARS_WFO_DEFAULTS: Record<HorizonKey, WFOParamSearchSpace<number>> = {
  short: { scan_min: 5, scan_max: 20, scan_step: 1 },
  medium: { scan_min: 20, scan_max: 60, scan_step: 5 },
  long: { scan_min: 40, scan_max: 120, scan_step: 10 },
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function toNumber(value: unknown, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item).trim()).filter(Boolean)
}

export function defaultHoldingBars(horizon: string): number {
  if (horizon === "short") return 10
  if (horizon === "long") return 60
  return 30
}

export function manualParam(value: number): WFOParam<number> {
  return { mode: "manual", value }
}

function defaultScanStep(value: number): number {
  return Number.isInteger(value) ? 1 : 0.1
}

function defaultSearchSpace(value: number, step: number): WFOParamSearchSpace<number> {
  return {
    scan_min: value,
    scan_max: value,
    scan_step: step,
  }
}

function widenSearchSpaceToIncludeValue(
  space: WFOParamSearchSpace<number>,
  value: number,
): WFOParamSearchSpace<number> {
  return {
    scan_min: Math.min(space.scan_min, value),
    scan_max: Math.max(space.scan_max, value),
    scan_step: space.scan_step,
  }
}

export function signalConstructionDefaultSearchSpaces(
  familyId: FamilyId,
  paramName: string,
  value: number,
): Partial<Record<HorizonKey, WFOParamSearchSpace<number>>> | undefined {
  const defaults = SIGNAL_CONSTRUCTION_WFO_DEFAULTS[familyId]?.[paramName]
  if (!defaults) return undefined
  return Object.fromEntries(
    HORIZON_KEYS.map((horizon) => [horizon, widenSearchSpaceToIncludeValue(defaults[horizon], value)]),
  ) as Partial<Record<HorizonKey, WFOParamSearchSpace<number>>>
}

function widenDefaults(
  defaults: Record<HorizonKey, WFOParamSearchSpace<number>>,
  value: number,
): Partial<Record<HorizonKey, WFOParamSearchSpace<number>>> {
  return Object.fromEntries(
    HORIZON_KEYS.map((horizon) => [horizon, widenSearchSpaceToIncludeValue(defaults[horizon], value)]),
  ) as Partial<Record<HorizonKey, WFOParamSearchSpace<number>>>
}

export function ruleThresholdDefaultSearchSpaces(
  variable: ScoreVariable,
  operator: RuleOperator,
  value: number,
): Partial<Record<HorizonKey, WFOParamSearchSpace<number>>> {
  const wantsLowerValues = operator === "<" || operator === "<="
  if (variable === "oscillation_score") {
    return widenDefaults(wantsLowerValues ? LOW_OSCILLATION_THRESHOLD_DEFAULTS : HIGH_OSCILLATION_THRESHOLD_DEFAULTS, value)
  }
  return widenDefaults(wantsLowerValues ? NEGATIVE_CONTINUOUS_THRESHOLD_DEFAULTS : POSITIVE_CONTINUOUS_THRESHOLD_DEFAULTS, value)
}

export function kellyModifierDefaultSearchSpaces(value: number): Partial<Record<HorizonKey, WFOParamSearchSpace<number>>> {
  return widenDefaults(KELLY_MODIFIER_WFO_DEFAULTS, value)
}

export function directRuleSizingDefaultSearchSpaces(value: number): Partial<Record<HorizonKey, WFOParamSearchSpace<number>>> {
  return widenDefaults(DIRECT_RULE_SIZING_WFO_DEFAULTS, value)
}

export function atrMultiplierDefaultSearchSpaces(value: number): Partial<Record<HorizonKey, WFOParamSearchSpace<number>>> {
  return widenDefaults(ATR_MULTIPLIER_WFO_DEFAULTS, value)
}

export function rrRatioDefaultSearchSpaces(value: number): Partial<Record<HorizonKey, WFOParamSearchSpace<number>>> {
  return widenDefaults(RR_RATIO_WFO_DEFAULTS, value)
}

export function cooldownBarsDefaultSearchSpaces(value: number): Partial<Record<HorizonKey, WFOParamSearchSpace<number>>> {
  return widenDefaults(COOLDOWN_BARS_WFO_DEFAULTS, value)
}

export function timeStopBarsDefaultSearchSpaces(value: number): Partial<Record<HorizonKey, WFOParamSearchSpace<number>>> {
  return widenDefaults(TIME_STOP_BARS_WFO_DEFAULTS, value)
}

export function ensureWfoSearchSpaces(
  param: WFOParam<number>,
  fallbackStep?: number,
  defaultSpaces?: Partial<Record<HorizonKey, WFOParamSearchSpace<number>>>,
): Partial<Record<HorizonKey, WFOParamSearchSpace<number>>> {
  const step = fallbackStep ?? defaultScanStep(param.value)
  const base = defaultSearchSpace(param.value, param.scan_step ?? step)
  const rawSpaces = param.search_spaces_by_horizon ?? {}
  const out: Partial<Record<HorizonKey, WFOParamSearchSpace<number>>> = {}
  for (const horizon of HORIZON_KEYS) {
    const seeded = defaultSpaces?.[horizon]
      ? widenSearchSpaceToIncludeValue(defaultSpaces[horizon] as WFOParamSearchSpace<number>, param.value)
      : {
          scan_min: param.scan_min ?? base.scan_min,
          scan_max: param.scan_max ?? base.scan_max,
          scan_step: param.scan_step ?? base.scan_step,
        }
    const raw = rawSpaces[horizon]
    out[horizon] = {
      scan_min: toNumber(raw?.scan_min, seeded.scan_min),
      scan_max: toNumber(raw?.scan_max, seeded.scan_max),
      scan_step: toNumber(raw?.scan_step, seeded.scan_step),
    }
  }
  return out
}

export function resolveWfoSearchSpace(
  param: WFOParam<number>,
  horizon: HorizonKey,
  fallbackStep?: number,
  defaultSpaces?: Partial<Record<HorizonKey, WFOParamSearchSpace<number>>>,
): WFOParamSearchSpace<number> {
  const spaces = ensureWfoSearchSpaces(param, fallbackStep, defaultSpaces)
  return spaces[horizon] ?? defaultSearchSpace(param.value, fallbackStep ?? defaultScanStep(param.value))
}

export function normalizeWfoParam(
  raw: unknown,
  fallbackValue: number,
  horizon: HorizonKey,
  defaultSpaces?: Partial<Record<HorizonKey, WFOParamSearchSpace<number>>>,
): WFOParam<number> {
  if (!isRecord(raw)) return manualParam(fallbackValue)
  const mode = String(raw.mode ?? "manual").toLowerCase() === "wfo" ? "wfo" : "manual"
  const value = toNumber(raw.value, fallbackValue)
  const baseStep = toNumber(raw.scan_step, defaultScanStep(value))
  const hasLegacyTopLevelRange = raw.scan_min != null || raw.scan_max != null || raw.scan_step != null
  const rawSearchSpaces = isRecord(raw.search_spaces_by_horizon)
    ? raw.search_spaces_by_horizon as Record<string, unknown>
    : null
  const param: WFOParam<number> = {
    mode,
    value,
    scan_min: toNumber(raw.scan_min, value),
    scan_max: toNumber(raw.scan_max, value),
    scan_step: baseStep,
    search_spaces_by_horizon: rawSearchSpaces
      ? Object.fromEntries(
          HORIZON_KEYS.map((key) => {
            const candidate = rawSearchSpaces[key]
            const item = isRecord(candidate) ? candidate as Record<string, unknown> : {}
            return [
              key,
              {
                scan_min: toNumber(item.scan_min, toNumber(raw.scan_min, value)),
                scan_max: toNumber(item.scan_max, toNumber(raw.scan_max, value)),
                scan_step: toNumber(item.scan_step, baseStep),
              },
            ]
          }),
        ) as Partial<Record<HorizonKey, WFOParamSearchSpace<number>>>
      : undefined,
  }
  const effectiveDefaultSpaces = rawSearchSpaces || hasLegacyTopLevelRange ? undefined : defaultSpaces
  const spaces = ensureWfoSearchSpaces(param, baseStep, effectiveDefaultSpaces)
  if (mode !== "wfo") {
    return {
      mode: "manual",
      value,
      search_spaces_by_horizon: spaces,
      scan_min: param.scan_min,
      scan_max: param.scan_max,
      scan_step: param.scan_step,
    }
  }
  const active = spaces[horizon] ?? defaultSearchSpace(value, baseStep)
  return {
    ...param,
    mode: "wfo",
    scan_min: active.scan_min,
    scan_max: active.scan_max,
    scan_step: active.scan_step,
    search_spaces_by_horizon: spaces,
  }
}

export function defaultRuleCondition(index = 0): RuleConditionV2 {
  return {
    id: `condition_${index + 1}`,
    variable: "consensus_score",
    operator: ">=",
    threshold: manualParam(0),
  }
}

export function defaultEntryRule(index = 0): EntryRuleV2 {
  return {
    id: `entry_${index + 1}`,
    label: `Entry ${index + 1}`,
    config_option: "A",
    conditions: [defaultRuleCondition(0)],
    sizing: {
      mode: "manual",
      manual_pct: 25,
      size_pct: null,
      kelly_modifier: null,
    },
  }
}

export function defaultExitRule(index = 0): ExitRuleV2 {
  return {
    id: `exit_${index + 1}`,
    label: `Exit ${index + 1}`,
    config_option: "A",
    conditions: [defaultRuleCondition(0)],
    sizing: {
      mode: "manual",
      manual_pct: 100,
      reduction_pct: null,
      kelly_modifier: null,
    },
  }
}

export function defaultIndicatorRowConfig(
  familyId: FamilyId,
  index = 0,
  scoreKey?: string,
): IndicatorRowConfigV2 {
  const computedScoreKey = scoreKey ?? (index === 0 ? FAMILY_SCORE_KEYS[familyId] : `${FAMILY_SCORE_KEYS[familyId]}_${index + 1}`)
  const computedLabel = index === 0 ? FAMILY_SCORE_LABELS[familyId] : `${FAMILY_SCORE_LABELS[familyId]} ${index + 1}`
  const params: Record<string, WFOParam<number>> =
    familyId === "sma"
      ? { window: manualParam(21) }
      : familyId === "rsi"
        ? { period: manualParam(21) }
        : familyId === "macd"
          ? { fast: manualParam(12), slow: manualParam(26), signal: manualParam(9) }
          : { ema_period: manualParam(21) }
  return {
    id: `${familyId}_row_${index + 1}`,
    enabled: true,
    score_key: computedScoreKey,
    label: computedLabel,
    params,
  }
}

export function nextScoreKey(
  familyId: FamilyId,
  existingKeys: string[],
): string {
  const base = FAMILY_SCORE_KEYS[familyId]
  const used = new Set(existingKeys)
  if (!used.has(base)) return base
  let suffix = 2
  while (used.has(`${base}_${suffix}`)) suffix += 1
  return `${base}_${suffix}`
}

export function defaultFamilyConfigs(): Record<FamilyId, FamilyConfigV2> {
  return {
    sma: { enabled: true, source_mode: "indicator_rows", rows: [defaultIndicatorRowConfig("sma", 0, FAMILY_SCORE_KEYS.sma)] },
    rsi: { enabled: true, source_mode: "indicator_rows", rows: [defaultIndicatorRowConfig("rsi", 0, FAMILY_SCORE_KEYS.rsi)] },
    macd: { enabled: true, source_mode: "indicator_rows", rows: [defaultIndicatorRowConfig("macd", 0, FAMILY_SCORE_KEYS.macd)] },
    obv: { enabled: true, source_mode: "indicator_rows", rows: [defaultIndicatorRowConfig("obv", 0, FAMILY_SCORE_KEYS.obv)] },
  }
}

export function defaultStockStrategyConfig(horizon: string): StockStrategyConfigV2 {
  return {
    strategy_type: "trend_following",
    signal_construction: { families: defaultFamilyConfigs() },
    entry_rules: [],
    exit_rules: [],
    risk: {
      stop_loss: { mode: "atr_based", manual_pct: 0.02, atr_multiplier: manualParam(1.5) },
      take_profit: { mode: "rr_target", manual_pct: 0.03, rr_ratio: manualParam(1.5) },
      cooldown_bars: manualParam(0),
      time_stop: { enabled: true, bars: manualParam(defaultHoldingBars(horizon)) },
      trailing_stop_enabled: false,
      max_position_pct: 20,
      max_sector_pct: 40,
    },
  }
}

export function defaultStrategyConfigV2(horizon: string): StrategyConfigV2 {
  return {
    schema_version: 3,
    app_domain: "four_pages",
    legacy_snapshot: null,
    portfolio: {
      total_capital_mad: 1_000_000,
      universe: {
        basket: [],
        sector_filter: [],
        min_abs_signal: 0,
        min_adv20: 0,
        sort_by: "adv20",
        sort_dir: "desc",
      },
      allocation: {
        method: "hrp",
        hrp_lookback_bars: 252,
        manual_overrides_by_symbol: {},
      },
    },
    stocks: {},
    snapshot: null,
  }
}

function normalizeStockStrategyConfig(
  raw: StrategyConfigV2["stocks"][string] | Record<string, unknown> | undefined,
  horizon: HorizonKey,
): StockStrategyConfigV2 {
  const base = defaultStockStrategyConfig(horizon)
  const record = isRecord(raw) ? raw : {}
  const signalConstruction = isRecord(record.signal_construction) ? record.signal_construction : {}
  const familiesRaw = isRecord(signalConstruction.families) ? signalConstruction.families : {}
  const entryRulesRaw = Array.isArray(record.entry_rules) ? record.entry_rules : []
  const exitRulesRaw = Array.isArray(record.exit_rules) ? record.exit_rules : []
  const riskRaw = isRecord(record.risk) ? record.risk : {}
  const stopLossRaw = isRecord(riskRaw.stop_loss) ? riskRaw.stop_loss : {}
  const takeProfitRaw = isRecord(riskRaw.take_profit) ? riskRaw.take_profit : {}
  const timeStopRaw = isRecord(riskRaw.time_stop) ? riskRaw.time_stop : {}

  return {
    strategy_type: record.strategy_type === "mean_reversion" ? "mean_reversion" : base.strategy_type,
    signal_construction: {
      families: Object.fromEntries(
        (Object.keys(base.signal_construction.families) as FamilyId[]).map((familyId) => {
          const familyRaw = isRecord(familiesRaw[familyId]) ? familiesRaw[familyId] : {}
          const baseFamily = base.signal_construction.families[familyId]
          const rowsRaw = Array.isArray(familyRaw.rows) ? familyRaw.rows : []
          const usedKeys = new Set<string>()
          const normalizedRows = rowsRaw.map((rawRow, index) => {
            const row = isRecord(rawRow) ? rawRow : {}
            const baseRow = defaultIndicatorRowConfig(familyId, index)
            const paramsRaw = isRecord(row.params) ? row.params : {}
            const rawScoreKey = typeof row.score_key === "string" ? row.score_key.trim().toLowerCase() : ""
            let scoreKey = rawScoreKey || nextScoreKey(familyId, Array.from(usedKeys))
            if (usedKeys.has(scoreKey)) scoreKey = nextScoreKey(familyId, Array.from(usedKeys))
            usedKeys.add(scoreKey)
            return {
              id: typeof row.id === "string" ? row.id : baseRow.id,
              enabled: row.enabled == null ? true : Boolean(row.enabled),
              score_key: scoreKey,
              label: typeof row.label === "string" && row.label.trim().length > 0 ? row.label : (scoreKey === FAMILY_SCORE_KEYS[familyId] ? FAMILY_SCORE_LABELS[familyId] : `${FAMILY_SCORE_LABELS[familyId]} ${index + 1}`),
              params: Object.fromEntries(
                Object.entries(baseRow.params).map(([paramName, defaultParam]) => [
                  paramName,
                  normalizeWfoParam(
                    paramsRaw[paramName],
                    defaultParam.value,
                    horizon,
                    signalConstructionDefaultSearchSpaces(familyId, paramName, defaultParam.value),
                  ),
                ]),
              ),
            }
          })

          const legacyParamsRaw = isRecord(familyRaw.params) ? familyRaw.params : {}
          const migratedLegacyRows = normalizedRows.length > 0
            ? normalizedRows
            : (isRecord(familyRaw) && (familyRaw.indicator_type != null || Object.keys(legacyParamsRaw).length > 0 || familyRaw.enabled != null))
              ? [
                  {
                    ...defaultIndicatorRowConfig(familyId, 0, FAMILY_SCORE_KEYS[familyId]),
                    params: Object.fromEntries(
                      Object.entries(defaultIndicatorRowConfig(familyId, 0, FAMILY_SCORE_KEYS[familyId]).params).map(([paramName, defaultParam]) => [
                        paramName,
                        normalizeWfoParam(
                          legacyParamsRaw[paramName],
                          defaultParam.value,
                          horizon,
                          signalConstructionDefaultSearchSpaces(familyId, paramName, defaultParam.value),
                        ),
                      ]),
                    ),
                  },
                ]
              : baseFamily.rows.map((row) => structuredClone(row))

          return [
            familyId,
            {
              enabled: familyRaw.enabled == null ? baseFamily.enabled : Boolean(familyRaw.enabled),
              source_mode: familyRaw.source_mode === "family_ensemble" ? "family_ensemble" : "indicator_rows",
              rows: migratedLegacyRows,
            },
          ]
        }),
      ) as Record<FamilyId, FamilyConfigV2>,
    },
    entry_rules: entryRulesRaw.map((rawRule, index) => {
      const rule = isRecord(rawRule) ? rawRule : {}
      const sizingRaw = isRecord(rule.sizing) ? rule.sizing : {}
      const conditionsRaw = Array.isArray(rule.conditions) ? rule.conditions : []
      return {
        id: typeof rule.id === "string" ? rule.id : `entry_${index + 1}`,
        label: typeof rule.label === "string" ? rule.label : `Entry ${index + 1}`,
        config_option: ["A", "B", "C", "D", "E"].includes(String(rule.config_option)) ? rule.config_option as ConfigOption : "A",
        conditions: conditionsRaw.map((rawCondition, conditionIndex) => {
          const condition = isRecord(rawCondition) ? rawCondition : {}
          return {
            id: typeof condition.id === "string" ? condition.id : `condition_${conditionIndex + 1}`,
            variable: typeof condition.variable === "string" && condition.variable.trim().length > 0 ? condition.variable as ScoreVariable : "consensus_score",
            operator: [">", ">=", "<", "<="].includes(String(condition.operator)) ? condition.operator as RuleOperator : ">=",
            threshold: normalizeWfoParam(condition.threshold, 0, horizon),
          }
        }),
        sizing: {
          mode: ["manual", "kelly_wfo", "wfo"].includes(String(sizingRaw.mode)) ? sizingRaw.mode as EntryRuleV2["sizing"]["mode"] : "manual",
          manual_pct: toNumber(sizingRaw.manual_pct, toNumber(sizingRaw.value, 25)),
          size_pct:
            String(sizingRaw.mode) === "wfo"
              ? normalizeWfoParam(
                  isRecord(sizingRaw.size_pct)
                    ? sizingRaw.size_pct
                    : isRecord(sizingRaw.kelly_modifier) && String(sizingRaw.kelly_modifier.mode ?? "").toLowerCase() === "wfo"
                      ? sizingRaw.kelly_modifier
                      : { mode: "wfo", value: toNumber(sizingRaw.manual_pct, toNumber(sizingRaw.value, 25)) },
                  toNumber(sizingRaw.manual_pct, toNumber(sizingRaw.value, 25)),
                  horizon,
                  directRuleSizingDefaultSearchSpaces(toNumber(sizingRaw.manual_pct, toNumber(sizingRaw.value, 25))),
                )
              : null,
          kelly_modifier:
            String(sizingRaw.mode) === "kelly_wfo"
              ? normalizeWfoParam(sizingRaw.kelly_modifier, 0.5, horizon, kellyModifierDefaultSearchSpaces(0.5))
              : null,
        },
      }
    }),
    exit_rules: exitRulesRaw.map((rawRule, index) => {
      const rule = isRecord(rawRule) ? rawRule : {}
      const sizingRaw = isRecord(rule.sizing) ? rule.sizing : {}
      const conditionsRaw = Array.isArray(rule.conditions) ? rule.conditions : []
      return {
        id: typeof rule.id === "string" ? rule.id : `exit_${index + 1}`,
        label: typeof rule.label === "string" ? rule.label : `Exit ${index + 1}`,
        config_option: ["A", "B", "C", "D", "E"].includes(String(rule.config_option)) ? rule.config_option as ConfigOption : "A",
        conditions: conditionsRaw.map((rawCondition, conditionIndex) => {
          const condition = isRecord(rawCondition) ? rawCondition : {}
          return {
            id: typeof condition.id === "string" ? condition.id : `condition_${conditionIndex + 1}`,
            variable: typeof condition.variable === "string" && condition.variable.trim().length > 0 ? condition.variable as ScoreVariable : "consensus_score",
            operator: [">", ">=", "<", "<="].includes(String(condition.operator)) ? condition.operator as RuleOperator : ">=",
            threshold: normalizeWfoParam(condition.threshold, 0, horizon),
          }
        }),
        sizing: {
          mode: ["manual", "kelly_wfo", "wfo"].includes(String(sizingRaw.mode)) ? sizingRaw.mode as ExitRuleV2["sizing"]["mode"] : "manual",
          manual_pct: toNumber(sizingRaw.manual_pct, toNumber(sizingRaw.value, 100)),
          reduction_pct:
            String(sizingRaw.mode) === "wfo"
              ? normalizeWfoParam(
                  isRecord(sizingRaw.reduction_pct)
                    ? sizingRaw.reduction_pct
                    : { mode: "wfo", value: toNumber(sizingRaw.manual_pct, toNumber(sizingRaw.value, 100)) },
                  toNumber(sizingRaw.manual_pct, toNumber(sizingRaw.value, 100)),
                  horizon,
                  directRuleSizingDefaultSearchSpaces(toNumber(sizingRaw.manual_pct, toNumber(sizingRaw.value, 100))),
                )
              : null,
          kelly_modifier:
            String(sizingRaw.mode) === "kelly_wfo"
              ? normalizeWfoParam(sizingRaw.kelly_modifier, 0.5, horizon, kellyModifierDefaultSearchSpaces(0.5))
              : null,
        },
      }
    }),
    risk: {
      stop_loss: {
        mode: ["manual_pct", "atr_based", "wfo"].includes(String(stopLossRaw.mode)) ? stopLossRaw.mode as RiskConfigV2["stop_loss"]["mode"] : "atr_based",
        manual_pct: toNumber(stopLossRaw.manual_pct, 0.02),
        atr_multiplier: normalizeWfoParam(stopLossRaw.atr_multiplier, 1.5, horizon),
      },
      take_profit: {
        mode: ["manual_pct", "rr_target", "wfo"].includes(String(takeProfitRaw.mode)) ? takeProfitRaw.mode as RiskConfigV2["take_profit"]["mode"] : "rr_target",
        manual_pct: toNumber(takeProfitRaw.manual_pct, 0.03),
        rr_ratio: normalizeWfoParam(takeProfitRaw.rr_ratio, 1.5, horizon),
      },
      cooldown_bars: normalizeWfoParam(riskRaw.cooldown_bars, 0, horizon),
      time_stop: {
        enabled: timeStopRaw.enabled == null ? true : Boolean(timeStopRaw.enabled),
        bars: normalizeWfoParam(timeStopRaw.bars, defaultHoldingBars(horizon), horizon),
      },
      trailing_stop_enabled: Boolean(riskRaw.trailing_stop_enabled),
      max_position_pct: toNumber(riskRaw.max_position_pct, 20),
      max_sector_pct: toNumber(riskRaw.max_sector_pct, 40),
    },
  }
}

export function migrateStrategyConfigV2(raw: unknown, horizon: string): StrategyConfigV2 {
  if (isRecord(raw) && (raw.schema_version === 2 || raw.schema_version === 3) && raw.app_domain === "four_pages") {
    const next = defaultStrategyConfigV2(horizon)
    const portfolio = isRecord(raw.portfolio) ? raw.portfolio : {}
    const universe = isRecord(portfolio.universe) ? portfolio.universe : {}
    const allocation = isRecord(portfolio.allocation) ? portfolio.allocation : {}
    const basket = toStringArray(universe.basket).map((symbol) => symbol.toUpperCase())
    next.legacy_snapshot = isRecord(raw.legacy_snapshot) ? raw.legacy_snapshot : null
    next.snapshot = isRecord(raw.snapshot) ? raw.snapshot : null
    next.portfolio = {
      total_capital_mad: toNumber(portfolio.total_capital_mad, next.portfolio.total_capital_mad),
      universe: {
        basket,
        sector_filter: toStringArray(universe.sector_filter),
        min_abs_signal: toNumber(universe.min_abs_signal, 0),
        min_adv20: toNumber(universe.min_adv20, 0),
        sort_by: universe.sort_by === "signal_score" ? "signal_score" : "adv20",
        sort_dir: universe.sort_dir === "asc" ? "asc" : "desc",
      },
      allocation: {
        method: "hrp",
        hrp_lookback_bars: toNumber(allocation.hrp_lookback_bars, 252),
        manual_overrides_by_symbol: isRecord(allocation.manual_overrides_by_symbol)
          ? Object.fromEntries(
              Object.entries(allocation.manual_overrides_by_symbol).map(([symbol, value]) => [
                symbol.toUpperCase(),
                {
                  enabled: Boolean((value as Record<string, unknown>)?.enabled),
                  capital_mad: toNumber((value as Record<string, unknown>)?.capital_mad, 0),
                },
              ]),
            )
          : {},
      },
    }
    const stocksRaw = isRecord(raw.stocks) ? raw.stocks : {}
    for (const symbol of basket) {
      next.stocks[symbol] = normalizeStockStrategyConfig(
        isRecord(stocksRaw[symbol]) ? stocksRaw[symbol] : undefined,
        horizon as HorizonKey,
      )
    }
    return next
  }

  const next = defaultStrategyConfigV2(horizon)
  const rawRecord = isRecord(raw) ? raw : {}
  const capital = isRecord(rawRecord.capital) ? rawRecord.capital : {}
  const universe = isRecord(rawRecord.universe) ? rawRecord.universe : {}
  const allocation = isRecord(rawRecord.allocation) ? rawRecord.allocation : {}
  const signal = isRecord(rawRecord.signal) ? rawRecord.signal : {}
  const logic = isRecord(rawRecord.logic) ? rawRecord.logic : {}
  const risk = isRecord(rawRecord.risk) ? rawRecord.risk : {}

  next.legacy_snapshot = isRecord(raw) ? rawRecord : null
  next.portfolio.total_capital_mad = toNumber(capital.total_capital_mad, next.portfolio.total_capital_mad)
  next.portfolio.universe = {
    basket: toStringArray(universe.basket).map((symbol) => symbol.toUpperCase()),
    sector_filter: toStringArray(universe.sector_filter),
    min_abs_signal: toNumber(universe.min_abs_signal, 0),
    min_adv20: toNumber(universe.min_adv20, 0),
    sort_by: universe.sort_by === "signal_score" ? "signal_score" : "adv20",
    sort_dir: universe.sort_dir === "asc" ? "asc" : "desc",
  }
  next.portfolio.allocation = {
    method: "hrp",
    hrp_lookback_bars: toNumber(allocation.hrp_lookback_bars, 252),
    manual_overrides_by_symbol: isRecord(allocation.manual_overrides_by_symbol)
      ? Object.fromEntries(
          Object.entries(allocation.manual_overrides_by_symbol).map(([symbol, value]) => [
            symbol.toUpperCase(),
            {
              enabled: isRecord(value) ? Boolean(value.enabled) : toNumber(value, 0) > 0,
              capital_mad: isRecord(value) ? toNumber(value.capital_mad, 0) : toNumber(value, 0),
            },
          ]),
        )
      : {},
  }

  const enabledFamilies = new Set(
    [...toStringArray(signal.enabled_families), ...toStringArray(logic.enabled_families)]
      .map((value) => value.toLowerCase())
      .filter((value): value is FamilyId => ["sma", "rsi", "macd", "obv"].includes(value)),
  )
  if (enabledFamilies.size === 0) {
    for (const family of ["sma", "rsi", "macd", "obv"] as FamilyId[]) enabledFamilies.add(family)
  }

  for (const symbol of next.portfolio.universe.basket) {
    const stock = defaultStockStrategyConfig(horizon)
    for (const family of Object.keys(stock.signal_construction.families) as FamilyId[]) {
      stock.signal_construction.families[family].enabled = enabledFamilies.has(family)
    }
    stock.risk = {
      stop_loss: {
        mode: "atr_based",
        manual_pct: 0.02,
        atr_multiplier: manualParam(toNumber(risk.stop_atr_multiplier, 1.5)),
      },
      take_profit: {
        mode: "rr_target",
        manual_pct: 0.03,
        rr_ratio: manualParam(toNumber(risk.take_profit_rr, 1.5)),
      },
      cooldown_bars: manualParam(0),
      time_stop: {
        enabled: risk.time_stop_enabled == null ? true : Boolean(risk.time_stop_enabled),
        bars: manualParam(toNumber(risk.max_holding_bars, defaultHoldingBars(horizon))),
      },
      trailing_stop_enabled: Boolean(risk.trailing_stop_enabled),
      max_position_pct: 20,
      max_sector_pct: 40,
    }
    next.stocks[symbol] = stock
  }
  return next
}

export function cloneStockStrategyConfig(
  stock: StrategyConfigV2["stocks"][string] | undefined,
  horizon: string,
): StockStrategyConfigV2 {
  return normalizeStockStrategyConfig(structuredClone(stock ?? defaultStockStrategyConfig(horizon)), horizon as HorizonKey)
}

export function ensureBasketStocks(config: StrategyConfigV2, horizon: string): StrategyConfigV2 {
  const next = structuredClone(config)
  const basket = new Set(next.portfolio.universe.basket.map((symbol) => symbol.toUpperCase()))
  const stocks: StrategyConfigV2["stocks"] = {}
  for (const symbol of next.portfolio.universe.basket) {
    stocks[symbol] = cloneStockStrategyConfig(next.stocks[symbol], horizon)
  }
  for (const [symbol, stock] of Object.entries(next.stocks)) {
    if (basket.has(symbol)) {
      stocks[symbol] = stocks[symbol] ?? cloneStockStrategyConfig(stock, horizon)
    }
  }
  next.stocks = stocks
  return next
}

export function scoreVariableOptions(
  stock: StockStrategyConfigV2,
  extraVariables: string[] = [],
): Array<{ value: string; label: string; missing?: boolean }> {
  const options: Array<{ value: string; label: string; missing?: boolean }> = []
  const seen = new Set<string>()
  for (const familyId of Object.keys(stock.signal_construction.families) as FamilyId[]) {
    const family = stock.signal_construction.families[familyId]
    if (!family.enabled) continue
    if (family.source_mode === "family_ensemble") {
      const value = FAMILY_SCORE_KEYS[familyId]
      options.push({ value, label: `${FAMILY_SCORE_LABELS[familyId]} · Family` })
      seen.add(value)
      continue
    }
    for (const row of family.rows) {
      if (!row.enabled) continue
      options.push({ value: row.score_key, label: row.label })
      seen.add(row.score_key)
    }
  }
  if (!seen.has("consensus_score")) {
    options.push({ value: "consensus_score", label: "Consensus Score" })
    seen.add("consensus_score")
  }
  for (const value of extraVariables) {
    const normalized = value.trim()
    if (!normalized || seen.has(normalized)) continue
    options.push({ value: normalized, label: `${normalized} (Missing)`, missing: true })
    seen.add(normalized)
  }
  return options
}

export function summarizeCondition(condition: RuleConditionV2, horizon?: HorizonKey): string {
  const rawValue = condition.threshold.mode === "wfo"
    ? (() => {
        if (horizon) {
          const active = resolveWfoSearchSpace(condition.threshold, horizon, 0.1)
          return `WFO ${active.scan_min}-${active.scan_max}`
        }
        return `WFO ${condition.threshold.scan_min ?? condition.threshold.value}-${condition.threshold.scan_max ?? condition.threshold.value}`
      })()
    : `${condition.threshold.value}`
  return `${condition.variable} ${condition.operator} ${rawValue}`
}
