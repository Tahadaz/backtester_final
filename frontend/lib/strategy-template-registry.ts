"use client"

import {
  cloneStockStrategyConfig,
  defaultIndicatorRowConfig,
  defaultStockStrategyConfig,
  manualParam,
  type EntryRuleV2,
  type ExitRuleV2,
  type FamilyId,
  type HorizonKey,
  type RuleExpressionV4,
  type StockStrategyConfigV2,
} from "@/lib/strategy-v2"

export type StrategyTemplateCategory = "trend" | "mean_reversion" | "breakout" | "volume"

export type StrategyTemplate = {
  id: string
  name: string
  author: string
  category: StrategyTemplateCategory
  summary: string
  tags: string[]
  isExecutable: boolean
  materialize: (horizon: HorizonKey, previous?: StockStrategyConfigV2 | null) => StockStrategyConfigV2
}

const price = (field: "Open" | "High" | "Low" | "Close") => ({ kind: "price", field })
const constant = (value: number) => ({ kind: "constant", value })
const rolling = (
  fn: "highest" | "lowest" | "mean",
  field: "High" | "Low" | "Close" | "Volume",
  lookback: number,
  offset = 1,
) => ({ kind: "rolling", function: fn, field, lookback, offset })
const indicator = (name: string, window: number, extras: Record<string, unknown> = {}) => ({
  kind: "indicator",
  name,
  window,
  ...extras,
})
const darvasBox = (side: "top" | "bottom", lookback: number) => ({
  kind: "darvas_box",
  side,
  lookback,
  offset: 1,
})

function ruleExpression(children: RuleExpressionV4[]): RuleExpressionV4 {
  return { operator: "all", children }
}

function entryRule(id: string, label: string, expression: RuleExpressionV4, manualPct = 25): EntryRuleV2 {
  return {
    id,
    label,
    config_option: "A",
    conditions: [],
    rule_expression: expression,
    sizing: {
      mode: "manual",
      manual_pct: manualPct,
      size_pct: null,
      kelly_modifier: null,
    },
  }
}

function exitRule(id: string, label: string, expression: RuleExpressionV4, reductionPct = 100): ExitRuleV2 {
  return {
    id,
    label,
    config_option: "A",
    conditions: [],
    rule_expression: expression,
    sizing: {
      mode: "manual",
      manual_pct: reductionPct,
      reduction_pct: null,
      kelly_modifier: null,
    },
  }
}

function baseTemplateStock(
  horizon: HorizonKey,
  previous: StockStrategyConfigV2 | null | undefined,
  strategyType: StockStrategyConfigV2["strategy_type"],
): StockStrategyConfigV2 {
  const stock = defaultStockStrategyConfig(horizon)
  const previousStock = previous ? cloneStockStrategyConfig(previous, horizon) : null
  stock.strategy_type = strategyType
  stock.signal_construction.source_mode = "manual"
  stock.signal_construction.selected_signal_candidate = null
  for (const familyId of Object.keys(stock.signal_construction.families) as FamilyId[]) {
    stock.signal_construction.families[familyId] = {
      enabled: false,
      source_mode: "indicator_rows",
      rows: [defaultIndicatorRowConfig(familyId, 0)],
    }
  }
  stock.entry_rules = []
  stock.exit_rules = []
  stock.risk.max_position_pct = previousStock?.risk.max_position_pct ?? stock.risk.max_position_pct
  stock.risk.max_sector_pct = previousStock?.risk.max_sector_pct ?? stock.risk.max_sector_pct
  return stock
}

function setFamilyRows(
  stock: StockStrategyConfigV2,
  familyId: FamilyId,
  rows: Array<{
    label: string
    scoreKey?: string
    params: Record<string, number>
  }>,
) {
  stock.signal_construction.families[familyId] = {
    enabled: true,
    source_mode: "indicator_rows",
    rows: rows.map((row, index) => {
      const next = defaultIndicatorRowConfig(familyId, index, row.scoreKey)
      next.label = row.label
      next.params = {
        ...next.params,
        ...Object.fromEntries(Object.entries(row.params).map(([key, value]) => [key, manualParam(value)])),
      }
      return next
    }),
  }
}

function turtleDonchian(horizon: HorizonKey, previous?: StockStrategyConfigV2 | null) {
  const stock = baseTemplateStock(horizon, previous, "trend_following")
  setFamilyRows(stock, "sma", [{ label: "Trend filter SMA 50", scoreKey: "turtle_sma_50", params: { window: 50 } }])
  stock.entry_rules = [
    entryRule(
      "entry_turtle_20_breakout",
      "20-bar Donchian breakout",
      ruleExpression([
        {
          type: "breakout",
          direction: "above",
          source: price("Close"),
          level: rolling("highest", "High", 20, 1),
        },
      ]),
      25,
    ),
  ]
  stock.exit_rules = [
    exitRule(
      "exit_turtle_10_breakdown",
      "10-bar Donchian breakdown",
      ruleExpression([
        {
          type: "breakdown",
          direction: "below",
          source: price("Close"),
          level: rolling("lowest", "Low", 10, 1),
        },
      ]),
    ),
  ]
  return stock
}

function movingAverageCross(horizon: HorizonKey, previous?: StockStrategyConfigV2 | null) {
  const stock = baseTemplateStock(horizon, previous, "trend_following")
  setFamilyRows(stock, "sma", [
    { label: "Fast SMA 20", scoreKey: "sma_fast_20", params: { window: 20 } },
    { label: "Slow SMA 50", scoreKey: "sma_slow_50", params: { window: 50 } },
  ])
  stock.entry_rules = [
    entryRule(
      "entry_sma_20_50_cross",
      "SMA 20 crosses above SMA 50",
      ruleExpression([
        {
          type: "cross",
          direction: "above",
          left: indicator("sma", 20),
          right: indicator("sma", 50),
        },
      ]),
      30,
    ),
  ]
  stock.exit_rules = [
    exitRule(
      "exit_sma_20_50_cross",
      "SMA 20 crosses below SMA 50",
      ruleExpression([
        {
          type: "cross",
          direction: "below",
          left: indicator("sma", 20),
          right: indicator("sma", 50),
        },
      ]),
    ),
  ]
  return stock
}

function rsiMeanReversion(horizon: HorizonKey, previous?: StockStrategyConfigV2 | null) {
  const stock = baseTemplateStock(horizon, previous, "mean_reversion")
  setFamilyRows(stock, "rsi", [{ label: "RSI 14", scoreKey: "rsi_14_score", params: { period: 14, oversold: 30, overbought: 70 } }])
  stock.entry_rules = [
    entryRule(
      "entry_rsi_oversold",
      "RSI oversold entry",
      ruleExpression([
        {
          type: "threshold",
          left: indicator("rsi", 14),
          operator: "<=",
          right: constant(30),
        },
      ]),
      25,
    ),
  ]
  stock.exit_rules = [
    exitRule(
      "exit_rsi_mean",
      "RSI mean exit",
      ruleExpression([
        {
          type: "threshold",
          left: indicator("rsi", 14),
          operator: ">=",
          right: constant(50),
        },
      ]),
    ),
  ]
  return stock
}

function bollingerMeanReversion(horizon: HorizonKey, previous?: StockStrategyConfigV2 | null) {
  const stock = baseTemplateStock(horizon, previous, "mean_reversion")
  setFamilyRows(stock, "sma", [{ label: "Bollinger midline SMA 20", scoreKey: "bb_mid_sma_20", params: { window: 20 } }])
  stock.entry_rules = [
    entryRule(
      "entry_bollinger_lower",
      "Close below lower band",
      ruleExpression([
        {
          type: "breakdown",
          direction: "below",
          source: price("Close"),
          level: indicator("bollinger_lower", 20, { multiplier: 2 }),
        },
      ]),
      25,
    ),
  ]
  stock.exit_rules = [
    exitRule(
      "exit_bollinger_mid",
      "Close back to midline",
      ruleExpression([
        {
          type: "threshold",
          left: price("Close"),
          operator: ">=",
          right: indicator("bollinger_mid", 20),
        },
      ]),
    ),
  ]
  return stock
}

function darvasBoxBreakout(horizon: HorizonKey, previous?: StockStrategyConfigV2 | null) {
  const stock = baseTemplateStock(horizon, previous, "trend_following")
  setFamilyRows(stock, "sma", [{ label: "Darvas context SMA 50", scoreKey: "darvas_sma_50", params: { window: 50 } }])
  setFamilyRows(stock, "obv", [{ label: "Volume confirmation", scoreKey: "darvas_volume_score", params: { ema_period: 20 } }])
  stock.entry_rules = [
    entryRule(
      "entry_darvas_box_breakout",
      "Darvas box breakout",
      ruleExpression([
        {
          type: "breakout",
          direction: "above",
          source: price("Close"),
          level: darvasBox("top", 20),
        },
        {
          type: "threshold",
          left: indicator("volume_sma_ratio", 20),
          operator: ">=",
          right: constant(1.3),
        },
      ]),
      25,
    ),
  ]
  stock.exit_rules = [
    exitRule(
      "exit_darvas_box_failure",
      "Darvas box failure",
      ruleExpression([
        {
          type: "breakdown",
          direction: "below",
          source: price("Close"),
          level: darvasBox("bottom", 10),
        },
      ]),
    ),
  ]
  return stock
}

export const STRATEGY_TEMPLATE_REGISTRY: StrategyTemplate[] = [
  {
    id: "turtle_donchian_20_10",
    name: "Turtle Donchian 20/10",
    author: "Richard Dennis / Turtle Traders",
    category: "breakout",
    summary: "Buy 20-bar highs and exit on 10-bar lows.",
    tags: ["Donchian", "breakout", "trend"],
    isExecutable: true,
    materialize: turtleDonchian,
  },
  {
    id: "sma_20_50_cross",
    name: "SMA 20/50 Cross",
    author: "Classic trend following",
    category: "trend",
    summary: "Enter when the fast average crosses above the slow average.",
    tags: ["SMA", "crossover"],
    isExecutable: true,
    materialize: movingAverageCross,
  },
  {
    id: "rsi_14_mean_reversion",
    name: "RSI 14 Mean Reversion",
    author: "J. Welles Wilder",
    category: "mean_reversion",
    summary: "Buy oversold RSI and exit near the mean.",
    tags: ["RSI", "oscillator"],
    isExecutable: true,
    materialize: rsiMeanReversion,
  },
  {
    id: "bollinger_20_2_mean_reversion",
    name: "Bollinger 20/2 Reversion",
    author: "John Bollinger",
    category: "mean_reversion",
    summary: "Fade closes outside the lower band and exit at the midline.",
    tags: ["Bollinger", "bands"],
    isExecutable: true,
    materialize: bollingerMeanReversion,
  },
  {
    id: "darvas_box_volume_breakout",
    name: "Darvas Box + Volume",
    author: "Nicolas Darvas",
    category: "volume",
    summary: "Buy box breakouts confirmed by relative volume.",
    tags: ["Darvas", "volume"],
    isExecutable: true,
    materialize: darvasBoxBreakout,
  },
]

export function materializeStrategyTemplate(
  templateId: string,
  horizon: HorizonKey,
  previous?: StockStrategyConfigV2 | null,
): StockStrategyConfigV2 | null {
  const template = STRATEGY_TEMPLATE_REGISTRY.find((item) => item.id === templateId && item.isExecutable)
  return template ? template.materialize(horizon, previous) : null
}
