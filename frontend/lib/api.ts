import { z } from "zod"

const API_BASE = "/api"

export const RunStatusEnum = z.enum([
  "created",
  "queued",
  "running",
  "cancel_requested",
  "canceled",
  "succeeded",
  "failed",
])

export type RunStatus = z.infer<typeof RunStatusEnum>

export const RunTypeEnum = z.enum(["backtest", "optimization", "decision_backtest"])
export type RunType = z.infer<typeof RunTypeEnum>

export const RunSchema = z.object({
  run_id: z.string(),
  status: RunStatusEnum,
  run_type: RunTypeEnum,
  mode: z.string().optional(),
  seed: z.number().nullable().optional(),
  dataset_hash: z.string().nullable().optional(),
  code_version: z.string().nullable().optional(),
  integrity_status: z.string().nullable().optional(),
  spec_json: z.record(z.unknown()).optional(),
  dataset_id: z.string().nullable().optional(),
  spec_hash: z.string().optional(),
  created_at: z.string().optional(),
  started_at: z.string().nullable().optional(),
  progress_pct: z.number().nullable().optional(),
  progress_stage: z.string().nullable().optional(),
  progress_message: z.string().nullable().optional(),
  last_heartbeat_at: z.string().nullable().optional(),
  rq_job_id: z.string().nullable().optional(),
  finished_at: z.string().nullable().optional(),
  error_message: z.string().nullable().optional(),
})
export type Run = z.infer<typeof RunSchema>

const RunIntegrityCheckSchema = z.object({
  check_name: z.string(),
  status: z.string(),
  details_json: z.record(z.unknown()).default({}),
  created_at: z.string(),
})

const RunIntegritySchema = z.object({
  run_id: z.string(),
  integrity_status: z.string().nullable().optional(),
  checks: z.array(RunIntegrityCheckSchema).default([]),
  report_url: z.string().url().nullable().optional(),
})
export type RunIntegrity = z.infer<typeof RunIntegritySchema>

const RunFoldSchema = z.object({
  fold_index: z.number(),
  fold_logical: z.number().default(0),
  trial_rank: z.number().default(1),
  strategy_kind: z.string().default(""),
  is_holdout: z.boolean().default(false),
  trial_id: z.string().default(""),
  train_start: z.string().nullable().optional(),
  train_end: z.string().nullable().optional(),
  test_start: z.string().nullable().optional(),
  test_end: z.string().nullable().optional(),
  fold_metrics_json: z.record(z.unknown()).default({}),
  fold_artifacts: z.record(z.unknown()).default({}),
  created_at: z.string(),
})

const WfoPeriodOutSchema = z.object({
  fold_no: z.number(),
  symbol: z.string().default(""),
  strategy_kind: z.string().default(""),
  horizon: z.string().nullable().optional(),
  train_start: z.string().nullable().optional(),
  train_end: z.string().nullable().optional(),
  test_start: z.string(),
  test_end: z.string(),
  winning_trial_id: z.string().default(""),
  optimal_params: z.record(z.unknown()).default({}),
  is_objective_name: z.string().nullable().optional(),
  is_objective_value: z.number().nullable().optional(),
  oos_pnl: z.number().nullable().optional(),
  oos_return: z.number().nullable().optional(),
  oos_cagr: z.number().nullable().optional(),
  oos_sharpe: z.number().nullable().optional(),
  oos_max_drawdown: z.number().nullable().optional(),
  oos_win_pct: z.number().nullable().optional(),
  oos_n_fills: z.number().nullable().optional(),
  cumulative_oos_pnl: z.number().nullable().optional(),
  is_holdout: z.boolean().default(false),
})
export type WfoPeriodOut = z.infer<typeof WfoPeriodOutSchema>

const StitchedOosSummarySchema = z.object({
  total_oos_pnl: z.number().nullable().optional(),
  mean_oos_sharpe: z.number().nullable().optional(),
  median_oos_sharpe: z.number().nullable().optional(),
  worst_fold_drawdown: z.number().nullable().optional(),
  profitable_folds: z.number().default(0),
  total_folds: z.number().default(0),
  profitable_pct: z.number().nullable().optional(),
})
export type StitchedOosSummary = z.infer<typeof StitchedOosSummarySchema>

const ClassicalWfoReportSchema = z.object({
  periods: z.array(WfoPeriodOutSchema).default([]),
  stitched_oos_summary: StitchedOosSummarySchema.default({}),
  current_live_params: z.record(z.unknown()).nullable().optional(),
  current_live_trial_id: z.string().nullable().optional(),
  final_holdout_summary: WfoPeriodOutSchema.nullable().optional(),
  data_source: z.string().default("run_wfo_period"),
})
export type ClassicalWfoReport = z.infer<typeof ClassicalWfoReportSchema>

const WfoCandidateSummarySchema = z.object({
  trial_id: z.string(),
  params: z.record(z.unknown()).optional(),
  fold_count: z.number().default(0),
  fold_coverage: z.number().nullable().optional(),
  objective_mean: z.number().nullable().optional(),
  objective_std: z.number().nullable().optional(),
  pnl_mean: z.number().nullable().optional(),
  sharpe_mean: z.number().nullable().optional(),
  max_drawdown_mean: z.number().nullable().optional(),
  win_pct_mean: z.number().nullable().optional(),
  rank_mean: z.number().nullable().optional(),
  is_winner: z.boolean().default(false),
})
export type WfoCandidateSummary = z.infer<typeof WfoCandidateSummarySchema>

const WfoFinalHoldoutSchema = z.object({
  fold_index: z.number().optional(),
  test_start: z.string().nullable().optional(),
  test_end: z.string().nullable().optional(),
  strategy_kind: z.string().default(""),
  trial_id: z.string().default(""),
  objective_value: z.number().nullable().optional(),
  pnl: z.number().nullable().optional(),
  cagr: z.number().nullable().optional(),
  sharpe: z.number().nullable().optional(),
  max_drawdown: z.number().nullable().optional(),
  win_pct: z.number().nullable().optional(),
  n_fills: z.number().nullable().optional(),
})
export type WfoFinalHoldout = z.infer<typeof WfoFinalHoldoutSchema>

const WfoSelectedWinnerSchema = z.object({
  trial_id: z.string(),
  fold_count: z.number().default(0),
  fold_coverage: z.number().nullable().optional(),
  objective_mean: z.number().nullable().optional(),
  objective_std: z.number().nullable().optional(),
  rank_mean: z.number().nullable().optional(),
  n_selection_folds: z.number().default(0),
  selection_reason: z.string().nullable().optional(),
})
export type WfoSelectedWinner = z.infer<typeof WfoSelectedWinnerSchema>

// Per-horizon data block used when is_multi_horizon=true (simple_wfo_multi_horizon runs).
// Horizons are kept separate; never merged across short/medium/long.
const WfoHorizonDataSchema = z.object({
  candidate_summaries: z.array(WfoCandidateSummarySchema).default([]),
  selected_winner: WfoSelectedWinnerSchema.nullable().optional(),
  final_holdout: WfoFinalHoldoutSchema.nullable().optional(),
})
export type WfoHorizonData = z.infer<typeof WfoHorizonDataSchema>

const WfoStrategyKindSummarySchema = z.object({
  // Standard WFO (single horizon): flat structure
  candidate_summaries: z.array(WfoCandidateSummarySchema).default([]),
  selected_winner: WfoSelectedWinnerSchema.nullable().optional(),
  final_holdout: WfoFinalHoldoutSchema.nullable().optional(),
  // Multi-horizon (simple_wfo_multi_horizon): nested by_horizon
  // When present, the flat fields above will be empty — use by_horizon instead
  by_horizon: z.record(z.string(), WfoHorizonDataSchema).optional(),
})
export type WfoStrategyKindSummary = z.infer<typeof WfoStrategyKindSummarySchema>

const RunWalkForwardSchema = z.object({
  run_id: z.string(),
  mode: z.string().nullable().optional(),
  horizon: z.string().nullable().optional(),
  horizon_label: z.string().nullable().optional(),
  horizon_cfg: z.record(z.unknown()).default({}),
  requested_start_date: z.string().nullable().optional(),
  requested_end_date: z.string().nullable().optional(),
  resolved_start_date: z.string().nullable().optional(),
  resolved_end_date: z.string().nullable().optional(),
  end_date_policy: z.string().nullable().optional(),
  date_resolution: z.record(z.unknown()).default({}),
  windows: z
    .object({
      train: z.record(z.unknown()).default({}),
      test: z.record(z.unknown()).default({}),
      step: z.record(z.unknown()).default({}),
    })
    .default({ train: {}, test: {}, step: {} }),
  aggregate: z
    .object({
      fold_count: z.number().default(0),
      n_selection_folds: z.number().default(0),
      objective_mean: z.number().nullable().optional(),
    })
    .default({ fold_count: 0, n_selection_folds: 0, objective_mean: null }),
  n_selection_folds: z.number().default(0),
  strategy_kinds: z.array(z.string()).default([]),
  by_strategy_kind: z.record(z.string(), WfoStrategyKindSummarySchema).default({}),
  legacy_aggregation: z.boolean().default(false),
  folds: z.array(RunFoldSchema).default([]),
  classical_wfo_report: ClassicalWfoReportSchema.nullable().optional(),
})
export type RunWalkForward = z.infer<typeof RunWalkForwardSchema>

const RunSignificanceSchema = z.object({
  method: z.string(),
  pvalue: z.number().nullable().optional(),
  statistic: z.number().nullable().optional(),
  mc_null_dist_ref: z.string().nullable().optional(),
  details_json: z.record(z.unknown()).default({}),
  created_at: z.string(),
})
export type RunSignificanceRow = z.infer<typeof RunSignificanceSchema>

const RunRiskSchema = z.object({
  run_id: z.string(),
  risk: z
    .object({
      kelly_fraction: z.number().nullable().optional(),
      half_kelly: z.number().nullable().optional(),
      chosen_leverage: z.number().nullable().optional(),
      mc_drawdown_pctl: z.number().nullable().optional(),
      mc_var: z.number().nullable().optional(),
      mc_cvar: z.number().nullable().optional(),
      details_json: z.record(z.unknown()).default({}),
      created_at: z.string(),
    })
    .nullable()
    .optional(),
})
export type RunRisk = z.infer<typeof RunRiskSchema>

const MeanReversionSchema = z.object({
  run_id: z.string(),
  report_url: z.string().url().nullable().optional(),
})
export type MeanReversionReport = z.infer<typeof MeanReversionSchema>

export const RunCreateResponseSchema = z.object({
  run_id: z.string(),
  status: z.string(),
  run_type: z.string(),
})

const WalkForwardResolveDatesResponseSchema = z.object({
  requested_start_date: z.string().nullable().optional(),
  requested_end_date: z.string().nullable().optional(),
  resolved_start_date: z.string(),
  resolved_end_date: z.string(),
  end_date_policy: z.string(),
  alignment_notes: z.record(z.unknown()).default({}),
  warnings: z.array(z.string()).default([]),
})
export type WalkForwardResolveDatesResponse = z.infer<typeof WalkForwardResolveDatesResponseSchema>

export const RunStartResponseSchema = z.object({
  run_id: z.string(),
  status: z.string(),
  job_id: z.string().optional(),
})

const NumericLike = z.number().nullable().optional()

export const LeaderboardRowSchema = z.object({
  run_id: z.string().optional(),
  symbol: z.string(),
  strategy_kind: z.string(),
  rank: z.number().optional(),
  pnl: NumericLike,
  cagr: NumericLike,
  total_return: NumericLike,
  sharpe: NumericLike,
  max_drawdown: NumericLike,
  win_pct: NumericLike,
  n_fills: NumericLike,
  efficiency: NumericLike,
  confidence_score: NumericLike,
  opportunity_score: NumericLike,
  horizon: z.string().nullable().optional(),
  signal_label: z.string().nullable().optional(),
  signal_today: NumericLike,
  signal_date: z.string().nullable().optional(),
  trial_id: z.string().nullable().optional(),
  best_params_json: z.unknown().optional(),
  plot_url: z.string().url().nullable().optional(),
  ledger_url: z.string().url().nullable().optional(),
  edge: z.lazy(() => EdgeMetricsSchema).nullable().optional(),
})
export type LeaderboardRow = z.infer<typeof LeaderboardRowSchema>

export const ExpectancyDecompSchema = z.object({
  p_win: z.number(),
  avg_win: z.number(),
  p_loss: z.number(),
  avg_loss: z.number(),
  expectancy: z.number(),
})
export type ExpectancyDecomp = z.infer<typeof ExpectancyDecompSchema>

export const EdgeGatesSchema = z.object({
  mc_gross: z.boolean(),
  mc_net: z.boolean(),
  wilson: z.boolean(),
  n: z.boolean(),
})
export type EdgeGates = z.infer<typeof EdgeGatesSchema>

export const EdgeMetricsSchema = z.object({
  symbol: z.string(),
  horizon: z.enum(["weekly", "monthly", "quarterly"]),
  source: z.enum(["signal_engine", "wfo"]),
  bucket: z.string(),
  direction: z.enum(["long", "short", "none"]),
  n: z.number(),
  window_start: z.string().nullable().optional(),
  window_end: z.string().nullable().optional(),
  expected_return_gross: z.number().nullable().optional(),
  expected_return_net: z.number().nullable().optional(),
  hit_rate: z.number().nullable().optional(),
  hit_ci_lower: z.number().nullable().optional(),
  hit_ci_upper: z.number().nullable().optional(),
  expectancy_gross: ExpectancyDecompSchema.nullable().optional(),
  expectancy_net: ExpectancyDecompSchema.nullable().optional(),
  edge_ratio_gross: z.number().nullable().optional(),
  edge_ratio_net: z.number().nullable().optional(),
  profit_factor_gross: z.number().nullable().optional(),
  profit_factor_net: z.number().nullable().optional(),
  mc_luck_pvalue_gross: z.number().nullable().optional(),
  mc_luck_pvalue_net: z.number().nullable().optional(),
  label_shuffle_pvalue_gross: z.number().nullable().optional(),
  label_shuffle_pvalue_net: z.number().nullable().optional(),
  proven_edge_gross: z.boolean(),
  proven_edge_net: z.boolean(),
  gates: EdgeGatesSchema,
  cost_bps_per_side: z.number(),
  methodology_version: z.string(),
  fragility_label: z.string().default("unavailable"),
  fragility_fold_count: z.number().default(0),
  fragility_details: z.array(z.record(z.unknown())).default([]),
})
export type EdgeMetrics = z.infer<typeof EdgeMetricsSchema>

export const FillRowSchema = z.object({
  id: z.string().optional(),
  run_id: z.string().optional(),
  timestamp: z.string().nullable().optional(),
  symbol: z.string().nullable().optional(),
  side: z.string().nullable().optional(),
  qty: NumericLike,
  price: NumericLike,
  fees: NumericLike,
  notional: NumericLike,
  meta: z.record(z.unknown()).nullable().optional(),
})
export type FillRow = z.infer<typeof FillRowSchema>

export const PositionRowSchema = z.object({
  id: z.string().optional(),
  run_id: z.string().optional(),
  timestamp: z.string().nullable().optional(),
  symbol: z.string().nullable().optional(),
  available_qty: NumericLike,
  cmp: NumericLike,
  position_value_cost: NumericLike,
  pnl_realise: NumericLike,
  pnl_latent: NumericLike,
  mark_price: NumericLike,
})
export type PositionRow = z.infer<typeof PositionRowSchema>

export const MetricRowSchema = z.object({
  run_id: z.string().optional(),
  symbol: z.string().nullable().optional(),
  metric_name: z.string(),
  metric_value: z.union([z.number(), z.string()]),
})
export type MetricRow = z.infer<typeof MetricRowSchema>

export const ArtifactSchema = z.object({
  id: z.string(),
  run_id: z.string(),
  symbol: z.string().nullable().optional(),
  artifact_type: z.string(),
  name: z.string(),
  object_key: z.string(),
  bucket: z.string(),
  content_type: z.string(),
  size_bytes: z.number(),
  sha256: z.string(),
  created_at: z.string(),
  url: z.string().url(),
})
export type Artifact = z.infer<typeof ArtifactSchema>

export const PlotlyFigureSchema = z.object({
  data: z.array(z.record(z.unknown())).default([]),
  layout: z.record(z.unknown()).default({}),
  frames: z.array(z.record(z.unknown())).optional(),
})
export type PlotlyFigure = z.infer<typeof PlotlyFigureSchema>

const MaterializedStrategyDetailsSchema = z.object({
  run_id: z.string(),
  symbol: z.string(),
  strategy_kind: z.string(),
  metrics: z.record(z.unknown()).default({}),
  trade_performance: z.array(z.record(z.unknown())).default([]),
  trade_ledger: z.array(z.record(z.unknown())).default([]),
  plots: z.record(z.record(z.unknown())).default({}),
  signal_label: z.string().nullable().optional(),
  signal_today: z.number().nullable().optional(),
  signal_date: z.string().nullable().optional(),
})
export type MaterializedStrategyDetails = z.infer<typeof MaterializedStrategyDetailsSchema>

const SmaDefaultsDiscoveryRunSchema = z.object({
  run_id: z.string(),
  strategy_name: z.string(),
  status: z.string(),
  ticker: z.string().nullable().optional(),
  dataset_id: z.string().nullable().optional(),
  created_at: z.string(),
  finished_at: z.string().nullable().optional(),
  params_json: z.record(z.unknown()).default({}),
  results_json: z.record(z.unknown()).nullable().optional(),
  artifacts_json: z.record(z.unknown()).default({}),
  progress_pct: z.number().nullable().optional(),
  progress_stage: z.string().nullable().optional(),
  progress_message: z.string().nullable().optional(),
  last_heartbeat_at: z.string().nullable().optional(),
  rq_job_id: z.string().nullable().optional(),
  error_message: z.string().nullable().optional(),
})
export type SmaDefaultsDiscoveryRun = z.infer<typeof SmaDefaultsDiscoveryRunSchema>

const StrategyDefaultSetSchema = z.object({
  id: z.number(),
  strategy_name: z.string(),
  source_run_id: z.string().nullable().optional(),
  defaults_json: z.record(z.unknown()).default({}),
  meta_json: z.record(z.unknown()).default({}),
  created_at: z.string(),
})
export type StrategyDefaultSet = z.infer<typeof StrategyDefaultSetSchema>

const DecisionLayerSchema = z.object({
  score: z.number(),
  weight: z.number(),
  inputs: z.record(z.unknown()).default({}),
  thresholds: z.record(z.unknown()).default({}),
  explain: z.string().default(""),
})

const DecisionScoreSchema = z.object({
  total: z.number(),
  layers: z.record(DecisionLayerSchema).default({}),
})

const DecisionLevelsSchema = z.object({
  support: z.number().nullable().optional(),
  resistance: z.number().nullable().optional(),
  entry: z.number().nullable().optional(),
  stop: z.number().nullable().optional(),
  target: z.number().nullable().optional(),
})

const DecisionRiskSchema = z.object({
  rr: z.number(),
  risk_per_share: z.number().nullable().optional(),
  reward_per_share: z.number().nullable().optional(),
  score: z.number(),
  invalidation: z.string().default(""),
})

const DecisionPageSchema = z.object({
  symbol: z.string(),
  strategy_kind: z.string(),
  trial_id: z.string(),
  direction: z.string(),
  status: z.string(),
  when_to_act: z.array(z.string()).default([]),
  levels: DecisionLevelsSchema.default({}),
  invalidation: z.string().default(""),
  risk: DecisionRiskSchema.default({ rr: 0, score: 0, invalidation: "" }),
  opportunity: DecisionScoreSchema.default({ total: 0, layers: {} }),
  confidence: DecisionScoreSchema.default({ total: 0, layers: {} }),
  opportunity_score: z.number(),
  confidence_score: z.number(),
  explain: z.record(z.unknown()).default({}),
  generated_at: z.string().nullable().optional(),
})

const StrategyDecisionSchema = z.object({
  run_id: z.string(),
  symbol: z.string(),
  strategy_kind: z.string(),
  trial_id: z.string(),
  rank: z.number().nullable().optional(),
  params_hash: z.string(),
  params_json: z.record(z.unknown()).default({}),
  opportunity_score: z.number(),
  confidence_score: z.number(),
  status: z.string(),
  opportunity_subscores: z.record(DecisionLayerSchema).default({}),
  confidence_subscores: z.record(DecisionLayerSchema).default({}),
  decision_page: DecisionPageSchema,
  explain: z.record(z.unknown()).default({}),
  computed_at: z.string(),
})
export type StrategyDecision = z.infer<typeof StrategyDecisionSchema>

const DecisionDashboardCheckSchema = z.object({
  name: z.string(),
  expr: z.string().default(""),
  value: z.unknown().optional(),
  threshold: z.unknown().optional(),
  pass: z.boolean(),
})

const DecisionDashboardSignalDebugSchema = z.object({
  rule_name: z.string(),
  inputs: z.record(z.unknown()).default({}),
  checks: z.array(DecisionDashboardCheckSchema).default([]),
  final_direction: z.number().default(0),
  strategy_direction: z.number().default(0),
  final_direction_label: z.string().default("neutral"),
})

const DecisionDashboardMarkerSchema = z.object({
  t: z.string(),
  value: z.number().nullable().optional(),
  direction: z.number().nullable().optional(),
  kind: z.string().nullable().optional(),
})

const DecisionDashboardTimeseriesSchema = z.object({
  t: z.array(z.string()).default([]),
  open: z.array(z.number().nullable().optional()).default([]),
  high: z.array(z.number().nullable().optional()).default([]),
  low: z.array(z.number().nullable().optional()).default([]),
  close: z.array(z.number().nullable().optional()).default([]),
  volume: z.array(z.number().nullable().optional()).default([]),
  sma_ref: z.array(z.number().nullable().optional()).default([]),
  sma100: z.array(z.number().nullable().optional()).default([]),
  sma200: z.array(z.number().nullable().optional()).default([]),
  rsi14: z.array(z.number().nullable().optional()).default([]),
  adx: z.array(z.number().nullable().optional()).default([]),
  atr: z.array(z.number().nullable().optional()).default([]),
  signal_markers: z.array(DecisionDashboardMarkerSchema).default([]),
  cross_markers: z.array(DecisionDashboardMarkerSchema).default([]),
})

const DecisionDashboardParamSchema = z.object({
  key: z.string(),
  value: z.unknown().optional(),
  description: z.string().default(""),
  impact: z.string().default(""),
})

const DecisionDashboardSchema = z.object({
  decision_summary: z.record(z.unknown()).default({}),
  strategy_params: z.array(DecisionDashboardParamSchema).default([]),
  derived_metrics: z.record(z.unknown()).default({}),
  regime: z.record(z.unknown()).default({}),
  signal_debug: DecisionDashboardSignalDebugSchema,
  levels: z.record(z.unknown()).default({}),
  confidence_layers: z.array(z.record(z.unknown())).default([]),
  framework_comparison: z.record(z.unknown()).default({}),
  timeseries: DecisionDashboardTimeseriesSchema,
})
export type DecisionDashboard = z.infer<typeof DecisionDashboardSchema>

export const STRATEGY_CATALOG = [
  { id: "sma_price", label: "SMA Price", description: "Simple Moving Average price crossover" },
  { id: "ma_cross", label: "MA Crossover", description: "Dual moving average crossover" },
  { id: "rsi", label: "RSI", description: "Relative Strength Index reversal/momentum" },
  { id: "macd", label: "MACD", description: "Moving Average Convergence Divergence" },
  { id: "bollinger", label: "Bollinger Bands", description: "Bollinger Bands mean reversion" },
  { id: "obv", label: "OBV", description: "On-Balance Volume trend" },
  { id: "stoch_vwap", label: "Stoch + VWAP", description: "Stochastic Oscillator with VWAP" },
  { id: "ichimoku", label: "Ichimoku", description: "Ichimoku Cloud trend system" },
] as const

export const PARAM_DEFAULTS: Record<string, string> = {
  "strategy.sma_window": "5,10,14,20,30,50,100,200",
  "strategy.signal_mode": "level,cross",
  "strategy.sma_fast_window": "5,8,10,12,15,20,30",
  "strategy.sma_slow_window": "20,30,50,80,100,150,200",
  "strategy.rsi_window": "7,10,14,21,28",
  "strategy.rsi_oversold": "20,25,30,35",
  "strategy.rsi_overbought": "65,70,75,80",
  "strategy.macd_fast_window": "8,10,12,15,26",
  "strategy.macd_slow_window": "20,26,30,36,50",
  "strategy.macd_signal_window": "5,7,9,12,20",
  "strategy.bb_window": "10,14,20,30,50",
  "strategy.bb_k": "1,1.5,2,2.5,3",
  "strategy.obv_span": "5,10,14,20,30,50,100",
  "strategy.k_window": "7,10,14,21,28",
  "strategy.d_window": "2,3,5,7",
  "strategy.smooth_k": "1,2,3,5",
  "strategy.vwap_window": "10,14,20,30,50",
  "strategy.tenkan": "7,9,12",
  "strategy.kijun": "22,26,30",
  "strategy.senkou_b": "44,52,60",
  "strategy.shift": "22,26,30",
  "portfolio.cooldown_bars": "0,5,10,21,60,120",
  "portfolio.buy_pct_cash": "0.1,0.25,0.5,0.75,1.0",
  "portfolio.sell_pct_shares": "0.1,0.25,0.5,0.75,1.0",
  "portfolio.min_return_before_sell": "0.0,0.01,0.02,0.05,0.10",
}

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`
  const headers = new Headers(options?.headers)
  const hasBody = options?.body !== undefined && options?.body !== null
  const isFormData = typeof FormData !== "undefined" && options?.body instanceof FormData
  if (hasBody && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }

  const res = await fetch(url, {
    ...options,
    headers,
    cache: options?.cache ?? "no-store",
  })

  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error")
    throw new ApiError(`${res.status}: ${text}`, res.status)
  }

  if (res.status === 204) {
    return undefined as T
  }
  return res.json() as Promise<T>
}

export async function createRun(body: {
  spec_hash: string
  dataset_id?: string | null
  spec_json: Record<string, unknown>
}) {
  const payload = await request<unknown>("/runs", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return RunCreateResponseSchema.parse(payload)
}

export async function resolveWalkForwardDates(body: {
  dataset_id?: string | null
  spec_json: Record<string, unknown>
}) {
  const payload = await request<unknown>("/runs/walk-forward/resolve-dates", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return WalkForwardResolveDatesResponseSchema.parse(payload)
}

export async function listRuns(params?: {
  status?: string
  run_type?: string
  dataset_id?: string
  limit?: number
  offset?: number
}) {
  const qs = new URLSearchParams()
  if (params?.status) qs.set("status", params.status)
  if (params?.run_type) qs.set("run_type", params.run_type)
  if (params?.dataset_id) qs.set("dataset_id", params.dataset_id)
  if (params?.limit !== undefined) qs.set("limit", String(params.limit))
  if (params?.offset !== undefined) qs.set("offset", String(params.offset))
  const q = qs.toString()

  const rows = await request<unknown[]>(`/runs${q ? `?${q}` : ""}`)
  return z.array(RunSchema).parse(rows)
}

export async function getRun(runId: string) {
  const row = await request<unknown>(`/runs/${runId}`)
  return RunSchema.parse(row)
}

export async function getRunIntegrity(runId: string) {
  const row = await request<unknown>(`/runs/${runId}/integrity`)
  return RunIntegritySchema.parse(row)
}

export async function getRunWalkForward(runId: string) {
  const row = await request<unknown>(`/runs/${runId}/walk-forward`)
  return RunWalkForwardSchema.parse(row)
}

export async function getRunSignificance(runId: string) {
  const rows = await request<unknown[]>(`/runs/${runId}/significance`)
  return z.array(RunSignificanceSchema).parse(rows)
}

export async function getRunRisk(runId: string) {
  const row = await request<unknown>(`/runs/${runId}/risk`)
  return RunRiskSchema.parse(row)
}

export async function getRunMeanReversion(runId: string) {
  const row = await request<unknown>(`/runs/${runId}/mean-reversion`)
  return MeanReversionSchema.parse(row)
}

export async function startRun(runId: string) {
  const payload = await request<unknown>(`/runs/${runId}/start`, { method: "POST" })
  return RunStartResponseSchema.parse(payload)
}

export async function cancelRun(runId: string) {
  const payload = await request<unknown>(`/runs/${runId}/cancel`, { method: "POST" })
  return payload as { run_id: string; status: string; job_id?: string | null }
}

export async function deleteRun(runId: string) {
  const payload = await request<unknown>(`/runs/${runId}`, { method: "DELETE" })
  return payload as {
    run_id: string
    status: string
    metrics_deleted?: number
    fills_deleted?: number
    positions_deleted?: number
    leaderboard_deleted?: number
    decisions_deleted?: number
    integrity_deleted?: number
    folds_deleted?: number
    significance_deleted?: number
    risk_deleted?: number
    artifacts_deleted?: number
    artifact_objects_deleted?: number
    artifact_object_delete_failed?: number
  }
}

export async function launchSmaDefaultsDiscovery(body: {
  strategy_name?: string
  ticker?: string | null
  dataset_id?: string | null
  timeframe?: string
  start_date?: string | null
  end_date?: string | null
  horizon?: string | null
  horizon_overrides?: Record<string, unknown> | null
  compute_all_horizons?: boolean
  walk_forward?: {
    train_window?: number | null
    step_size?: number | null
    use_test_window?: boolean | null
    test_window?: number | null
    enforce_feasible_train_half?: boolean
    override_feasible_max_n?: number | null
  }
  buckets?: Array<{ bucket_id: string; low: number; high: number }>
  score_settings?: {
    drawdown_weight?: number
    turnover_weight?: number
    mode_threshold?: number
  }
  signal_params?: {
    buy_threshold_perc?: number
    sell_threshold_perc?: number
    cooldown_days?: number
    min_volume?: number
  }
  use_net_after_costs?: boolean
  snap_to_nice?: boolean
  allow_short?: boolean
  signal_mode?: string
  cost_model?: Record<string, unknown>
}) {
  const payload = await request<unknown>("/defaults/sma/discover", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return z
    .object({
      run_id: z.string(),
      status: z.string(),
      job_id: z.string().nullable().optional(),
    })
    .parse(payload)
}

export async function listDefaultsRuns(params?: { limit?: number; strategy_name?: string }) {
  const qs = new URLSearchParams()
  if (params?.limit !== undefined) qs.set("limit", String(params.limit))
  if (params?.strategy_name) qs.set("strategy_name", params.strategy_name)
  const q = qs.toString()
  const rows = await request<unknown[]>(`/defaults/runs${q ? `?${q}` : ""}`)
  return z.array(SmaDefaultsDiscoveryRunSchema).parse(rows)
}

export async function getDefaultsRun(runId: string) {
  const row = await request<unknown>(`/defaults/runs/${runId}`)
  return SmaDefaultsDiscoveryRunSchema.parse(row)
}

export async function deleteDefaultsRun(runId: string) {
  const payload = await request<unknown>(`/defaults/runs/${runId}`, { method: "DELETE" })
  return payload as {
    run_id: string
    status: string
    previous_status?: string
    job_id?: string | null
    queued_job_canceled?: boolean
    default_sets_unlinked?: number
    artifact_objects_deleted?: number
    artifact_object_delete_failed?: number
  }
}

export async function applyDefaultsRun(runId: string, params?: { horizon?: string }) {
  const qs = new URLSearchParams()
  if (params?.horizon) qs.set("horizon", params.horizon)
  const q = qs.toString()
  const row = await request<unknown>(`/defaults/runs/${runId}/apply${q ? `?${q}` : ""}`, { method: "POST" })
  return StrategyDefaultSetSchema.parse(row)
}

export async function listSmaDefaultSets(params?: { limit?: number }) {
  const qs = new URLSearchParams()
  if (params?.limit !== undefined) qs.set("limit", String(params.limit))
  const q = qs.toString()
  const rows = await request<unknown[]>(`/defaults/strategy/sma/default-sets${q ? `?${q}` : ""}`)
  return z.array(StrategyDefaultSetSchema).parse(rows)
}

export async function getLatestSmaDefaultSet() {
  const row = await request<unknown>("/defaults/strategy/sma/default-sets/latest")
  return StrategyDefaultSetSchema.parse(row)
}


export async function getLeaderboard(
  runId: string,
  params?: { symbol?: string; best_only?: boolean }
) {
  const qs = new URLSearchParams()
  if (params?.symbol) qs.set("symbol", params.symbol)
  if (params?.best_only !== undefined) qs.set("best_only", String(params.best_only))
  const q = qs.toString()

  const rows = await request<unknown[]>(`/runs/${runId}/leaderboard${q ? `?${q}` : ""}`)
  return z.array(LeaderboardRowSchema).parse(rows)
}

export async function fetchEdge(
  symbol: string,
  horizon: "weekly" | "monthly" | "quarterly",
  source: "signal_engine" | "wfo",
  costBps: number = 33,
): Promise<EdgeMetrics | null> {
  const qs = new URLSearchParams({
    symbol,
    horizon,
    source,
    cost_bps: String(costBps),
  })
  const payload = await request<unknown | null>(`/analytics/edge?${qs.toString()}`)
  if (payload == null) {
    return null
  }
  return EdgeMetricsSchema.parse(payload)
}

export async function getRunDecisions(
  runId: string,
  params?: { symbol?: string; best_only?: boolean }
) {
  const qs = new URLSearchParams()
  if (params?.symbol) qs.set("symbol", params.symbol)
  if (params?.best_only !== undefined) qs.set("best_only", String(params.best_only))
  const q = qs.toString()

  const rows = await request<unknown[]>(`/runs/${runId}/decisions${q ? `?${q}` : ""}`)
  return z.array(StrategyDecisionSchema).parse(rows)
}

export async function getRunDecision(
  runId: string,
  symbol: string,
  strategyKind: string,
  trialId: string
) {
  const s = encodeURIComponent(symbol)
  const k = encodeURIComponent(strategyKind)
  const t = encodeURIComponent(trialId)
  const row = await request<unknown>(`/runs/${runId}/decisions/${s}/${k}/${t}`)
  return StrategyDecisionSchema.parse(row)
}

export async function getRunDecisionDashboard(
  runId: string,
  symbol: string,
  strategyKind: string,
  trialId: string,
  params?: { bars?: number }
) {
  const s = encodeURIComponent(symbol)
  const k = encodeURIComponent(strategyKind)
  const t = encodeURIComponent(trialId)
  const qs = new URLSearchParams()
  if (params?.bars !== undefined) qs.set("bars", String(params.bars))
  const q = qs.toString()
  const row = await request<unknown>(
    `/runs/${runId}/decisions/${s}/${k}/${t}/dashboard${q ? `?${q}` : ""}`
  )
  return DecisionDashboardSchema.parse(row)
}

export async function getFills(
  runId: string,
  params?: { symbol?: string; limit?: number; cursor?: string }
) {
  const qs = new URLSearchParams()
  if (params?.symbol) qs.set("symbol", params.symbol)
  if (params?.limit !== undefined) qs.set("limit", String(params.limit))
  if (params?.cursor) qs.set("cursor", params.cursor)
  const q = qs.toString()

  const rows = await request<unknown[]>(`/runs/${runId}/fills${q ? `?${q}` : ""}`)
  return z.array(FillRowSchema).parse(rows)
}

export async function getPositionLedger(
  runId: string,
  params?: { symbol?: string; limit?: number; cursor?: string }
) {
  const qs = new URLSearchParams()
  if (params?.symbol) qs.set("symbol", params.symbol)
  if (params?.limit !== undefined) qs.set("limit", String(params.limit))
  if (params?.cursor) qs.set("cursor", params.cursor)
  const q = qs.toString()

  const rows = await request<unknown[]>(`/runs/${runId}/position-ledger${q ? `?${q}` : ""}`)
  return z.array(PositionRowSchema).parse(rows)
}

export async function getMetrics(runId: string) {
  const rows = await request<unknown[]>(`/runs/${runId}/metrics`)
  return z.array(MetricRowSchema).parse(rows)
}

export async function getArtifacts(runId: string, params?: { symbol?: string }) {
  const qs = new URLSearchParams()
  if (params?.symbol) qs.set("symbol", params.symbol)
  const q = qs.toString()

  const rows = await request<unknown[]>(`/runs/${runId}/artifacts${q ? `?${q}` : ""}`)
  return z.array(ArtifactSchema).parse(rows)
}

export function toArtifactProxyUrl(rawUrl: string): string {
  return `${API_BASE}/artifacts/fetch?url=${encodeURIComponent(rawUrl)}`
}

function extractObjectKeyFromUrl(rawUrl: string): string | null {
  try {
    const parsed = new URL(rawUrl)
    const keyParam = parsed.searchParams.get("Key") ?? parsed.searchParams.get("key")
    if (keyParam) return keyParam.replace(/^\/+/, "")

    const parts = parsed.pathname
      .split("/")
      .map((part) => part.trim())
      .filter(Boolean)

    if (!parts.length) return null

    const runsIdx = parts.findIndex((part) => part.toLowerCase() === "runs")
    if (runsIdx >= 0) return parts.slice(runsIdx).join("/")
    return null
  } catch {
    return null
  }
}

function extractRunIdFromObjectKey(objectKey: string): string | null {
  const parts = objectKey
    .split("/")
    .map((part) => part.trim())
    .filter(Boolean)

  const runsIdx = parts.findIndex((part) => part.toLowerCase() === "runs")
  if (runsIdx < 0 || runsIdx + 1 >= parts.length) return null
  return parts[runsIdx + 1]
}

function isExpiredPresignedUrlError(status: number, text: string): boolean {
  if (status !== 400 && status !== 403) return false
  const lowered = text.toLowerCase()
  return lowered.includes("request has expired") || lowered.includes("requestexpired")
}

async function refreshArtifactUrl(
  rawUrl: string,
  objectKeyHint?: string
): Promise<string | null> {
  const objectKey = objectKeyHint?.trim() || extractObjectKeyFromUrl(rawUrl)
  if (!objectKey) return null

  const runId = extractRunIdFromObjectKey(objectKey)
  if (!runId) return null

  try {
    const artifacts = await getArtifacts(runId)
    const match = artifacts.find((item) => item.object_key === objectKey)
    return match?.url ?? null
  } catch {
    return null
  }
}

async function fetchArtifactWithRefresh(
  rawUrl: string,
  accept: string,
  objectKeyHint?: string
): Promise<Response> {
  const requestWithUrl = (url: string) =>
    fetch(toArtifactProxyUrl(url), {
      headers: { Accept: accept },
      cache: "no-store",
    })

  let res = await requestWithUrl(rawUrl)
  if (res.ok) return res

  const text = await res.text().catch(() => "Unknown error")
  if (!isExpiredPresignedUrlError(res.status, text)) {
    throw new ApiError(`${res.status}: ${text}`, res.status)
  }

  const refreshed = await refreshArtifactUrl(rawUrl, objectKeyHint)
  if (!refreshed || refreshed === rawUrl) {
    throw new ApiError(`${res.status}: ${text}`, res.status)
  }

  res = await requestWithUrl(refreshed)
  if (!res.ok) {
    const retryText = await res.text().catch(() => "Unknown error")
    throw new ApiError(`${res.status}: ${retryText}`, res.status)
  }

  return res
}

export async function fetchArtifactJson(rawUrl: string, objectKeyHint?: string) {
  const res = await fetchArtifactWithRefresh(rawUrl, "application/json", objectKeyHint)

  const payload = (await res.json()) as unknown
  return PlotlyFigureSchema.parse(payload)
}

export async function fetchArtifactText(rawUrl: string, objectKeyHint?: string) {
  const res = await fetchArtifactWithRefresh(
    rawUrl,
    "text/csv,text/plain,*/*",
    objectKeyHint
  )
  return res.text()
}

export async function fetchArtifact(
  runId: string,
  symbol: string,
  strategyKind: string,
  filename: string
): Promise<unknown> {
  const artifacts = await getArtifacts(runId, { symbol })
  const strategy = strategyKind.trim().toLowerCase()
  const file = filename.trim().toLowerCase()

  const artifact = artifacts.find((item) => {
    const name = item.name.toLowerCase()
    return (
      name === file ||
      name === `${strategy}.${file}` ||
      (name.startsWith(`${strategy}.`) && name.endsWith(file))
    )
  })

  if (!artifact) {
    throw new ApiError(
      `Artifact not found for run=${runId}, symbol=${symbol}, strategy=${strategyKind}, filename=${filename}`,
      404
    )
  }

  const looksLikeJson =
    artifact.content_type.toLowerCase().includes("json") ||
    artifact.name.toLowerCase().endsWith(".json")

  if (looksLikeJson) return fetchArtifactJson(artifact.url, artifact.object_key)
  return fetchArtifactText(artifact.url, artifact.object_key)
}

export async function materializeStrategyDetails(
  runId: string,
  body: {
    symbol: string
    strategy_kind: string
    strategy_params?: Record<string, unknown>
    portfolio_overrides?: Record<string, unknown>
  }
) {
  const payload = await request<unknown>(`/runs/${runId}/materialize-strategy-details`, {
    method: "POST",
    body: JSON.stringify(body),
  })
  return MaterializedStrategyDetailsSchema.parse(payload)
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize)
  if (value && typeof value === "object" && value.constructor === Object) {
    const out: Record<string, unknown> = {}
    for (const k of Object.keys(value).sort()) {
      out[k] = canonicalize((value as Record<string, unknown>)[k])
    }
    return out
  }
  return value
}

export async function computeSpecHash(spec: Record<string, unknown>): Promise<string> {
  const canonical = JSON.stringify(canonicalize(spec))
  const encoder = new TextEncoder()
  const data = encoder.encode(canonical)
  const subtle = globalThis.crypto?.subtle
  if (subtle && typeof subtle.digest === "function") {
    const hashBuffer = await subtle.digest("SHA-256", data)
    const hashArray = Array.from(new Uint8Array(hashBuffer))
    return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("")
  }

  // Fallback for non-secure browser contexts where WebCrypto is unavailable.
  // API recomputes the canonical hash server-side from spec_json.
  let a = 0x243f6a88
  let b = 0x85a308d3
  let c = 0x13198a2e
  let d = 0x03707344

  for (let i = 0; i < canonical.length; i += 1) {
    const x = canonical.charCodeAt(i)
    a = Math.imul(a ^ x, 0x9e3779b1)
    b = Math.imul((b + x) | 0, 0x85ebca77)
    c = Math.imul(c ^ ((x << (i % 24)) | (x >>> (24 - (i % 24)))), 0xc2b2ae3d)
    d = Math.imul((d + (x ^ i)) | 0, 0x27d4eb2f)

    a ^= a >>> 16
    b ^= b >>> 13
    c ^= c >>> 16
    d ^= d >>> 15
  }

  const words = [a >>> 0, b >>> 0, c >>> 0, d >>> 0]
  while (words.length < 8) {
    const prev = words[words.length - 1]!
    const prev2 = words[words.length - 2]!
    const next =
      (Math.imul((prev ^ (prev >>> 16)) + words.length + 0x9e3779b9, 0x85ebca6b) ^
        (prev2 >>> 13)) >>>
      0
    words.push(next)
  }

  return words.map((w) => w.toString(16).padStart(8, "0")).join("")
}

export const fetcher = <T>(path: string) => request<T>(path)

const DatasetRowSchema = z.object({
  dataset_id: z.string().optional(),
  id: z.string().optional(),
  source: z.string().optional(),
  filename: z.string().optional(),
  sha256: z.string().optional(),
  created_at: z.string().optional(),
  meta: z.unknown().optional(),
  detected_symbols: z.array(z.string()).optional(),
})

export type Dataset = {
  id: string
  dataset_id: string
  source?: string
  filename?: string
  sha256?: string
  created_at?: string
  meta?: unknown
  detected_symbols?: string[]
}

export async function listDatasets(): Promise<Dataset[]> {
  const rows = await request<unknown[]>("/datasets")
  const parsed = z.array(DatasetRowSchema).parse(rows)

  const out: Dataset[] = []
  for (const row of parsed) {
    const dataset_id = row.dataset_id ?? row.id
    if (!dataset_id) continue
    out.push({
      id: dataset_id,
      dataset_id,
      source: row.source,
      filename: row.filename,
      sha256: row.sha256,
      created_at: row.created_at,
      meta: row.meta,
      detected_symbols: row.detected_symbols,
    })
  }
  return out
}

const MarketSymbolRowSchema = z.object({
  symbol: z.string(),
  timeframe: z.string().optional(),
  object_key: z.string().optional(),
  start_ts: z.string().nullable().optional(),
  end_ts: z.string().nullable().optional(),
  row_count: z.number().nullable().optional(),
  updated_at: z.string().nullable().optional(),
  source_provider: z.string().nullable().optional(),
})

export type MarketSymbolRow = z.infer<typeof MarketSymbolRowSchema>

export async function listMarketSymbols(params?: { timeframe?: string }): Promise<MarketSymbolRow[]> {
  const qs = new URLSearchParams()
  if (params?.timeframe) qs.set("timeframe", params.timeframe)
  const q = qs.toString()

  const rows = await request<unknown[]>(`/market-data/symbols${q ? `?${q}` : ""}`)
  return z.array(MarketSymbolRowSchema).parse(rows)
}

export async function uploadExcelFile(
  file: File,
  options?: {
    uploadScope?: "masi" | "other"
    metadata?: Record<string, unknown>
  },
): Promise<{ dataset_id: string; job_id: string }> {
  const form = new FormData()
  form.append("file", file)
  const metadata: Record<string, unknown> = { ...(options?.metadata ?? {}) }
  if (options?.uploadScope) {
    metadata.upload_scope = options.uploadScope
  }
  if (Object.keys(metadata).length > 0) {
    form.append("metadata_json", JSON.stringify(metadata))
  }
  const res = await fetch(`${API_BASE}/market-data/excel`, {
    method: "POST",
    body: form,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => "Upload failed")
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json()
}

export interface IngestSymbolResult {
  canonical_symbol: string | null
  status: "created" | "updated" | "unchanged" | "error"
  error?: string
  error_code?: string
  final_status_reason?: string
  row_count?: number
  is_new_ticker?: boolean
}

export interface IngestStatusResponse {
  status: "processing" | "done"
  report?: {
    dataset_id: string
    symbols: Record<string, IngestSymbolResult>
    errors: string[]
  }
}

export async function pollIngestStatus(datasetId: string): Promise<IngestStatusResponse> {
  return request<IngestStatusResponse>(`/market-data/uploads/${datasetId}/status`)
}

/**
 * Poll until the ingest worker finishes (or timeout).
 * Returns the final report, or null if timed out.
 */
export async function waitForIngestCompletion(
  datasetId: string,
  { intervalMs = 1500, timeoutMs = 300_000 } = {},
): Promise<IngestStatusResponse> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const resp = await pollIngestStatus(datasetId)
    if (resp.status === "done") return resp
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  return { status: "processing" }
}

const SmaTechnicalVariationSchema = z.object({
  window: z.number(),
  sma_value: z.number().nullable().optional(),
  close_value: z.number().nullable().optional(),
  signal_value: z.number(),
  signal: z.string(),
  sufficient_data: z.boolean(),
})
export type SmaTechnicalVariation = z.infer<typeof SmaTechnicalVariationSchema>

const SmaTechnicalResultSchema = z.object({
  symbol: z.string(),
  status: z.string(),
  error: z.string().nullable().optional(),
  timeframe: z.string(),
  windows: z.array(z.number()),
  as_of: z.string().nullable().optional(),
  latest_close: z.number().nullable().optional(),
  consensus_signal: z.string(),
  consensus_value: z.number(),
  score_pct: z.number(),
  agreement_count: z.number(),
  directional_windows: z.number(),
  buy_count: z.number(),
  sell_count: z.number(),
  hold_count: z.number(),
  skipped_windows: z.number(),
  variations: z.array(SmaTechnicalVariationSchema),
})
export type SmaTechnicalResult = z.infer<typeof SmaTechnicalResultSchema>

const SmaTechnicalStudyResponseSchema = z.object({
  strategy_kind: z.string(),
  timeframe: z.string(),
  windows: z.array(z.number()),
  score_basis: z.string(),
  results: z.array(SmaTechnicalResultSchema),
})
export type SmaTechnicalStudyResponse = z.infer<typeof SmaTechnicalStudyResponseSchema>

export async function technicalStudySma(body: {
  symbols: string[]
  windows: number[]
  timeframe?: string
}): Promise<SmaTechnicalStudyResponse> {
  const payload = await request<unknown>("/market-data/technical-study/sma", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return SmaTechnicalStudyResponseSchema.parse(payload)
}

const UploadDatasetResponseSchema = z.object({
  dataset_id: z.string(),
  filename: z.string(),
  sha256: z.string(),
  object_key: z.string(),
  meta: z
    .object({
      detected_symbols: z.array(z.string()).optional(),
    })
    .catchall(z.unknown())
    .optional(),
  download_url: z.string().optional(),
})
export type UploadDatasetResponse = z.infer<typeof UploadDatasetResponseSchema>

export async function deleteDataset(datasetId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/datasets/${datasetId}`, {
    method: "DELETE",
    cache: "no-store",
  })
  if (!res.ok && res.status !== 204) {
    const text = await res.text().catch(() => "Unknown error")
    throw new ApiError(`${res.status}: ${text}`, res.status)
  }
}

export async function uploadDataset(
  file: File,
  metadata?: Record<string, unknown>
): Promise<UploadDatasetResponse> {
  const form = new FormData()
  form.append("file", file)
  if (metadata) form.append("metadata_json", JSON.stringify(metadata))

  const res = await fetch(`${API_BASE}/datasets/upload`, {
    method: "POST",
    body: form,
    cache: "no-store",
  })
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error")
    throw new ApiError(`${res.status}: ${text}`, res.status)
  }

  const payload = (await res.json()) as unknown
  return UploadDatasetResponseSchema.parse(payload)
}

// ── Moroccan Market Data — Stock Registry & Refresh ──────────────────────────

export const StockMasterSchema = z.object({
  symbol: z.string(),
  display_name: z.string().nullable().optional(),
  isin: z.string().nullable().optional(),
  sector: z.string().nullable().optional(),
  market_cap_class: z.string().nullable().optional(),
  is_active: z.boolean(),
  track_source: z.string(),
  bourse_url: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
  created_at: z.string().nullable().optional(),
  updated_at: z.string().nullable().optional(),
  // Freshness (joined from market_data_store)
  start_ts: z.string().nullable().optional(),
  end_ts: z.string().nullable().optional(),
  row_count: z.number().nullable().optional(),
  store_updated_at: z.string().nullable().optional(),
  source_provider: z.string().nullable().optional(),
  data_as_of: z.string().nullable().optional(),
  is_stale: z.boolean().default(false),
})
export type StockMaster = z.infer<typeof StockMasterSchema>

export const BourseStockLookupSchema = z.object({
  symbol: z.string(),
  bourse_url: z.string(),
  display_name: z.string().nullable().optional(),
  sector: z.string().nullable().optional(),
  isin: z.string().nullable().optional(),
  found: z.boolean(),
})
export type BourseStockLookup = z.infer<typeof BourseStockLookupSchema>

export const ProviderSymbolMapSchema = z.object({
  id: z.number(),
  symbol: z.string(),
  provider: z.string(),
  provider_symbol: z.string(),
  confidence: z.number(),
  is_verified: z.boolean(),
  override_reason: z.string().nullable().optional(),
  created_at: z.string().nullable().optional(),
})
export type ProviderSymbolMap = z.infer<typeof ProviderSymbolMapSchema>

export const MarketRefreshRunSchema = z.object({
  id: z.string(),
  trigger_source: z.string(),
  scope: z.string(),
  symbol: z.string().nullable().optional(),
  timeframe: z.string(),
  status: z.string(),
  rq_job_id: z.string().nullable().optional(),
  symbols_total: z.number().nullable().optional(),
  symbols_done: z.number().nullable().optional(),
  symbols_failed: z.number().nullable().optional(),
  started_at: z.string().nullable().optional(),
  finished_at: z.string().nullable().optional(),
  created_at: z.string(),
  error_message: z.string().nullable().optional(),
  meta_json: z.record(z.unknown()).default({}),
})
export type MarketRefreshRun = z.infer<typeof MarketRefreshRunSchema>

export const MarketHealthSchema = z.object({
  total_tracked: z.number(),
  up_to_date: z.number(),
  stale: z.number(),
  very_stale: z.number(),
  never_ingested: z.number(),
  last_refresh_run: MarketRefreshRunSchema.nullable().optional(),
  last_successful_refresh: z.string().nullable().optional(),
})
export type MarketHealth = z.infer<typeof MarketHealthSchema>

export const OhlcvBarSchema = z.object({
  date: z.string(),
  open: z.number().nullable().optional(),
  high: z.number().nullable().optional(),
  low: z.number().nullable().optional(),
  close: z.number().nullable().optional(),
  volume: z.number().nullable().optional(),
})

export const OhlcvPreviewSchema = z.object({
  symbol: z.string(),
  timeframe: z.string(),
  bars: z.array(OhlcvBarSchema),
  source_provider: z.string().nullable().optional(),
  data_as_of: z.string().nullable().optional(),
  row_count: z.number().nullable().optional(),
})
export const OhlcvHistorySchema = z.object({
  symbol: z.string(),
  timeframe: z.string(),
  bars: z.array(OhlcvBarSchema),
  source_provider: z.string().nullable().optional(),
  data_as_of: z.string().nullable().optional(),
  row_count: z.number().nullable().optional(),
})
export type OhlcvBar = z.infer<typeof OhlcvBarSchema>
export type OhlcvPreview = z.infer<typeof OhlcvPreviewSchema>
export type OhlcvHistory = z.infer<typeof OhlcvHistorySchema>

export const UploadFormatDefinitionSchema = z.object({
  format_id: z.string(),
  label: z.string(),
  aliases: z.record(z.array(z.string())),
  numeric_examples: z.array(z.string()),
  volume_suffixes: z.array(z.string()),
  notes: z.array(z.string()).default([]),
})
export const UploadFormatReferenceSchema = z.object({
  canonical_fields: z.array(z.string()),
  formats: z.array(UploadFormatDefinitionSchema),
  validation: z.object({
    required_fields: z.array(z.string()),
    note: z.string(),
  }),
})
export type UploadFormatReference = z.infer<typeof UploadFormatReferenceSchema>

export const AvailabilityCalendarDaySchema = z.object({
  date: z.string(),
  state: z.string(),
  has_data: z.boolean().default(false),
  holiday_name: z.string().nullable().optional(),
  holiday_certainty: z.string().nullable().optional(),
  missing_fields: z.array(z.string()).default([]),
})
export const AvailabilityCalendarSchema = z.object({
  symbol: z.string(),
  timeframe: z.string(),
  first_date: z.string().nullable().optional(),
  last_date: z.string().nullable().optional(),
  default_month: z.string().nullable().optional(),
  days: z.array(AvailabilityCalendarDaySchema),
  present_days: z.number().default(0),
  missing_expected_days: z.number().default(0),
  weekend_days: z.number().default(0),
  market_holiday_days: z.number().default(0),
  tentative_market_holiday_days: z.number().default(0),
  partial_days: z.number().default(0),
})
export type AvailabilityCalendarDay = z.infer<typeof AvailabilityCalendarDaySchema>
export type AvailabilityCalendar = z.infer<typeof AvailabilityCalendarSchema>

// ── Market Catalog (unified /data-page view) ──────────────────────────────────

export const MarketCatalogRowSchema = z.object({
  symbol: z.string(),
  // From stock_master (null if symbol exists only in market_data_store)
  display_name: z.string().nullable().optional(),
  isin: z.string().nullable().optional(),
  sector: z.string().nullable().optional(),
  is_active: z.boolean().nullable().optional(),
  track_source: z.string().nullable().optional(),
  bourse_url: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
  // From market_data_store (null if tracked but not yet ingested)
  start_ts: z.string().nullable().optional(),
  end_ts: z.string().nullable().optional(),
  row_count: z.number().nullable().optional(),
  source_provider: z.string().nullable().optional(),
  data_as_of: z.string().nullable().optional(),
  is_stale: z.boolean().default(false),
  // Derived flags
  is_tracked: z.boolean().default(false),
  has_canonical_data: z.boolean().default(false),
  market: z.string().default("masi"),
  // Asset taxonomy
  asset_type: z.string().default("equity"),   // "equity" | "commodity" | "forex" | "bond"
  market_region: z.string().nullable().optional(), // "masi" | "us" | "european" | "asian" | null
})
export type MarketCatalogRow = z.infer<typeof MarketCatalogRowSchema>

export const MacroFactorSchema = z.object({
  canonical_id: z.string(),
  yahoo_ticker: z.string(),
  display_name: z.string(),
  asset_type: z.string(),
  market_region: z.string().nullable().optional(),
  active: z.boolean(),
  added_via: z.string(),
})
export type MacroFactor = z.infer<typeof MacroFactorSchema>

export async function listMarketCatalog(): Promise<MarketCatalogRow[]> {
  const rows = await request<unknown[]>("/market-data/catalog")
  return z.array(MarketCatalogRowSchema).parse(rows)
}

export async function patchAssetCategory(
  symbol: string,
  body: { asset_type: string; market_region: string | null },
): Promise<MarketCatalogRow> {
  const data = await request<unknown>(`/market-data/stocks/${encodeURIComponent(symbol)}/category`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  return MarketCatalogRowSchema.parse(data)
}

// ── MASI Ticker Registry ─────────────────────────────────────────────────────

export const MasiTickerSchema = z.object({
  symbol: z.string(),
  display_name: z.string(),
  sector: z.string(),
})
export type MasiTicker = z.infer<typeof MasiTickerSchema>

export async function fetchMasiTickers(): Promise<MasiTicker[]> {
  const rows = await request<unknown[]>("/market-data/masi-tickers")
  return z.array(MasiTickerSchema).parse(rows)
}

// ── Stock Registry API functions ──────────────────────────────────────────────

export async function listTrackedStocks(params?: { is_active?: boolean }): Promise<StockMaster[]> {
  const qs = new URLSearchParams()
  if (params?.is_active !== undefined) qs.set("is_active", String(params.is_active))
  const q = qs.toString()
  const rows = await request<unknown[]>(`/market-data/stocks${q ? `?${q}` : ""}`)
  return z.array(StockMasterSchema).parse(rows)
}

export async function addTrackedStock(body: {
  symbol: string
  isin?: string
  sector?: string
  market_cap_class?: string
  track_source?: string
  bourse_url?: string
  notes?: string
}): Promise<StockMaster> {
  const row = await request<unknown>("/market-data/stocks", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return StockMasterSchema.parse(row)
}

export async function addMacroFactor(body: {
  canonical_id: string
  yahoo_ticker: string
  display_name: string
  asset_type: string
  market_region?: string | null
  notes?: string | null
}): Promise<MacroFactor> {
  const row = await request<unknown>("/market-data/factors", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return MacroFactorSchema.parse(row)
}

export async function updateMacroFactor(
  canonical_id: string,
  body: {
    active?: boolean
    display_name?: string
    notes?: string
  }
): Promise<MacroFactor> {
  const row = await request<unknown>(`/market-data/factors/${encodeURIComponent(canonical_id)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  })
  return MacroFactorSchema.parse(row)
}

export async function updateTrackedStock(
  symbol: string,
  body: {
    isin?: string
    sector?: string
    market_cap_class?: string
    is_active?: boolean
    track_source?: string
    bourse_url?: string
    notes?: string
  }
): Promise<StockMaster> {
  const row = await request<unknown>(`/market-data/stocks/${encodeURIComponent(symbol)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  })
  return StockMasterSchema.parse(row)
}

export async function deleteMarketSymbol(symbol: string): Promise<{
  symbol: string
  deleted_tracked_stock: boolean
  deleted_canonical_data: boolean
  deleted_object_key?: string | null
}> {
  const row = await request<unknown>(`/market-data/symbols/${encodeURIComponent(symbol)}`, {
    method: "DELETE",
  })
  return row as {
    symbol: string
    deleted_tracked_stock: boolean
    deleted_canonical_data: boolean
    deleted_object_key?: string | null
  }
}

export async function bourseLookupStock(symbol: string): Promise<BourseStockLookup> {
  const row = await request<unknown>(
    `/market-data/stocks/${encodeURIComponent(symbol)}/bourse-lookup`
  )
  return BourseStockLookupSchema.parse(row)
}

export async function listStockMappings(symbol: string): Promise<ProviderSymbolMap[]> {
  const rows = await request<unknown[]>(
    `/market-data/stocks/${encodeURIComponent(symbol)}/mappings`
  )
  return z.array(ProviderSymbolMapSchema).parse(rows)
}

export async function updateStockMapping(
  symbol: string,
  provider: string,
  body: { provider_symbol: string; is_verified?: boolean; override_reason?: string }
): Promise<ProviderSymbolMap> {
  const row = await request<unknown>(
    `/market-data/stocks/${encodeURIComponent(symbol)}/mappings/${encodeURIComponent(provider)}`,
    { method: "PATCH", body: JSON.stringify(body) }
  )
  return ProviderSymbolMapSchema.parse(row)
}

export async function getStockOhlcvPreview(
  symbol: string,
  params?: { timeframe?: string; limit?: number }
): Promise<OhlcvPreview> {
  const qs = new URLSearchParams()
  if (params?.timeframe) qs.set("timeframe", params.timeframe)
  if (params?.limit !== undefined) qs.set("limit", String(params.limit))
  const q = qs.toString()
  const row = await request<unknown>(
    `/market-data/stocks/${encodeURIComponent(symbol)}/ohlcv-preview${q ? `?${q}` : ""}`
  )
  return OhlcvPreviewSchema.parse(row)
}

export async function getUploadFormatReference(): Promise<UploadFormatReference> {
  const row = await request<unknown>("/market-data/upload-format-reference")
  return UploadFormatReferenceSchema.parse(row)
}

export async function getStockOhlcvHistory(
  symbol: string,
  params?: { timeframe?: string }
): Promise<OhlcvHistory> {
  const qs = new URLSearchParams()
  if (params?.timeframe) qs.set("timeframe", params.timeframe)
  const q = qs.toString()
  const row = await request<unknown>(
    `/market-data/stocks/${encodeURIComponent(symbol)}/ohlcv-history${q ? `?${q}` : ""}`
  )
  return OhlcvHistorySchema.parse(row)
}

export async function getStockAvailabilityCalendar(
  symbol: string,
  params?: { timeframe?: string }
): Promise<AvailabilityCalendar> {
  const qs = new URLSearchParams()
  if (params?.timeframe) qs.set("timeframe", params.timeframe)
  const q = qs.toString()
  const row = await request<unknown>(
    `/market-data/stocks/${encodeURIComponent(symbol)}/availability-calendar${q ? `?${q}` : ""}`
  )
  return AvailabilityCalendarSchema.parse(row)
}

// ── OHLCV Row Mutations ──────────────────────────────────────────────────────

export interface OhlcvMutationResult {
  symbol: string
  timeframe: string
  action: string
  affected_dates: string[]
  new_row_count: number
}

export async function upsertOhlcvRow(
  symbol: string,
  body: {
    date: string
    open?: number | null
    high?: number | null
    low?: number | null
    close?: number | null
    volume?: number | null
  },
): Promise<OhlcvMutationResult> {
  return (await request<OhlcvMutationResult>(
    `/market-data/stocks/${encodeURIComponent(symbol)}/ohlcv-rows`,
    { method: "PATCH", body: JSON.stringify(body) },
  ))
}

export async function deleteOhlcvRows(
  symbol: string,
  dates: string[],
): Promise<OhlcvMutationResult> {
  return (await request<OhlcvMutationResult>(
    `/market-data/stocks/${encodeURIComponent(symbol)}/ohlcv-rows`,
    { method: "DELETE", body: JSON.stringify({ dates }) },
  ))
}

// ── Refresh API functions ─────────────────────────────────────────────────────

export async function refreshAllStocks(body?: {
  timeframe?: string
  source_override?: string
  include_unverified?: boolean
}): Promise<{ refresh_run_id: string; status: string; symbols_total: number; job_id?: string }> {
  const payload = await request<unknown>("/market-data/refresh", {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  })
  return payload as { refresh_run_id: string; status: string; symbols_total: number; job_id?: string }
}

export async function refreshSingleStock(
  symbol: string,
  body?: { timeframe?: string; source_override?: string }
): Promise<{ refresh_run_id: string; status: string; job_id?: string }> {
  const payload = await request<unknown>(
    `/market-data/stocks/${encodeURIComponent(symbol)}/refresh`,
    { method: "POST", body: JSON.stringify(body ?? {}) }
  )
  return payload as { refresh_run_id: string; status: string; job_id?: string }
}

export async function getRefreshRun(refreshRunId: string): Promise<MarketRefreshRun> {
  const row = await request<unknown>(`/market-data/refresh/${refreshRunId}`)
  return MarketRefreshRunSchema.parse(row)
}

export async function listRefreshRuns(params?: {
  limit?: number
  offset?: number
}): Promise<MarketRefreshRun[]> {
  const qs = new URLSearchParams()
  if (params?.limit !== undefined) qs.set("limit", String(params.limit))
  if (params?.offset !== undefined) qs.set("offset", String(params.offset))
  const q = qs.toString()
  const rows = await request<unknown[]>(`/market-data/refresh${q ? `?${q}` : ""}`)
  return z.array(MarketRefreshRunSchema).parse(rows)
}

export async function getMarketHealth(): Promise<MarketHealth> {
  const row = await request<unknown>("/market-data/health")
  return MarketHealthSchema.parse(row)
}

// ── Moroccan Indices API ──────────────────────────────────────────────────────

export const IndexMasterRowSchema = z.object({
  symbol: z.string(),
  display_name: z.string(),
  family: z.string().nullable().optional(),
  is_active: z.boolean(),
  source: z.string(),
  notes: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
})
export type IndexMasterRow = z.infer<typeof IndexMasterRowSchema>

export const IndicesCatalogRowSchema = z.object({
  symbol: z.string(),
  display_name: z.string().nullable().optional(),
  family: z.string().nullable().optional(),
  is_active: z.boolean().nullable().optional(),
  source: z.string().nullable().optional(),
  start_ts: z.string().nullable().optional(),
  end_ts: z.string().nullable().optional(),
  row_count: z.number().nullable().optional(),
  source_provider: z.string().nullable().optional(),
  data_as_of: z.string().nullable().optional(),
  is_stale: z.boolean().default(false),
  is_tracked: z.boolean().default(false),
  has_canonical_data: z.boolean().default(false),
})
export type IndicesCatalogRow = z.infer<typeof IndicesCatalogRowSchema>

export async function listIndicesCatalog(): Promise<IndicesCatalogRow[]> {
  const rows = await request<unknown[]>("/market-data/indices/catalog")
  return z.array(IndicesCatalogRowSchema).parse(rows)
}

export async function listIndices(): Promise<IndexMasterRow[]> {
  const rows = await request<unknown[]>("/market-data/indices")
  return z.array(IndexMasterRowSchema).parse(rows)
}

export async function uploadIndicesExcel(
  file: File
): Promise<{ dataset_id: string; job_id: string; raw_object_key: string }> {
  const form = new FormData()
  form.append("file", file)
  const payload = await request<unknown>("/market-data/indices/excel", {
    method: "POST",
    body: form,
  })
  return payload as { dataset_id: string; job_id: string; raw_object_key: string }
}

export async function getIndicesIngestStatus(
  datasetId: string
): Promise<{ status: "done" | "processing"; report?: unknown }> {
  return request<{ status: "done" | "processing"; report?: unknown }>(
    `/market-data/indices/uploads/${datasetId}/status`
  )
}

export async function refreshAllIndices(): Promise<{
  refresh_run_id: string
  status: string
  symbols_total: number
  job_id?: string
}> {
  const payload = await request<unknown>("/market-data/indices/refresh", { method: "POST" })
  return payload as { refresh_run_id: string; status: string; symbols_total: number; job_id?: string }
}

export async function getIndexOhlcvPreview(
  symbol: string,
  limit = 30
): Promise<OhlcvPreview> {
  const row = await request<unknown>(
    `/market-data/indices/${encodeURIComponent(symbol)}/ohlcv-preview?limit=${limit}`
  )
  return OhlcvPreviewSchema.parse(row)
}

export async function getIndexOhlcvHistory(symbol: string): Promise<OhlcvHistory> {
  const row = await request<unknown>(
    `/market-data/indices/${encodeURIComponent(symbol)}/ohlcv-history`
  )
  return OhlcvHistorySchema.parse(row)
}

export async function deleteIndexSymbol(symbol: string): Promise<void> {
  await request<void>(`/market-data/indices/${encodeURIComponent(symbol)}`, {
    method: "DELETE",
  })
}

export async function getIndicesRefreshRun(refreshRunId: string): Promise<MarketRefreshRun> {
  const row = await request<unknown>(`/market-data/indices/refresh/${refreshRunId}`)
  return MarketRefreshRunSchema.parse(row)
}

// ── Signal Engine — SMA Ensemble ──────────────────────────────────────────────

export const SignalRepresentativeSchema = z.object({
  variant_id: z.string(),
  signal: z.number(),
  signal_label: z.string(),
  reliability_weight: z.number(),
  normalized_weight: z.number(),
  contribution: z.number(),
  current_close: z.number(),
  indicator_value: z.number().nullable(),
  explanation: z.string(),
  description: z.string().default(""),
  params: z.record(z.unknown()).default({}),
  archetype: z.string().default(""),
  selection_status: z.string().optional(),
})
export type SignalRepresentative = z.infer<typeof SignalRepresentativeSchema>

export const MethodologyWindowSchema = z.object({
  train: z.number(),
  test: z.number(),
  step: z.number(),
  target_windows: z.number().default(0),
})
export type MethodologyWindow = z.infer<typeof MethodologyWindowSchema>

export const MethodologyContextSchema = z.object({
  methodology_mode: z.string(),
  available_bars: z.number(),
  nominal_window: MethodologyWindowSchema,
  effective_window: MethodologyWindowSchema,
  warning_message: z.string().default(""),
  is_provisional: z.boolean().default(false),
})
export type MethodologyContext = z.infer<typeof MethodologyContextSchema>

export const FamilyCombinedSignalSchema = z.object({
  family: z.string(),
  symbol: z.string(),
  horizon: z.string(),
  timeframe: z.string(),
  family_score_pct: z.number(),
  family_signal_label: z.string(),
  tested_count: z.number(),
  viable_count: z.number(),
  competitive_count: z.number(),
  representative_count: z.number(),
  representatives: z.array(SignalRepresentativeSchema),
  fallback_variants: z.array(SignalRepresentativeSchema).default([]),
  score_explanation: z.string(),
  methodology_status: z.string(),
  methodology_mode: z.string().default("robust_oos_ensemble"),
  available_bars: z.number().default(0),
  nominal_window: MethodologyWindowSchema.default({ train: 0, test: 0, step: 0, target_windows: 0 }),
  effective_window: MethodologyWindowSchema.default({ train: 0, test: 0, step: 0, target_windows: 0 }),
  warning_message: z.string().default(""),
  is_provisional: z.boolean().default(false),
  as_of: z.string(),
  latest_close: z.number().nullable().optional(),
  best_variant_id: z.string().default(""),
})
export type FamilyCombinedSignal = z.infer<typeof FamilyCombinedSignalSchema>

export const SupportResistanceMethodSchema = z.object({
  id: z.string(),
  label: z.string(),
  support: z.number().nullable().optional(),
  resistance: z.number().nullable().optional(),
  status: z.enum(["available", "ignored", "unavailable"]).default("unavailable"),
  selected_for_support: z.boolean().default(false),
  selected_for_resistance: z.boolean().default(false),
  explanation: z.string().default(""),
  inputs: z.record(z.unknown()).default({}),
})
export type SupportResistanceMethod = z.infer<typeof SupportResistanceMethodSchema>

export const SupportResistanceResponseSchema = z.object({
  symbol: z.string(),
  horizon: z.string(),
  timeframe: z.string(),
  as_of: z.string(),
  current_close: z.number(),
  trend_score_pct: z.number().nullable().optional(),
  trend_label: z.string(),
  methods: z.array(SupportResistanceMethodSchema).default([]),
  preview_support: z.number().nullable().optional(),
  preview_resistance: z.number().nullable().optional(),
  preview_support_method_id: z.string().nullable().optional(),
  preview_resistance_method_id: z.string().nullable().optional(),
  optimal_support: z.number().nullable().optional(),
  optimal_resistance: z.number().nullable().optional(),
  optimal_variant_id: z.string().nullable().optional(),
  optimal_status: z.enum(["pending", "ready", "unavailable"]).default("pending"),
  final_support: z.number().nullable().optional(),
  final_resistance: z.number().nullable().optional(),
  selected_support_method_id: z.string().nullable().optional(),
  selected_resistance_method_id: z.string().nullable().optional(),
  summary_explanation: z.string().default(""),
})
export type SupportResistanceResponse = z.infer<typeof SupportResistanceResponseSchema>

export const SupportResistanceChartBarSchema = z.object({
  date: z.string(),
  open: z.number().nullable().optional(),
  high: z.number().nullable().optional(),
  low: z.number().nullable().optional(),
  close: z.number().nullable().optional(),
  volume: z.number().nullable().optional(),
})
export type SupportResistanceChartBar = z.infer<typeof SupportResistanceChartBarSchema>

export const SupportResistanceChartSourceSchema = z.object({
  label: z.string(),
  indicator: z.object({
    type: z.string().default("overlay"),
    plot_kind: z.string().default("line"),
    plot_axis: z.string().default("price"),
    plot_values: z.array(z.number().nullable().optional()).default([]),
  }),
})
export type SupportResistanceChartSource = z.infer<typeof SupportResistanceChartSourceSchema>

export const SupportResistanceChartSchema = z.object({
  bars: z.array(SupportResistanceChartBarSchema).default([]),
  sources: z.array(SupportResistanceChartSourceSchema).default([]),
})
export type SupportResistanceChart = z.infer<typeof SupportResistanceChartSchema>

export const SupportResistanceMethodDetailResponseSchema = z.object({
  symbol: z.string(),
  horizon: z.string(),
  timeframe: z.string(),
  as_of: z.string(),
  current_close: z.number(),
  trend_score_pct: z.number().nullable().optional(),
  trend_label: z.string(),
  method_id: z.string(),
  method: SupportResistanceMethodSchema,
  chart: SupportResistanceChartSchema.nullable().optional(),
  preview_support: z.number().nullable().optional(),
  preview_resistance: z.number().nullable().optional(),
  preview_support_method_id: z.string().nullable().optional(),
  preview_resistance_method_id: z.string().nullable().optional(),
  optimal_support: z.number().nullable().optional(),
  optimal_resistance: z.number().nullable().optional(),
  optimal_variant_id: z.string().nullable().optional(),
  optimal_status: z.enum(["pending", "ready", "unavailable"]).default("pending"),
  final_support: z.number().nullable().optional(),
  final_resistance: z.number().nullable().optional(),
  selected_support_method_id: z.string().nullable().optional(),
  selected_resistance_method_id: z.string().nullable().optional(),
  summary_explanation: z.string().default(""),
})
export type SupportResistanceMethodDetailResponse = z.infer<typeof SupportResistanceMethodDetailResponseSchema>

export const IndicatorSeriesResponseSchema = z.object({
  symbol: z.string(),
  indicator: z.string(),
  params: z.record(z.number()),
  dates: z.array(z.string()),
  close: z.array(z.number().nullable().optional()),
  indicator_values: z.array(z.number().nullable().optional()),
  indicator_overlay: z.array(z.number().nullable().optional()).nullable(),
  plot_payload: z.record(z.unknown()).nullable().optional(),
  current_score: z.number(),
  current_label: z.string(),
  atr: z.number().nullable(),
})
export type IndicatorSeriesResponse = z.infer<typeof IndicatorSeriesResponseSchema>

export async function fetchSmaEnsemble(body: {
  symbol: string
  horizon: string
  timeframe?: string
  cost_bps?: number
}): Promise<FamilyCombinedSignal> {
  const payload: Record<string, unknown> = {
    symbol: body.symbol,
    horizon: body.horizon,
    timeframe: body.timeframe ?? "1D",
  }
  if (body.cost_bps != null) payload.cost_bps = body.cost_bps
  const raw = await request<unknown>("/strategy/signal/sma-ensemble", {
    method: "POST",
    body: JSON.stringify(payload),
  })
  return FamilyCombinedSignalSchema.parse(raw)
}

export async function fetchFamilyEnsemble(body: {
  family: string
  symbol: string
  horizon: string
  timeframe?: string
  cost_bps?: number
  cooldown_bars?: number
  variant?: string
}): Promise<FamilyCombinedSignal> {
  const payload: Record<string, unknown> = {
    family: body.family,
    symbol: body.symbol,
    horizon: body.horizon,
    timeframe: body.timeframe ?? "1D",
    variant: body.variant ?? "expanded",
  }
  if (body.cost_bps != null) payload.cost_bps = body.cost_bps
  if (body.cooldown_bars != null) payload.cooldown_bars = body.cooldown_bars
  const raw = await request<unknown>("/strategy/signal/family-ensemble", {
    method: "POST",
    body: JSON.stringify(payload),
  })
  return FamilyCombinedSignalSchema.parse(raw)
}

export async function fetchSupportResistance(body: {
  symbol: string
  horizon: string
  timeframe?: string
  cost_bps?: number
  cooldown_bars?: number
  variant?: string
}): Promise<SupportResistanceResponse> {
  const payload: Record<string, unknown> = {
    symbol: body.symbol,
    horizon: body.horizon,
    timeframe: body.timeframe ?? "1D",
    variant: body.variant ?? "expanded",
  }
  if (body.cost_bps != null) payload.cost_bps = body.cost_bps
  if (body.cooldown_bars != null) payload.cooldown_bars = body.cooldown_bars
  const raw = await request<unknown>("/strategy/signal/support-resistance", {
    method: "POST",
    body: JSON.stringify(payload),
  })
  return SupportResistanceResponseSchema.parse(raw)
}

export async function fetchSupportResistanceMethodDetail(body: {
  symbol: string
  horizon: string
  method_id: string
  timeframe?: string
  cost_bps?: number
  cooldown_bars?: number
  variant?: string
}): Promise<SupportResistanceMethodDetailResponse> {
  const payload: Record<string, unknown> = {
    symbol: body.symbol,
    horizon: body.horizon,
    method_id: body.method_id,
    timeframe: body.timeframe ?? "1D",
    variant: body.variant ?? "expanded",
  }
  if (body.cost_bps != null) payload.cost_bps = body.cost_bps
  if (body.cooldown_bars != null) payload.cooldown_bars = body.cooldown_bars
  const raw = await request<unknown>("/strategy/signal/support-resistance/method-detail", {
    method: "POST",
    body: JSON.stringify(payload),
  })
  return SupportResistanceMethodDetailResponseSchema.parse(raw)
}

export async function fetchIndicatorSeries(body: {
  symbol: string
  indicator: string
  params: Record<string, number>
  timeframe?: string
}): Promise<IndicatorSeriesResponse> {
  const payload: Record<string, unknown> = {
    symbol: body.symbol,
    indicator: body.indicator,
    params: body.params,
    timeframe: body.timeframe ?? "1D",
  }
  const raw = await request<unknown>("/strategy/signal/indicator-series", {
    method: "POST",
    body: JSON.stringify(payload),
  })
  return IndicatorSeriesResponseSchema.parse(raw)
}

// ── Signal Engine — Variant Detail ──────────────────────────────────────────

export const VariantRobustnessSchema = z.object({
  mean_sharpe: z.number(),
  std_sharpe: z.number(),
  median_sharpe: z.number(),
  fraction_positive_windows: z.number(),
  mean_max_drawdown: z.number(),
  reliability_score: z.number(),
  is_viable: z.boolean(),
  sharpe_score: z.number(),
  stability_score: z.number(),
  consistency_score: z.number(),
  drawdown_score: z.number(),
  total_pnl_100k: z.number().default(0),
  total_pnl_realise_1u: z.number().default(0),
})
export type VariantRobustness = z.infer<typeof VariantRobustnessSchema>

export const OOSWindowSchema = z.object({
  window_index: z.number(),
  train_start: z.number(),
  train_end: z.number(),
  test_start: z.number(),
  test_end: z.number(),
  test_start_date: z.string().optional(),
  test_end_date: z.string().optional(),
  n_trades: z.number(),
  mean_return_net: z.number(),
  sharpe: z.number(),
  max_drawdown: z.number(),
  fraction_positive_bars: z.number(),
  n_bars: z.number(),
  is_valid: z.boolean(),
})
export type OOSWindow = z.infer<typeof OOSWindowSchema>

export const VariantSummarySchema = z.object({
  variant_id: z.string(),
  archetype: z.string(),
  params: z.record(z.unknown()),
  description: z.string(),
  reliability_score: z.number(),
  is_viable: z.boolean(),
  is_survivor: z.boolean(),
  is_representative: z.boolean(),
  elimination_reason: z.string(),
  mean_sharpe: z.number().default(0),
  mean_max_drawdown: z.number().default(0),
  fraction_positive_windows: z.number().default(0),
  cagr: z.number().default(0),
  total_pnl: z.number().default(0),
  total_pnl_100k: z.number().default(0),
  total_pnl_realise_1u: z.number().default(0),
  signal_value: z.number().default(0),
  signal_label: z.string().optional(),
  correlated_with: z.string().nullable().optional(),
  correlated_with_label: z.string().nullable().optional(),
  correlation: z.number().nullable().optional(),
  threshold_score: z.number().nullable().optional(),
  viability_detail: z.string().nullable().optional(),
  selection_status: z.string().optional(),
  sr_objective_score: z.number().optional(),
  net_return_score: z.number().optional(),
  consistency_score: z.number().optional(),
  drawdown_score: z.number().optional(),
  trade_activity_score: z.number().optional(),
  support_level: z.number().nullable().optional(),
  resistance_level: z.number().nullable().optional(),
  support_method_id: z.string().optional(),
  resistance_method_id: z.string().optional(),
})
export type VariantSummary = z.infer<typeof VariantSummarySchema>

export const FunnelSchema = z.object({
  tested: z.number(),
  viable: z.number(),
  competitive: z.number(),
  representative: z.number(),
})

export const VariantDetailSchema = z.object({
  variant_id: z.string(),
  archetype: z.string(),
  params: z.record(z.unknown()),
  description: z.string(),
  signal: z.number(),
  signal_label: z.string(),
  selection_status: z.string().default("not_viable"),
  robustness: VariantRobustnessSchema,
  oos_windows: z.array(OOSWindowSchema),
  all_variants: z.array(VariantSummarySchema),
  fallback_variants: z.array(SignalRepresentativeSchema).default([]),
  funnel: FunnelSchema,
  correlation_matrix: z.unknown().optional(),
  methodology_context: MethodologyContextSchema,
})
export type VariantDetail = z.infer<typeof VariantDetailSchema>

export const SupportResistanceVariantsResponseSchema = z.object({
  family: z.string().default("support_resistance"),
  symbol: z.string(),
  horizon: z.string(),
  timeframe: z.string(),
  as_of: z.string(),
  current_close: z.number().nullable().optional(),
  trend_score_pct: z.number().nullable().optional(),
  trend_label: z.string().default(""),
  methods: z.array(SupportResistanceMethodSchema).default([]),
  preview_support: z.number().nullable().optional(),
  preview_resistance: z.number().nullable().optional(),
  preview_support_method_id: z.string().nullable().optional(),
  preview_resistance_method_id: z.string().nullable().optional(),
  optimal_support: z.number().nullable().optional(),
  optimal_resistance: z.number().nullable().optional(),
  optimal_variant_id: z.string().nullable().optional(),
  optimal_status: z.enum(["pending", "ready", "unavailable"]).default("pending"),
  final_support: z.number().nullable().optional(),
  final_resistance: z.number().nullable().optional(),
  selected_support_method_id: z.string().nullable().optional(),
  selected_resistance_method_id: z.string().nullable().optional(),
  best_variant_id: z.string().nullable().optional(),
  funnel: FunnelSchema,
  tested_count: z.number().default(0),
  viable_count: z.number().default(0),
  competitive_count: z.number().default(0),
  representative_count: z.number().default(0),
  competitive_threshold: z.number().nullable().optional(),
  representatives: z.array(VariantSummarySchema).default([]),
  all_variants: z.array(VariantSummarySchema).default([]),
  score_explanation: z.string().default(""),
  methodology_context: MethodologyContextSchema.optional(),
})
export type SupportResistanceVariantsResponse = z.infer<typeof SupportResistanceVariantsResponseSchema>

export async function fetchVariantDetail(body: {
  symbol: string
  horizon: string
  timeframe?: string
  variant_id: string
  cost_bps?: number
  cooldown_bars?: number
  variant?: string
}): Promise<VariantDetail> {
  const payload: Record<string, unknown> = {
    symbol: body.symbol,
    horizon: body.horizon,
    timeframe: body.timeframe ?? "1D",
    variant_id: body.variant_id,
    variant: body.variant ?? "expanded",
  }
  if (body.cost_bps != null) payload.cost_bps = body.cost_bps
  if (body.cooldown_bars != null) payload.cooldown_bars = body.cooldown_bars
  const raw = await request<unknown>("/strategy/signal/variant-detail", {
    method: "POST",
    body: JSON.stringify(payload),
  })
  return VariantDetailSchema.parse(raw)
}

export async function fetchSupportResistanceVariants(body: {
  symbol: string
  horizon: string
  timeframe?: string
  cost_bps?: number
  cooldown_bars?: number
  variant?: string
}): Promise<SupportResistanceVariantsResponse> {
  const payload: Record<string, unknown> = {
    symbol: body.symbol,
    horizon: body.horizon,
    timeframe: body.timeframe ?? "1D",
    variant: body.variant ?? "expanded",
  }
  if (body.cost_bps != null) payload.cost_bps = body.cost_bps
  if (body.cooldown_bars != null) payload.cooldown_bars = body.cooldown_bars
  const raw = await request<unknown>("/strategy/signal/support-resistance/variants", {
    method: "POST",
    body: JSON.stringify(payload),
  })
  return SupportResistanceVariantsResponseSchema.parse(raw)
}

export async function fetchSupportResistanceVariantDetail(body: {
  symbol: string
  horizon: string
  timeframe?: string
  variant_id: string
  cost_bps?: number
  cooldown_bars?: number
  variant?: string
}): Promise<VariantDetail> {
  const payload: Record<string, unknown> = {
    symbol: body.symbol,
    horizon: body.horizon,
    timeframe: body.timeframe ?? "1D",
    variant_id: body.variant_id,
    variant: body.variant ?? "expanded",
  }
  if (body.cost_bps != null) payload.cost_bps = body.cost_bps
  if (body.cooldown_bars != null) payload.cooldown_bars = body.cooldown_bars
  const raw = await request<unknown>("/strategy/signal/support-resistance/variant-detail", {
    method: "POST",
    body: JSON.stringify(payload),
  })
  return VariantDetailSchema.parse(raw)
}

// Per-window detail (for OOS drill-down)
export const PerWindowDetailSchema = z.object({
  window_index: z.number(),
  start_date: z.string(),
  end_date: z.string(),
  sharpe: z.number(),
  pnl: z.number(),
  n_trades: z.number(),
  is_valid: z.boolean(),
  plot: PlotlyFigureSchema,
  equity_plot: PlotlyFigureSchema.optional(),
  drawdown_plot: PlotlyFigureSchema.optional(),
  trades: z.array(z.record(z.unknown())),
})
export type PerWindowDetail = z.infer<typeof PerWindowDetailSchema>

// Variant backtest types
export const VariantBacktestSchema = z.object({
  variant_id: z.string(),
  description: z.string(),
  metrics: z.record(z.unknown()).default({}),
  trade_performance: z.array(z.record(z.unknown())).default([]),
  trade_ledger: z.array(z.record(z.unknown())).default([]),
  plots: z.record(PlotlyFigureSchema).default({}),
  per_window: z.array(PerWindowDetailSchema).default([]),
  methodology_context: MethodologyContextSchema.optional(),
  warning_message: z.string().default(""),
})
export type VariantBacktest = z.infer<typeof VariantBacktestSchema>

export async function fetchVariantBacktest(body: {
  symbol: string
  variant_id: string
  horizon?: string
  timeframe?: string
  cost_bps?: number
  cooldown_bars?: number
  variant?: string
}): Promise<VariantBacktest> {
  const payload: Record<string, unknown> = {
    symbol: body.symbol,
    variant_id: body.variant_id,
    horizon: body.horizon ?? "medium",
    timeframe: body.timeframe ?? "1D",
    variant: body.variant ?? "expanded",
  }
  if (body.cost_bps != null) payload.cost_bps = body.cost_bps
  if (body.cooldown_bars != null) payload.cooldown_bars = body.cooldown_bars
  const raw = await request<unknown>("/strategy/signal/variant-backtest", {
    method: "POST",
    body: JSON.stringify(payload),
  })
  return VariantBacktestSchema.parse(raw)
}

export async function fetchSupportResistanceVariantBacktest(body: {
  symbol: string
  variant_id: string
  horizon?: string
  timeframe?: string
  cost_bps?: number
  cooldown_bars?: number
  variant?: string
}): Promise<VariantBacktest> {
  const payload: Record<string, unknown> = {
    symbol: body.symbol,
    variant_id: body.variant_id,
    horizon: body.horizon ?? "medium",
    timeframe: body.timeframe ?? "1D",
    variant: body.variant ?? "expanded",
  }
  if (body.cost_bps != null) payload.cost_bps = body.cost_bps
  if (body.cooldown_bars != null) payload.cooldown_bars = body.cooldown_bars
  const raw = await request<unknown>("/strategy/signal/support-resistance/variant-backtest", {
    method: "POST",
    body: JSON.stringify(payload),
  })
  return VariantBacktestSchema.parse(raw)
}

// ── Signal Engine — Batch Scores ────────────────────────────────────────────

export const BatchScoreSchema = z.object({
  symbol: z.string(),
  aggregate_score_pct: z.number().nullable(),
  aggregate_signal_label: z.string().nullable(),
})
export type BatchScore = z.infer<typeof BatchScoreSchema>

export async function fetchBatchScores(body: {
  symbols: string[]
  horizon: string
  cost_bps?: number
  cooldown_bars?: number
  variant?: string
}): Promise<BatchScore[]> {
  const raw = await request<unknown[]>("/strategy/signal/batch-scores", {
    method: "POST",
    body: JSON.stringify({
      symbols: body.symbols,
      horizon: body.horizon,
      cost_bps: body.cost_bps ?? 10,
      cooldown_bars: body.cooldown_bars ?? 0,
      variant: body.variant ?? "expanded",
    }),
  })
  return z.array(BatchScoreSchema).parse(raw)
}

export const PersistedSignalEngineSummarySchema = z.object({
  symbol: z.string(),
  aggregate_score_pct: z.number().nullable(),
  aggregate_signal_label: z.string().nullable(),
  data_as_of: z.string().nullable().optional(),
  market_data_as_of: z.string().nullable().optional(),
  computed_at: z.string().nullable().optional(),
  is_stale: z.boolean().default(false),
})
export type PersistedSignalEngineSummary = z.infer<typeof PersistedSignalEngineSummarySchema>

export async function fetchPersistedSignalEngineSummaries(body: {
  symbols: string[]
  horizon: string
  variant?: string
  timeframe?: string
}): Promise<PersistedSignalEngineSummary[]> {
  const raw = await request<unknown[]>("/strategy/engine/persisted-summaries", {
    method: "POST",
    body: JSON.stringify({
      symbols: body.symbols,
      horizon: body.horizon,
      variant: body.variant ?? "expanded",
      timeframe: body.timeframe ?? "1D",
    }),
  })
  return z.array(PersistedSignalEngineSummarySchema).parse(raw)
}

// ── Signal Engine — Regime Consensus (Layer H) ──────────────────────────────

export const RegimeWindowResultSchema = z.object({
  train_start: z.number(),
  train_end: z.number(),
  test_start: z.number(),
  test_end: z.number(),
  train_start_date: z.string().optional(),
  train_end_date: z.string().optional(),
  test_start_date: z.string().optional(),
  test_end_date: z.string().optional(),
  er_low: z.number(),
  er_high: z.number(),
  regime_sharpe: z.number(),
  equal_sharpe: z.number(),
  delta: z.number(),
  trending_weights: z.record(z.number()),
  ranging_weights: z.record(z.number()),
})
export type RegimeWindowResult = z.infer<typeof RegimeWindowResultSchema>

export const RegimeTopVariantSchema = z.object({
  variant_id: z.string(),
  archetype: z.string(),
  params: z.record(z.unknown()),
  reliability_score: z.number(),
  label: z.string(),
})
export type RegimeTopVariant = z.infer<typeof RegimeTopVariantSchema>

export const RegimeConsensusSchema = z.object({
  symbol: z.string(),
  final_consensus: z.number().nullable(),
  family_weights: z.record(z.number()),
  per_family: z.record(
    z.object({ score_pct: z.number(), weight: z.number() })
  ),
  regime_active: z.boolean(),
  regime_label: z.string(),
  er_value: z.number().nullable(),
  improvement: z.number(),
  tercile_bounds: z.array(z.number()),
  equal_consensus: z.number().nullable(),
  n_families: z.number(),
  window_results: z.array(RegimeWindowResultSchema),
  n_folds: z.number(),
  folds_regime_wins: z.number(),
  top_variants: z.record(RegimeTopVariantSchema),
})
export type RegimeConsensus = z.infer<typeof RegimeConsensusSchema>

export async function fetchRegimeConsensus(body: {
  symbol: string
  horizon: string
  timeframe?: string
  cost_bps?: number
  cooldown_bars?: number
  variant?: string
}): Promise<RegimeConsensus> {
  const raw = await request<unknown>("/strategy/signal/regime-consensus", {
    method: "POST",
    body: JSON.stringify({
      symbol: body.symbol,
      horizon: body.horizon,
      timeframe: body.timeframe ?? "1D",
      cost_bps: body.cost_bps ?? 10,
      cooldown_bars: body.cooldown_bars ?? 0,
      variant: body.variant ?? "expanded",
    }),
  })
  return RegimeConsensusSchema.parse(raw)
}

// ── Strategy Plan — Universe ──────────────────────────────────────────────────

export const UniverseStockSchema = z.object({
  symbol: z.string(),
  display_name: z.string().nullable().optional(),
  sector: z.string().nullable().optional(),
  market_cap_class: z.string().nullable().optional(),
  row_count: z.number().nullable().optional(),
  data_as_of: z.string().nullable().optional(),
  adv20: z.number().nullable().optional(),
  signal_score: z.number().nullable(),
  signal_label: z.string().nullable().optional(),
  per_family: z.record(z.unknown()).nullable().optional(),
  eligible: z.boolean(),
  exclusion_reason: z.string().nullable().optional(),
})
export type UniverseStock = z.infer<typeof UniverseStockSchema>

export async function fetchUniverse(body: {
  horizon: string
  timeframe?: string
  cost_bps?: number
  cooldown_bars?: number
  min_bars?: number
  min_abs_signal?: number
  min_adv20?: number
  sector_filter?: string[]
  sort_by?: "adv20" | "signal_score"
  sort_dir?: "asc" | "desc"
}): Promise<UniverseStock[]> {
  const payload: Record<string, unknown> = {
    horizon: body.horizon,
  }
  if (body.timeframe != null) payload.timeframe = body.timeframe
  if (body.cost_bps != null) payload.cost_bps = body.cost_bps
  if (body.cooldown_bars != null) payload.cooldown_bars = body.cooldown_bars
  if (body.min_bars != null) payload.min_bars = body.min_bars
  if (body.min_abs_signal != null) payload.min_abs_signal = body.min_abs_signal
  if (body.min_adv20 != null) payload.min_adv20 = body.min_adv20
  if (body.sector_filter != null) payload.sector_filter = body.sector_filter
  if (body.sort_by != null) payload.sort_by = body.sort_by
  if (body.sort_dir != null) payload.sort_dir = body.sort_dir

  const raw = await request<unknown[]>("/strategy/plan/universe", {
    method: "POST",
    body: JSON.stringify(payload),
  })
  return z.array(UniverseStockSchema).parse(raw)
}

export const StrategyAllocationRowSchema = z.object({
  symbol: z.string(),
  source: z.string().default("hrp"),
  hrp_weight_pct: z.number().default(0),
  weight_pct: z.number().default(0),
  capital_mad: z.number().default(0),
})
export type StrategyAllocationRow = z.infer<typeof StrategyAllocationRowSchema>

export const StrategyAllocationSchema = z.object({
  rows: z.array(StrategyAllocationRowSchema).default([]),
  total_capital_mad: z.number().default(0),
  allocated_capital_mad: z.number().default(0),
  remaining_capital_mad: z.number().default(0),
  explain: z.string().default(""),
})
export type StrategyAllocation = z.infer<typeof StrategyAllocationSchema>

export async function fetchStrategyAllocation(body: {
  symbols: string[]
  total_capital_mad: number
  method?: "hrp"
  timeframe?: string
  lookback_bars?: number
  manual_overrides_by_symbol?: Record<string, number>
}): Promise<StrategyAllocation> {
  const raw = await request<unknown>("/strategy/plan/allocation", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return StrategyAllocationSchema.parse(raw)
}

// ── Strategy Plan — Levels (S/R + ATR + Pivot) ───────────────────────────────

export const SRLevelSchema = z.object({
  price: z.number(),
  bar_index: z.number(),
  date: z.string().nullable().optional(),
  strength: z.number().default(0),
})
export type SRLevel = z.infer<typeof SRLevelSchema>

export const PivotPointsSchema = z.object({
  pp: z.number(),
  s1: z.number(),
  s2: z.number(),
  r1: z.number(),
  r2: z.number(),
})
export type PivotPoints = z.infer<typeof PivotPointsSchema>

export const LevelsResultSchema = z.object({
  symbol: z.string(),
  current_close: z.number(),
  atr_14: z.number().nullable().optional(),
  atr_pct: z.number().nullable().optional(),
  supports: z.array(SRLevelSchema).default([]),
  resistances: z.array(SRLevelSchema).default([]),
  nearest_support: z.number().nullable().optional(),
  nearest_resistance: z.number().nullable().optional(),
  pivot: PivotPointsSchema.nullable().optional(),
  explain: z.string().default(""),
})
export type LevelsResult = z.infer<typeof LevelsResultSchema>

export async function fetchLevels(body: {
  symbol: string
  horizon?: string
  timeframe?: string
  execution_holding_bars?: number
  left_bars?: number
  right_bars?: number
  lookback?: number
  max_levels?: number
}): Promise<LevelsResult> {
  const payload: Record<string, unknown> = {
    symbol: body.symbol,
  }
  if (body.horizon != null) payload.horizon = body.horizon
  if (body.timeframe != null) payload.timeframe = body.timeframe
  if (body.execution_holding_bars != null) payload.execution_holding_bars = body.execution_holding_bars
  if (body.left_bars != null) payload.left_bars = body.left_bars
  if (body.right_bars != null) payload.right_bars = body.right_bars
  if (body.lookback != null) payload.lookback = body.lookback
  if (body.max_levels != null) payload.max_levels = body.max_levels

  const raw = await request<unknown>("/strategy/plan/levels", {
    method: "POST",
    body: JSON.stringify(payload),
  })
  return LevelsResultSchema.parse(raw)
}


// ---------------------------------------------------------------------------
// Saved Strategy CRUD
// ---------------------------------------------------------------------------

export const SavedStrategyListItemSchema = z.object({
  id: z.string(),
  name: z.string(),
  status: z.string(),
  side_policy: z.string(),
  horizon: z.string(),
  basket_count: z.number().default(0),
  updated_at: z.string(),
})
export type SavedStrategyListItem = z.infer<typeof SavedStrategyListItemSchema>

export const SavedStrategySchema = z.object({
  id: z.string(),
  name: z.string(),
  note: z.string().nullable().optional(),
  status: z.string(),
  side_policy: z.string(),
  horizon: z.string(),
  config_json: z.record(z.unknown()).default({}),
  created_at: z.string(),
  updated_at: z.string(),
})
export type SavedStrategy = z.infer<typeof SavedStrategySchema>

export async function fetchStrategies(status?: string): Promise<SavedStrategyListItem[]> {
  const qs = status ? `?status=${status}` : ""
  const raw = await request<unknown>(`/strategy/plan/strategies${qs}`)
  return z.array(SavedStrategyListItemSchema).parse(raw)
}

export async function fetchStrategy(id: string): Promise<SavedStrategy> {
  const raw = await request<unknown>(`/strategy/plan/strategies/${id}`)
  return SavedStrategySchema.parse(raw)
}

export const DashboardCustomIndexSchema = z.object({
  id: z.string(),
  name: z.string(),
  symbols: z.array(z.string()).default([]),
  created_at: z.string(),
  updated_at: z.string(),
})
export type DashboardCustomIndex = z.infer<typeof DashboardCustomIndexSchema>

export const ReviewStockReadinessSchema = z.object({
  symbol: z.string(),
  has_signal: z.boolean().default(false),
  has_entry_rules: z.boolean().default(false),
  has_exit_rules: z.boolean().default(false),
  has_risk: z.boolean().default(false),
  wfo_param_count: z.number().default(0),
  ready: z.boolean().default(false),
  warnings: z.array(z.string()).default([]),
  blocking_issues: z.array(z.string()).default([]),
})
export type ReviewStockReadiness = z.infer<typeof ReviewStockReadinessSchema>

export const StrategyReviewSchema = z.object({
  total_wfo_param_count: z.number().default(0),
  wfo_param_severity: z.string().default("ok"),
  pardo_df_ok: z.boolean().default(true),
  pardo_df_message: z.string().default(""),
  stocks: z.array(ReviewStockReadinessSchema).default([]),
  global_warnings: z.array(z.string()).default([]),
  blocking_issues: z.array(z.string()).default([]),
  ready: z.boolean().default(false),
})
export type StrategyReview = z.infer<typeof StrategyReviewSchema>

export const WfoParamManifestEntrySchema = z.object({
  stock: z.string(),
  section: z.string(),
  param_path: z.string(),
  scan_min: z.number(),
  scan_max: z.number(),
  scan_step: z.number(),
})
export type WfoParamManifestEntry = z.infer<typeof WfoParamManifestEntrySchema>

export const StrategyHandoffSchema = z.object({
  strategy_id: z.string(),
  strategy_name: z.string(),
  portfolio: z.record(z.unknown()).default({}),
  stocks: z.record(z.unknown()).default({}),
  wfo_params: z.object({
    params: z.array(WfoParamManifestEntrySchema).default([]),
  }).default({ params: [] }),
  total_wfo_param_count: z.number().default(0),
  warnings: z.array(z.string()).default([]),
  ready: z.boolean().default(false),
  blocking_issues: z.array(z.string()).default([]),
  schema_version: z.number().default(3),
  app_domain: z.string().default("four_pages"),
})
export type StrategyHandoff = z.infer<typeof StrategyHandoffSchema>

export const ActiveScoreChipSchema = z.object({
  score_key: z.string(),
  label: z.string(),
  family: z.string(),
  source_kind: z.string(),
  score: z.number().nullable().optional(),
  signal_label: z.string().nullable().optional(),
})
export type ActiveScoreChip = z.infer<typeof ActiveScoreChipSchema>

const PreviewZoneRepSchema = z.object({
  variant_id: z.string().optional(),
  weight: z.number().default(0),
  label: z.string().default(""),
  indicator: z.record(z.string(), z.any()).nullable().optional(),
})

const ConstructedSignalSourceSchema = z.object({
  score_key: z.string(),
  label: z.string(),
  family: z.string(),
  source_kind: z.string(),
  source_mode_label: z.string().default(""),
  scores: z.array(z.number()).default([]),
  representatives: z.array(PreviewZoneRepSchema).default([]),
  indicator: z.record(z.any()).nullable().optional(),
  wfo_start_indicator: z.record(z.any()).nullable().optional(),
  wfo_end_indicator: z.record(z.any()).nullable().optional(),
  wfo_param_names: z.array(z.string()).default([]),
  wfo_range_active: z.boolean().default(false),
})

export const ConstructedSignalChartSchema = z.object({
  symbol: z.string(),
  horizon: z.string(),
  bars: z.array(OhlcvBarSchema),
  sources: z.array(ConstructedSignalSourceSchema).default([]),
})
export type ConstructedSignalChart = z.infer<typeof ConstructedSignalChartSchema>

export const SignalConstructionPreviewSchema = z.object({
  active_scores: z.array(ActiveScoreChipSchema).default([]),
  score_snapshot: z.record(z.number().nullable()).default({}),
  variable_catalog: z.array(z.record(z.string())).default([]),
  zone_chart: ConstructedSignalChartSchema.default({ symbol: "", horizon: "", bars: [], sources: [] }),
  explain: z.string().default(""),
})
export type SignalConstructionPreview = z.infer<typeof SignalConstructionPreviewSchema>

export const RulePreviewRowSchema = z.object({
  id: z.string(),
  label: z.string(),
  config_option: z.string().default("A"),
  condition_count: z.number().default(0),
  triggered: z.boolean().default(false),
  conditions: z.array(z.string()).default([]),
})
export type RulePreviewRow = z.infer<typeof RulePreviewRowSchema>

export const RulePreviewSchema = z.object({
  symbol: z.string(),
  score_snapshot: z.record(z.number().nullable()).default({}),
  rules: z.array(RulePreviewRowSchema).default([]),
  explain: z.string().default(""),
})
export type RulePreview = z.infer<typeof RulePreviewSchema>

export const RiskPreviewSchema = z.object({
  symbol: z.string(),
  current_close: z.number().nullable().optional(),
  atr_14: z.number().nullable().optional(),
  stop_loss: z.number().nullable().optional(),
  take_profit: z.number().nullable().optional(),
  rr_ratio: z.number().nullable().optional(),
  cooldown_bars: z.number().default(0),
  time_stop_bars: z.number().nullable().optional(),
  explain: z.string().default(""),
})
export type RiskPreview = z.infer<typeof RiskPreviewSchema>

export type FamilyHistoryMode = "static_current_reps" | "dynamic_point_in_time"

export async function fetchStrategyReview(body: {
  config_json?: Record<string, unknown>
  horizon?: string
}): Promise<StrategyReview> {
  const raw = await request<unknown>("/strategy/plan/review", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return StrategyReviewSchema.parse(raw)
}

export async function fetchStrategyHandoff(strategyId: string): Promise<StrategyHandoff> {
  const raw = await request<unknown>(`/strategy/plan/strategies/${strategyId}/handoff`, {
    method: "POST",
  })
  return StrategyHandoffSchema.parse(raw)
}

export async function fetchSignalConstructionPreview(body: {
  symbol: string
  horizon?: string
  timeframe?: string
  stock_config?: Record<string, unknown>
  cost_bps?: number
  cooldown_bars?: number
  family_history_mode?: FamilyHistoryMode
}): Promise<SignalConstructionPreview> {
  const raw = await request<unknown>("/strategy/plan/signal-construction/preview", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return SignalConstructionPreviewSchema.parse(raw)
}

export async function fetchEntryRulesPreview(body: {
  symbol: string
  horizon?: string
  timeframe?: string
  stock_config?: Record<string, unknown>
  cost_bps?: number
  cooldown_bars?: number
}): Promise<RulePreview> {
  const raw = await request<unknown>("/strategy/plan/entry-rules/preview", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return RulePreviewSchema.parse(raw)
}

export async function fetchExitRulesPreview(body: {
  symbol: string
  horizon?: string
  timeframe?: string
  stock_config?: Record<string, unknown>
  cost_bps?: number
  cooldown_bars?: number
}): Promise<RulePreview> {
  const raw = await request<unknown>("/strategy/plan/exit-rules/preview", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return RulePreviewSchema.parse(raw)
}

export async function fetchRiskPreview(body: {
  symbol: string
  horizon?: string
  timeframe?: string
  stock_config?: Record<string, unknown>
  cost_bps?: number
  cooldown_bars?: number
}): Promise<RiskPreview> {
  const raw = await request<unknown>("/strategy/plan/risk/preview", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return RiskPreviewSchema.parse(raw)
}

export const StrategyBacktestRunStockSummarySchema = z.object({
  symbol: z.string(),
  status: z.string().default("queued"),
  summary: z.record(z.unknown()).default({}),
  error_text: z.string().nullable().optional(),
})
export type StrategyBacktestRunStockSummary = z.infer<typeof StrategyBacktestRunStockSummarySchema>

export const StrategyBacktestRunSchema = z.object({
  run_id: z.string(),
  title: z.string(),
  strategy_id: z.string(),
  strategy_name: z.string(),
  mode: z.string().default("direct"),
  status: z.string().default("queued"),
  horizon: z.string().default("medium"),
  strategy_snapshot: z.record(z.unknown()).default({}),
  data_snapshot: z.record(z.unknown()).default({}),
  request: z.record(z.unknown()).default({}),
  summary: z.record(z.unknown()).default({}),
  result: z.record(z.unknown()).default({}),
  progress: z.record(z.unknown()).default({}),
  stocks: z.array(StrategyBacktestRunStockSummarySchema).default([]),
  error_text: z.string().nullable().optional(),
  created_at: z.string(),
  started_at: z.string().nullable().optional(),
  completed_at: z.string().nullable().optional(),
})
export type StrategyBacktestRun = z.infer<typeof StrategyBacktestRunSchema>

export const StrategyBacktestRunCreateSchema = z.object({
  run_id: z.string(),
  status: z.string(),
  mode: z.string(),
  title: z.string(),
  reused: z.boolean().default(false),
})
export type StrategyBacktestRunCreate = z.infer<typeof StrategyBacktestRunCreateSchema>

export const StrategyBacktestRunListItemSchema = z.object({
  run_id: z.string(),
  title: z.string(),
  strategy_id: z.string(),
  strategy_name: z.string(),
  mode: z.string().default("direct"),
  status: z.string().default("queued"),
  horizon: z.string().default("medium"),
  start_date: z.string().nullable().optional(),
  end_date: z.string().nullable().optional(),
  basket_count: z.number().default(0),
  summary: z.record(z.unknown()).default({}),
  created_at: z.string(),
  completed_at: z.string().nullable().optional(),
})
export type StrategyBacktestRunListItem = z.infer<typeof StrategyBacktestRunListItemSchema>

export const StrategyBacktestStockDetailSchema = z.object({
  run_id: z.string(),
  symbol: z.string(),
  status: z.string(),
  summary: z.record(z.unknown()).default({}),
  result: z.record(z.unknown()).default({}),
  error_text: z.string().nullable().optional(),
})
export type StrategyBacktestStockDetail = z.infer<typeof StrategyBacktestStockDetailSchema>

export async function createStrategyBacktestRun(body: {
  strategy_id: string
  mode?: "direct" | "wfo"
  start_date?: string | null
  end_date?: string | null
  timeframe?: string
  family_history_mode?: FamilyHistoryMode
  cost_model: {
    brokerage_bps: number
    comm_bourse_bps: number
    reg_liv_bps: number
    slippage_bps: number
    tva_rate: number
  }
  volume_gate: {
    enabled: boolean
    kind: "min_abs" | "min_ratio_adv"
    min_volume_abs: number
    min_volume_ratio_adv: number
    adv_window: number
  }
  cooldown_bars: number
  wfo_config?: {
    window_policy?: "strict_fold_driven" | "legacy_ratio_scan"
    top_k_folds?: number
    strict_fallback_enabled?: boolean
    strict_fallback_floor?: number
    is_oos_ratios?: number[]
    min_walk_forwards?: number
    test_period_start?: string | null
    test_period_end?: string | null
    n_monte_carlo_paths?: number
    monte_carlo_block_length?: number | null
  }
}): Promise<StrategyBacktestRunCreate> {
  const raw = await request<unknown>("/backtest/strategy-runs", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return StrategyBacktestRunCreateSchema.parse(raw)
}

export async function fetchStrategyBacktestRun(runId: string): Promise<StrategyBacktestRun> {
  const raw = await request<unknown>(`/backtest/strategy-runs/${runId}`)
  return StrategyBacktestRunSchema.parse(raw)
}

export async function cancelStrategyBacktestRun(runId: string): Promise<StrategyBacktestRun> {
  const raw = await request<unknown>(`/backtest/strategy-runs/${runId}/cancel`, {
    method: "POST",
  })
  return StrategyBacktestRunSchema.parse(raw)
}

export async function fetchStrategyBacktestRuns(params?: {
  strategy_id?: string | null
  status?: string | null
  mode?: string | null
  q?: string | null
  limit?: number | null
}): Promise<StrategyBacktestRunListItem[]> {
  const qs = new URLSearchParams()
  if (params?.strategy_id) qs.set("strategy_id", params.strategy_id)
  if (params?.status) qs.set("status", params.status)
  if (params?.mode) qs.set("mode", params.mode)
  if (params?.q) qs.set("q", params.q)
  if (params?.limit != null) qs.set("limit", String(params.limit))
  const raw = await request<unknown>(`/backtest/strategy-runs${qs.toString() ? `?${qs.toString()}` : ""}`)
  return z.array(StrategyBacktestRunListItemSchema).parse(raw)
}

export async function fetchStrategyBacktestStockDetail(runId: string, symbol: string): Promise<StrategyBacktestStockDetail> {
  const raw = await request<unknown>(`/backtest/strategy-runs/${runId}/stocks/${encodeURIComponent(symbol)}`)
  return StrategyBacktestStockDetailSchema.parse(raw)
}

export const StrategyBacktestWindowDetailSchema = z.object({
  run_id: z.string(),
  symbol: z.string(),
  window_index: z.number(),
  summary: z.record(z.unknown()).default({}),
  detail: z.record(z.unknown()).default({}),
})
export type StrategyBacktestWindowDetail = z.infer<typeof StrategyBacktestWindowDetailSchema>

export async function fetchStrategyBacktestWindowDetail(
  runId: string,
  symbol: string,
  windowIndex: number,
): Promise<StrategyBacktestWindowDetail> {
  const raw = await request<unknown>(
    `/backtest/strategy-runs/${runId}/stocks/${encodeURIComponent(symbol)}/windows/${windowIndex}`,
  )
  return StrategyBacktestWindowDetailSchema.parse(raw)
}

export async function renameStrategyBacktestRun(runId: string, title: string): Promise<StrategyBacktestRun> {
  const raw = await request<unknown>(`/backtest/strategy-runs/${runId}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  })
  return StrategyBacktestRunSchema.parse(raw)
}

export async function deleteStrategyBacktestRun(runId: string): Promise<void> {
  await request<unknown>(`/backtest/strategy-runs/${runId}`, {
    method: "DELETE",
  })
}

export const StrategyBacktestMetricRowSchema = z.object({
  metric: z.string(),
  value: z.unknown(),
})
export type StrategyBacktestMetricRow = z.infer<typeof StrategyBacktestMetricRowSchema>

export const StrategyBacktestCalibrationBucketRowSchema = z.object({
  score_low: z.number(),
  score_high: z.number(),
  n_observations: z.number(),
  avg_r_multiple: z.number(),
  avg_net_return: z.number(),
  win_rate: z.number(),
  target_exposure_pct: z.number(),
})
export type StrategyBacktestCalibrationBucketRow = z.infer<typeof StrategyBacktestCalibrationBucketRowSchema>

export const StrategyBacktestCalibrationSchema = z.object({
  status: z.string().default("fallback"),
  lookback_bars: z.number().default(0),
  window_start: z.string().nullable().optional(),
  window_end: z.string().nullable().optional(),
  n_observations: z.number().default(0),
  primary_metric: z.string().default("avg_r_multiple"),
  bucket_rows: z.array(StrategyBacktestCalibrationBucketRowSchema).default([]),
  ladder: z.array(z.record(z.unknown())).default([]),
  plot: z.record(z.unknown()).default({}),
  reason: z.string().nullable().optional(),
})
export type StrategyBacktestCalibration = z.infer<typeof StrategyBacktestCalibrationSchema>

export const StrategyBacktestGeneralResultsSchema = z.object({
  metrics: z.record(z.unknown()).default({}),
  trade_performance: z.array(StrategyBacktestMetricRowSchema).default([]),
  calibration: StrategyBacktestCalibrationSchema.default({
    status: "fallback",
    lookback_bars: 0,
    n_observations: 0,
    primary_metric: "avg_r_multiple",
    bucket_rows: [],
    ladder: [],
    plot: {},
  }),
  plots: z.record(z.unknown()).default({}),
})
export type StrategyBacktestGeneralResults = z.infer<typeof StrategyBacktestGeneralResultsSchema>

export const StrategyBacktestStockSchema = z.object({
  symbol: z.string(),
  allocation: z.record(z.unknown()).default({}),
  summary_metrics: z.record(z.unknown()).default({}),
  price_chart: z.record(z.unknown()).default({}),
  trade_ledger: z.array(z.record(z.unknown())).default([]),
  trade_performance: z.array(StrategyBacktestMetricRowSchema).default([]),
})
export type StrategyBacktestStock = z.infer<typeof StrategyBacktestStockSchema>

export const StrategyBacktestResponseSchema = z.object({
  strategy: z.record(z.unknown()).default({}),
  assumptions: z.record(z.unknown()).default({}),
  general_results: StrategyBacktestGeneralResultsSchema.default({
    metrics: {},
    trade_performance: [],
    plots: {},
  }),
  stocks: z.array(StrategyBacktestStockSchema).default([]),
})
export type StrategyBacktestResponse = z.infer<typeof StrategyBacktestResponseSchema>

export async function fetchStrategyBacktest(body: {
  strategy_id: string
  start_date: string
  end_date: string
  timeframe?: string
  family_history_mode?: FamilyHistoryMode
  cost_model: {
    brokerage_bps: number
    comm_bourse_bps: number
    reg_liv_bps: number
    slippage_bps: number
    tva_rate: number
  }
  volume_gate: {
    enabled: boolean
    kind: "min_abs" | "min_ratio_adv"
    min_volume_abs: number
    min_volume_ratio_adv: number
    adv_window: number
  }
  cooldown_bars: number
}): Promise<StrategyBacktestResponse> {
  const raw = await request<unknown>("/strategy/plan/backtest", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return StrategyBacktestResponseSchema.parse(raw)
}

export async function fetchDashboardIndices(): Promise<DashboardCustomIndex[]> {
  const raw = await request<unknown>("/dashboard/indices")
  return z.array(DashboardCustomIndexSchema).parse(raw)
}

export async function createDashboardIndex(body: {
  name: string
  symbols: string[]
}): Promise<DashboardCustomIndex> {
  const raw = await request<unknown>("/dashboard/indices", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return DashboardCustomIndexSchema.parse(raw)
}

export async function updateDashboardIndex(
  id: string,
  body: {
    name: string
    symbols: string[]
  },
): Promise<DashboardCustomIndex> {
  const raw = await request<unknown>(`/dashboard/indices/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  })
  return DashboardCustomIndexSchema.parse(raw)
}

export async function deleteDashboardIndex(id: string): Promise<void> {
  await request<unknown>(`/dashboard/indices/${id}`, {
    method: "DELETE",
  })
}

export async function createStrategy(body: {
  name: string
  note?: string
  side_policy?: string
  horizon?: string
}): Promise<SavedStrategy> {
  const raw = await request<unknown>("/strategy/plan/strategies", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return SavedStrategySchema.parse(raw)
}

export async function updateStrategy(
  id: string,
  body: {
    name?: string
    note?: string
    side_policy?: string
    horizon?: string
    config_json?: Record<string, unknown>
    status?: string
  },
): Promise<SavedStrategy> {
  const raw = await request<unknown>(`/strategy/plan/strategies/${id}`, {
    method: "PUT",
    body: JSON.stringify(body),
  })
  return SavedStrategySchema.parse(raw)
}

export async function duplicateStrategy(id: string): Promise<SavedStrategy> {
  const raw = await request<unknown>(`/strategy/plan/strategies/${id}/duplicate`, {
    method: "POST",
  })
  return SavedStrategySchema.parse(raw)
}

export async function archiveStrategy(id: string): Promise<SavedStrategy> {
  const raw = await request<unknown>(`/strategy/plan/strategies/${id}/archive`, {
    method: "PATCH",
  })
  return SavedStrategySchema.parse(raw)
}

// ---------------------------------------------------------------------------
// Signal Consensus
// ---------------------------------------------------------------------------

const FamilyScoreOutSchema = z.object({
  score_pct: z.number(),
  label: z.string(),
  weight: z.number(),
})

export const SignalConsensusSchema = z.object({
  symbol: z.string(),
  final_consensus: z.number().nullable(),
  final_consensus_label: z.string().nullable().optional(),
  enabled_families: z.array(z.string()).default([]),
  family_weights: z.record(z.number()).default({}),
  per_family: z.record(FamilyScoreOutSchema).default({}),
  explain: z.string().default(""),
})
export type SignalConsensus = z.infer<typeof SignalConsensusSchema>

export async function fetchSignalConsensus(body: {
  symbol: string
  horizon: string
  enabled_families: string[]
  timeframe?: string
  cost_bps?: number
  cooldown_bars?: number
}): Promise<SignalConsensus> {
  const raw = await request<unknown>("/strategy/plan/signal-consensus", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return SignalConsensusSchema.parse(raw)
}

// ---------------------------------------------------------------------------
// Signal Zone Chart
// ---------------------------------------------------------------------------

const ZoneRepSchema = z.object({
  variant_id: z.string(),
  weight: z.number(),
  label: z.string(),
  indicator: z.record(z.string(), z.any()).nullable().optional(),
})

const FamilyZoneSchema = z.object({
  scores: z.array(z.number()),
  representatives: z.array(ZoneRepSchema),
  indicator: z.record(z.any()).nullable().optional(),
})

export const SignalZoneChartSchema = z.object({
  symbol: z.string(),
  horizon: z.string(),
  bars: z.array(OhlcvBarSchema),
  families: z.record(FamilyZoneSchema),
})
export type SignalZoneChart = z.infer<typeof SignalZoneChartSchema>

export async function fetchSignalZoneChart(body: {
  symbol: string
  horizon: string
  enabled_families: string[]
  timeframe?: string
  cost_bps?: number
  cooldown_bars?: number
  family_history_mode?: FamilyHistoryMode
}): Promise<SignalZoneChart> {
  const raw = await request<unknown>("/strategy/signal/zone-chart", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return SignalZoneChartSchema.parse(raw)
}

// ---------------------------------------------------------------------------
// Execution Plan
// ---------------------------------------------------------------------------

export const ExecutionPlanSchema = z.object({
  symbol: z.string(),
  direction: z.string().nullable().optional(),
  status: z.string().default("no_setup"),
  entry_price: z.number().nullable().optional(),
  entry_zone_low: z.number().nullable().optional(),
  entry_zone_high: z.number().nullable().optional(),
  stop_loss: z.number().nullable().optional(),
  target_1: z.number().nullable().optional(),
  target_2: z.number().nullable().optional(),
  rr_ratio: z.number().nullable().optional(),
  atr_14: z.number().nullable().optional(),
  adjusted_consensus: z.number().nullable().optional(),
  explain: z.string().default(""),
})
export type ExecutionPlan = z.infer<typeof ExecutionPlanSchema>

export async function fetchExecution(body: {
  symbol: string
  horizon: string
  enabled_families: string[]
  execution_holding_bars?: number
  side_policy: string
  entry_threshold?: number
  atr_multiplier?: number
  buffer_pct?: number
  min_rr?: number
  cost_bps?: number
  cooldown_bars?: number
  consensus_override?: number | null
}): Promise<ExecutionPlan> {
  const raw = await request<unknown>("/strategy/plan/execution", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return ExecutionPlanSchema.parse(raw)
}

// ---------------------------------------------------------------------------
// Sizing
// ---------------------------------------------------------------------------

const StockSizingRowSchema = z.object({
  symbol: z.string(),
  weight_pct: z.number().default(0),
  shares: z.number().default(0),
  position_value: z.number().default(0),
  trade_risk: z.number().default(0),
  status: z.string().default("no_setup"),
})

const FocusedKellyOutSchema = z.object({
  full_kelly_pct: z.number().default(0),
  modified_kelly_pct: z.number().default(0),
  position_size_shares: z.number().default(0),
  position_value: z.number().default(0),
  trade_risk: z.number().default(0),
  pct_of_account_risked: z.number().default(0),
})

export const SizingResultSchema = z.object({
  focused_kelly: FocusedKellyOutSchema.nullable().optional(),
  portfolio_table: z.array(StockSizingRowSchema).default([]),
  total_exposure_pct: z.number().default(0),
  total_risk_pct: z.number().default(0),
  capital_deployed: z.number().default(0),
  explain: z.string().default(""),
})
export type SizingResult = z.infer<typeof SizingResultSchema>
export type StockSizingRow = z.infer<typeof StockSizingRowSchema>
export type FocusedKelly = z.infer<typeof FocusedKellyOutSchema>

export interface StockSizingInput {
  symbol: string
  entry_price: number
  stop_price: number
  atr_pct?: number
  consensus?: number
  sector?: string
  status?: string
}

export async function fetchSizing(body: {
  stocks: StockSizingInput[]
  account_equity: number
  kelly_modifier: number
  allocation_method: string
  max_position_pct: number
  max_sector_pct: number
  win_rate: number
  avg_wl_ratio: number
  focused_symbol?: string | null
}): Promise<SizingResult> {
  const raw = await request<unknown>("/strategy/plan/sizing", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return SizingResultSchema.parse(raw)
}

// ---------------------------------------------------------------------------
// WFO Signal Layer
// ---------------------------------------------------------------------------

export const WfoRepresentativeSchema = z.object({
  family: z.string(),
  archetype: z.string(),
  variant_id: z.string(),
  params: z.record(z.unknown()),
  signal: z.number(),
  signal_label: z.string(),
  normalized_weight: z.number(),
  contribution: z.number(),
  description: z.string(),
  current_close: z.number().nullable().optional(),
  indicator_value: z.number().nullable().optional(),
  explanation: z.string().default(""),
  wfo_prom: z.number().nullable().optional(),
})
export type WfoRepresentative = z.infer<typeof WfoRepresentativeSchema>

export const WfoCategorySummarySchema = z.object({
  category: z.string(),
  status: z.string(),
  score_pct: z.number().nullable().optional(),
  signal_label: z.string().nullable().optional(),
  representatives: z.array(WfoRepresentativeSchema).default([]),
  wfe_pct: z.number().nullable().optional(),
  robustness_ratio: z.number().nullable().optional(),
  total_folds: z.number().nullable().optional(),
  profitable_folds: z.number().nullable().optional(),
  mean_oos_sharpe: z.number().nullable().optional(),
  total_oos_pnl: z.number().nullable().optional(),
  worst_fold_drawdown: z.number().nullable().optional(),
  composite_score: z.number().nullable().optional(),
  robustness_grade: z.string().nullable().optional(),
  computed_at: z.string().nullable().optional(),
  data_as_of: z.string().nullable().optional(),
  compute_seconds: z.number().nullable().optional(),
  config: z.record(z.unknown()).nullable().optional(),
})
export type WfoCategorySummary = z.infer<typeof WfoCategorySummarySchema>

export const WfoGlobalSignalSchema = z.object({
  status: z.string(),
  global_score_pct: z.number().nullable().optional(),
  raw_score_pct: z.number().nullable().optional(),
  signal_label: z.string().nullable().optional(),
  recommendation: z.string().nullable().optional(),
  weight_tendance: z.number().nullable().optional(),
  weight_momentum: z.number().nullable().optional(),
  weight_oscillation: z.number().nullable().optional(),
  weight_volume: z.number().nullable().optional(),
  sr_modifier: z.number().nullable().optional(),
  sr_support_level: z.number().nullable().optional(),
  sr_resistance_level: z.number().nullable().optional(),
  sr_support_method: z.string().nullable().optional(),
  sr_resistance_method: z.string().nullable().optional(),
  best_category: z.string().nullable().optional(),
  best_category_score: z.number().nullable().optional(),
  categories_viable: z.number().nullable().optional(),
  consensus_wfe_pct: z.number().nullable().optional(),
  consensus_robustness: z.number().nullable().optional(),
  computed_at: z.string().nullable().optional(),
  data_as_of: z.string().nullable().optional(),
})
export type WfoGlobalSignal = z.infer<typeof WfoGlobalSignalSchema>

export const WfoSummaryResponseSchema = z.object({
  symbol: z.string(),
  horizon: z.string(),
  categories: z.record(WfoCategorySummarySchema),
  global_signal: WfoGlobalSignalSchema.nullable().optional(),
})
export type WfoSummaryResponse = z.infer<typeof WfoSummaryResponseSchema>

export async function fetchWfoSummary(
  symbol: string,
  horizon: string,
  variant: string = "expanded",
): Promise<WfoSummaryResponse> {
  const params = new URLSearchParams({ symbol, horizon, variant })
  const res = await fetch(`${API_BASE}/strategy/wfo/summary?${params}`)
  if (!res.ok) throw new Error(`WFO summary fetch failed: ${res.status}`)
  return WfoSummaryResponseSchema.parse(await res.json())
}

export async function triggerWfoComputation(body: {
  symbol: string
  horizon: string
  variant?: string
  categories?: string[]
  train_bars?: number
  oos_bars?: number
  step_bars?: number
  window_policy?: string
  top_k_folds?: number
  min_walk_forwards?: number
  strict_fallback_enabled?: boolean
  strict_fallback_floor?: number
  cost_bps?: number
  max_reps?: number
  max_corr?: number
}): Promise<{ triggered: string[]; job_id: string | null }> {
  const res = await fetch(`${API_BASE}/strategy/wfo/trigger`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`WFO trigger failed: ${res.status}`)
  return res.json()
}

// --- WFO Detail (fold-by-fold) ---

export const WfoCategoryDetailSchema = WfoCategorySummarySchema.extend({
  folds: z.array(z.record(z.unknown())).nullable().optional(),
  config: z.record(z.unknown()).nullable().optional(),
  error_message: z.string().nullable().optional(),
})
export type WfoCategoryDetail = z.infer<typeof WfoCategoryDetailSchema>

export async function fetchWfoDetail(
  symbol: string,
  horizon: string,
  category: string,
  variant = "expanded",
): Promise<WfoCategoryDetail> {
  const params = new URLSearchParams({ symbol, horizon, category, variant })
  const res = await fetch(`${API_BASE}/strategy/wfo/detail?${params}`)
  if (!res.ok) throw new Error(`WFO detail fetch failed: ${res.status}`)
  return WfoCategoryDetailSchema.parse(await res.json())
}

// --- WFO Config ---

export const WfoPipelineStepSchema = z.object({
  id: z.string(),
  label: z.string(),
  description: z.string(),
  detail: z.string().optional(),
})

export const WfoFamilyDescriptionSchema = z.object({
  label: z.string(),
  archetype: z.string(),
  signal_type: z.string(),
  description: z.string(),
})

export const WfoConfigSchema = z.object({
  horizons: z.record(z.object({
    train: z.number(),
    test: z.number(),
    step: z.number(),
    max_years: z.number(),
  })),
  categories: z.record(z.array(z.string())),
  family_signal_types: z.record(z.string()),
  family_descriptions: z.record(WfoFamilyDescriptionSchema),
  scoring: z.object({
    grade_thresholds: z.record(z.object({
      wfe: z.number(),
      robustness: z.number(),
    })),
    composite_weights: z.record(z.number()),
    max_representatives: z.number(),
    max_correlation: z.number(),
  }),
  window_policy_defaults: z.object({
    default_policy: z.string(),
    ratio_anchors: z.array(z.number()),
    min_walk_forwards: z.number(),
    top_k_folds: z.number(),
    strict_fallback_enabled: z.boolean(),
    strict_fallback_floor: z.number(),
    train_bands: z.record(z.object({
      min: z.number(),
      max: z.number(),
    })),
  }),
  pipeline_steps: z.array(WfoPipelineStepSchema),
})
export type WfoConfig = z.infer<typeof WfoConfigSchema>

export async function fetchWfoConfig(): Promise<WfoConfig> {
  const res = await fetch(`${API_BASE}/strategy/wfo/config`)
  if (!res.ok) throw new Error(`WFO config fetch failed: ${res.status}`)
  return WfoConfigSchema.parse(await res.json())
}

export async function triggerAllWfo(body: {
  variants?: string[]
  train_bars?: number
  oos_bars?: number
  step_bars?: number
  window_policy?: string
  top_k_folds?: number
  min_walk_forwards?: number
  strict_fallback_enabled?: boolean
  strict_fallback_floor?: number
  cost_bps?: number
  max_reps?: number
  max_corr?: number
}): Promise<{ total_jobs: number; symbols: number; horizons: string[]; variants: string[] }> {
  const res = await fetch(`${API_BASE}/strategy/wfo/trigger-all`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`WFO trigger-all failed: ${res.status}`)
  return res.json()
}

export async function fetchWfoBatchStatus(): Promise<{
  total: number
  succeeded: number
  running: number
  failed: number
  pending: number
  insufficient_data: number
}> {
  const res = await fetch(`${API_BASE}/strategy/wfo/batch-status`)
  if (!res.ok) throw new Error(`WFO batch-status fetch failed: ${res.status}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// Signal backtest + Monte Carlo
// ---------------------------------------------------------------------------

const MCEnvelopeSchema = z.object({
  p05: z.array(z.number()),
  p25: z.array(z.number()),
  p50: z.array(z.number()),
  p75: z.array(z.number()),
  p95: z.array(z.number()),
})

const MCStatBandSchema = z.object({
  p05: z.number().nullable(),
  p50: z.number().nullable(),
  p95: z.number().nullable(),
})

const MCStatsSchema = z.object({
  total_return: MCStatBandSchema,
  cagr: MCStatBandSchema,
  sharpe: MCStatBandSchema,
  max_drawdown: MCStatBandSchema,
  var95: z.number().nullable(),
  cvar95: z.number().nullable(),
  prob_positive_terminal: z.number().nullable(),
})

const BacktestMetricsSchema = z.object({
  total_return: z.number().nullable(),
  cagr: z.number().nullable(),
  sharpe: z.number().nullable(),
  max_drawdown: z.number().nullable(),
  win_rate: z.number().nullable(),
  n_trades: z.number().nullable(),
})

const ShuffleStatsSchema = z.object({
  status: z.string(),
  n_trades: z.number(),
  expected_return: z.number().nullable(),
  ci95: z.tuple([z.number(), z.number()]).nullable(),
  prob_positive: z.number().nullable(),
  var95: z.number().nullable(),
  cvar95: z.number().nullable(),
  envelope: MCEnvelopeSchema.nullable(),
}).nullable()

export const SignalBacktestResultSchema = z.object({
  source: z.string(),
  scope: z.string(),
  scope_key: z.string(),
  status: z.string(),
  warning_code: z.string().nullable().optional(),
  window_start: z.string().nullable(),
  window_end: z.string().nullable(),
  n_bars: z.number().nullable(),
  n_trades: z.number().nullable(),
  equity: z.array(z.number()).nullable(),
  dates: z.array(z.string()).nullable(),
  trades: z.array(z.record(z.unknown())).nullable().optional(),
  close_series: z.array(z.number()).nullable().optional(),
  position_series: z.array(z.number()).nullable().optional(),
  signal_diagnostics: z.record(z.unknown()).nullable().optional(),
  metrics: BacktestMetricsSchema,
  mc: z.object({
    method: z.string(),
    n_paths: z.number(),
    envelope: MCEnvelopeSchema.nullable(),
    stats: MCStatsSchema.nullable(),
  }),
  shuffle_stats: ShuffleStatsSchema.optional(),
  computed_at: z.string().nullable(),
  data_as_of: z.string().nullable(),
  is_stale: z.boolean(),
})

export const SignalBacktestResponseSchema = z.object({
  symbol: z.string(),
  horizon: z.string(),
  variant: z.string(),
  market_data_as_of: z.string().nullable(),
  results: z.array(SignalBacktestResultSchema),
})

export type SignalBacktestResult = z.infer<typeof SignalBacktestResultSchema>
export type SignalBacktestResponse = z.infer<typeof SignalBacktestResponseSchema>

export const SignalEngineResultSchema = z.object({
  symbol: z.string(),
  horizon: z.string(),
  variant: z.string(),
  status: z.string(),
  aggregate_score_pct: z.number().nullable(),
  expanded_aggregate_score_pct: z.number().nullable(),
  signal_label: z.string().nullable(),
  per_category: z.record(z.unknown()).nullable(),
  per_family: z.record(z.unknown()).nullable(),
  technical_levels: z.record(z.unknown()).nullable(),
  support_resistance: z.record(z.unknown()).nullable(),
  computed_at: z.string().nullable(),
  data_as_of: z.string().nullable(),
  is_stale: z.boolean(),
  market_data_as_of: z.string().nullable(),
  families: z.record(z.unknown()),
  resolution_mode: z.string().optional(),
  cache_state: z.string().optional(),
})

export type SignalEngineResult = z.infer<typeof SignalEngineResultSchema>

export async function fetchSignalBacktestResults(
  symbol: string,
  horizon: string,
  opts?: { variant?: string; source?: string; scope?: string }
): Promise<SignalBacktestResponse> {
  const params = new URLSearchParams({ symbol, horizon, variant: opts?.variant ?? "expanded" })
  if (opts?.source) params.set("source", opts.source)
  if (opts?.scope) params.set("scope", opts.scope)
  const raw = await request<unknown>(`/strategy/backtest-mc?${params}`)
  return SignalBacktestResponseSchema.parse(raw)
}

export async function triggerSignalBacktest(body: {
  symbol: string
  horizon: string
  variant?: string
  window_start?: string
  window_end?: string
  mc_config?: Record<string, unknown>
}): Promise<{ job_id: string; status: string }> {
  return request("/strategy/backtest-mc/trigger", {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export async function triggerSignalEngine(body: {
  symbol: string
  horizon: string
  variant?: string
}): Promise<{ job_id: string; status: string }> {
  return request("/strategy/engine/trigger", {
    method: "POST",
    body: JSON.stringify(body),
  })
}

export async function fetchSignalEngineResult(
  symbol: string,
  horizon: string,
  variant = "expanded",
  opts?: { cooldownBars?: number }
): Promise<SignalEngineResult> {
  const params = new URLSearchParams({ symbol, horizon, variant })
  if (opts?.cooldownBars != null) {
    params.set("cooldown_bars", String(Math.max(0, Math.floor(opts.cooldownBars))))
  }
  const raw = await request<unknown>(`/strategy/engine/result?${params}`)
  return SignalEngineResultSchema.parse(raw)
}

export async function fetchSignalEngineBatchStatus(
  symbol: string,
  horizon: string,
  variant = "expanded"
): Promise<{ symbol: string; horizon: string; variant: string; jobs: unknown[] }> {
  const params = new URLSearchParams({ symbol, horizon, variant })
  return request(`/strategy/engine/batch-status?${params}`)
}

function _shouldBootstrapSignalEngineResult(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false
  const message = error.message.toLowerCase()
  if (error.status === 404) {
    return (
      message.includes("no persisted signal engine result")
      || message.includes("no signal engine result")
    )
  }
  if (error.status === 409) {
    return message.includes("persisted signal engine result is invalid")
  }
  return false
}

function _sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

export async function fetchSignalEngineResultWithBootstrap(
  symbol: string,
  horizon: string,
  variant = "expanded",
  opts?: { timeoutMs?: number; pollMs?: number }
): Promise<SignalEngineResult> {
  try {
    return await fetchSignalEngineResult(symbol, horizon, variant)
  } catch (error) {
    if (!_shouldBootstrapSignalEngineResult(error)) throw error
  }

  await triggerSignalEngine({ symbol, horizon, variant })
  const timeoutMs = Math.max(15_000, opts?.timeoutMs ?? 180_000)
  const pollMs = Math.max(1_000, opts?.pollMs ?? 3_000)
  const deadline = Date.now() + timeoutMs

  while (Date.now() < deadline) {
    await _sleep(pollMs)

    try {
      return await fetchSignalEngineResult(symbol, horizon, variant)
    } catch (error) {
      if (!_shouldBootstrapSignalEngineResult(error)) throw error
    }

    try {
      const status = await fetchSignalEngineBatchStatus(symbol, horizon, variant)
      const latest = (Array.isArray(status.jobs) ? status.jobs[0] : null) as
        | { status?: unknown; error_message?: unknown }
        | null
      const latestStatus = String(latest?.status ?? "").toLowerCase()
      if (latestStatus === "failed") {
        const detail = typeof latest?.error_message === "string" && latest.error_message
          ? `: ${latest.error_message}`
          : ""
        throw new Error(`Le calcul Signal Engine a echoue${detail}`)
      }
    } catch (error) {
      if (error instanceof Error && error.message.includes("a echoue")) {
        throw error
      }
    }
  }

  throw new Error("Le calcul Signal Engine est toujours en cours. Reessayez dans quelques instants.")
}

export async function triggerAllSignalEngine(body?: {
  variants?: string[]
}): Promise<{ batch_id: string; total_jobs: number; symbols: number; horizons: string[]; variants: string[] }> {
  return request("/strategy/engine/trigger-all", {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  })
}

export async function fetchSignalEngineGlobalBatchStatus(batchId?: string): Promise<{
  batch_id: string | null
  total: number
  succeeded: number
  running: number
  failed: number
  pending: number
  partial: number
}> {
  const params = new URLSearchParams()
  if (batchId) params.set("batch_id", batchId)
  const query = params.toString()
  return request(`/strategy/engine/batch-status-global${query ? `?${query}` : ""}`)
}

// ---------------------------------------------------------------------------
// Analytics — signal evaluation + macro factor
// ---------------------------------------------------------------------------

export const ICCurveSchema = z.object({
  horizons: z.array(z.number()),
  ic_values: z.array(z.number()),
  ic_se: z.array(z.number()),
  ic_ci_lower: z.array(z.number()),
  ic_ci_upper: z.array(z.number()),
  n_obs: z.array(z.number()),
})
export type ICCurve = z.infer<typeof ICCurveSchema>

export const PortfolioStatsSchema = z.object({
  sharpe: z.number(),
  sortino: z.number(),
  max_drawdown: z.number(),
  calmar: z.number(),
  turnover: z.number(),
  hit_rate: z.number(),
  profit_factor: z.number(),
  avg_win: z.number(),
  avg_loss: z.number(),
  after_cost_sharpe: z.number(),
  n_trades: z.number(),
  total_return: z.number(),
})
export type PortfolioStats = z.infer<typeof PortfolioStatsSchema>

export const RobustnessSchema = z.object({
  dsr: z.number(),
  psr: z.number(),
  sharpe_bootstrap_ci: z.array(z.number()),
  ic_bootstrap_ci: z.array(z.number()),
  ic_cv: z.number(),
  sharpe_cv: z.number(),
  n_variants: z.number(),
})
export type Robustness = z.infer<typeof RobustnessSchema>

export const SignalEvaluationReportSchema = z.object({
  signal_id: z.string(),
  symbol: z.string(),
  n_obs: z.number(),
  horizons: z.array(z.number()),
  ic_curve: ICCurveSchema,
  hit_rate_h1: z.number(),
  hit_rate_ci: z.array(z.number()),
  conditional_return_tstat: z.number(),
  portfolio: PortfolioStatsSchema,
  robustness: RobustnessSchema,
})
export type SignalEvaluationReport = z.infer<typeof SignalEvaluationReportSchema>

export const SignalOverviewRowSchema = z.object({
  symbol: z.string(),
  category: z.string(),
  horizon: z.string(),
  signal_id: z.string(),
  ic_h1: z.number().nullable().optional(),
  ic_h5: z.number().nullable().optional(),
  dsr: z.number().nullable().optional(),
  psr: z.number().nullable().optional(),
  sharpe: z.number(),
  after_cost_sharpe: z.number().nullable().optional(),
  hit_rate: z.number().nullable().optional(),
  n_obs: z.number(),
  fdr_pass: z.boolean(),
  engine_score_pct: z.number().nullable().optional(),
  engine_label: z.string().nullable().optional(),
})
export type SignalOverviewRow = z.infer<typeof SignalOverviewRowSchema>

export const MacroCatalogRowSchema = z.object({
  canonical_id: z.string(),
  yahoo_symbol: z.string(),
  description: z.string(),
  channel_tags: z.array(z.string()),
  data_as_of: z.string().nullable().optional(),
  row_count: z.number().nullable().optional(),
  has_data: z.boolean(),
})
export type MacroCatalogRow = z.infer<typeof MacroCatalogRowSchema>

export async function getAnalyticsSignalsOverview(symbol?: string, horizon?: string): Promise<SignalOverviewRow[]> {
  const params = new URLSearchParams()
  if (symbol) params.set("symbol", symbol)
  if (horizon) params.set("horizon", horizon)
  const q = params.toString()
  const data = await request(`/analytics/signals${q ? `?${q}` : ""}`)
  return z.array(SignalOverviewRowSchema).parse(data)
}

export async function evaluateStockSignal(
  symbol: string,
  category: string,
  horizon: string,
  opts?: { n_variants?: number; spread_bps?: number; commission_bps?: number }
): Promise<SignalEvaluationReport> {
  const params = new URLSearchParams()
  if (opts?.n_variants) params.set("n_variants", String(opts.n_variants))
  if (opts?.spread_bps) params.set("spread_bps", String(opts.spread_bps))
  if (opts?.commission_bps) params.set("commission_bps", String(opts.commission_bps))
  const q = params.toString()
  const data = await request(`/analytics/stocks/${symbol}/evaluate/${category}/${horizon}${q ? `?${q}` : ""}`)
  return SignalEvaluationReportSchema.parse(data)
}

export async function getMacroCatalog(): Promise<MacroCatalogRow[]> {
  const data = await request("/analytics/macro/catalog")
  return z.array(MacroCatalogRowSchema).parse(data)
}

export async function enqueueMacroIngest(canonicalId: string, start?: string): Promise<{ canonical_id: string; job_id: string; status: string }> {
  const params = new URLSearchParams()
  if (start) params.set("start", start)
  const q = params.toString()
  return request(`/analytics/macro/ingest/${canonicalId}${q ? `?${q}` : ""}`, { method: "POST" })
}

export async function enqueueAllMacroIngest(start?: string): Promise<{ enqueued: { canonical_id: string; job_id: string }[] }> {
  const params = new URLSearchParams()
  if (start) params.set("start", start)
  const q = params.toString()
  return request(`/analytics/macro/ingest-all${q ? `?${q}` : ""}`, { method: "POST" })
}

// Factor relevance

export const FactorRelevanceRowSchema = z.object({
  factor_id: z.string(),
  symbol: z.string(),
  ic: z.number(),
  t_stat: z.number(),
  p_value: z.number(),
  ic_cv: z.number(),
  n_obs: z.number(),
  significant: z.boolean(),
})
export type FactorRelevanceRow = z.infer<typeof FactorRelevanceRowSchema>

export const FactorRelevanceMatrixSchema = z.object({
  symbol: z.string(),
  as_of: z.string(),
  pairs: z.array(FactorRelevanceRowSchema),
})
export type FactorRelevanceMatrix = z.infer<typeof FactorRelevanceMatrixSchema>

export const AllFactorRelevanceSummarySchema = z.object({
  factor_id: z.string(),
  n_significant: z.number(),
  n_total: z.number(),
  top_symbols: z.array(z.string()),
})
export type AllFactorRelevanceSummary = z.infer<typeof AllFactorRelevanceSummarySchema>

export const FactorLeaderboardRowSchema = z.object({
  symbol: z.string(),
  n_significant: z.number(),
  best_factor: z.string(),
  max_t_stat: z.number(),
  max_ic: z.number(),
  n_obs: z.number(),
})
export type FactorLeaderboardRow = z.infer<typeof FactorLeaderboardRowSchema>

export async function getFactorRelevance(
  symbol: string,
  opts?: { lagRule?: string; returnMethod?: string; lookbackDays?: number; forwardHorizon?: number }
): Promise<FactorRelevanceMatrix> {
  const params = new URLSearchParams()
  if (opts?.lagRule) params.set("lag_rule", opts.lagRule)
  if (opts?.returnMethod) params.set("return_method", opts.returnMethod)
  if (opts?.lookbackDays) params.set("lookback_days", String(opts.lookbackDays))
  if (opts?.forwardHorizon) params.set("forward_horizon", String(opts.forwardHorizon))
  const q = params.toString()
  const data = await request(`/analytics/factors/${symbol}${q ? `?${q}` : ""}`)
  return FactorRelevanceMatrixSchema.parse(data)
}

export async function getAllFactorRelevanceSummary(): Promise<AllFactorRelevanceSummary[]> {
  const data = await request("/analytics/factors")
  return z.array(AllFactorRelevanceSummarySchema).parse(data)
}

export async function getFactorLeaderboard(opts?: {
  lookbackDays?: number
  forwardHorizon?: number
  returnMethod?: string
}): Promise<FactorLeaderboardRow[]> {
  const params = new URLSearchParams()
  if (opts?.lookbackDays) params.set("lookback_days", String(opts.lookbackDays))
  if (opts?.forwardHorizon) params.set("forward_horizon", String(opts.forwardHorizon))
  if (opts?.returnMethod) params.set("return_method", opts.returnMethod)
  const q = params.toString()
  const data = await request(`/analytics/factors/leaderboard${q ? `?${q}` : ""}`)
  return z.array(FactorLeaderboardRowSchema).parse(data)
}

export const FactorSignalEvalSchema = z.object({
  factor_id: z.string(),
  signal_name: z.string(),
  symbol: z.string(),
  citation: z.string(),
  channel_filter: z.array(z.string()),
  applicable: z.boolean(),
  ic_h1: z.number(),
  ic_h5: z.number(),
  hit_rate: z.number(),
  sharpe: z.number(),
  after_cost_sharpe: z.number(),
  dsr: z.number(),
  psr: z.number(),
  conditional_return_tstat: z.number(),
  n_obs: z.number(),
  fdr_pass: z.boolean(),
  ic_curve: ICCurveSchema,
  portfolio: PortfolioStatsSchema,
  robustness: RobustnessSchema,
})
export type FactorSignalEval = z.infer<typeof FactorSignalEvalSchema>

export async function getFactorSignalEval(
  symbol: string,
  opts?: { returnMethod?: string; lookbackDays?: number }
): Promise<FactorSignalEval[]> {
  const params = new URLSearchParams()
  if (opts?.returnMethod) params.set("return_method", opts.returnMethod)
  if (opts?.lookbackDays) params.set("lookback_days", String(opts.lookbackDays))
  const q = params.toString()
  const data = await request(`/analytics/factors/${symbol}/evaluate${q ? `?${q}` : ""}`)
  return z.array(FactorSignalEvalSchema).parse(data)
}


// ---------------------------------------------------------------------------
// Predictive ability — bucket × forward-horizon analytics
// ---------------------------------------------------------------------------

export const PREDICTIVE_BUCKETS = ["strong_sell", "sell", "hold", "buy", "strong_buy"] as const
export type PredictiveBucket = (typeof PREDICTIVE_BUCKETS)[number]

export const PredictiveAbilityCellSchema = z.object({
  bucket: z.string(),
  fwd_h: z.number(),
  n: z.number(),
  mean: z.number().nullable().optional(),
  std: z.number().nullable().optional(),
  ci_lower: z.number().nullable().optional(),
  ci_upper: z.number().nullable().optional(),
  hit_rate: z.number().nullable().optional(),
  hit_ci_lower: z.number().nullable().optional(),
  hit_ci_upper: z.number().nullable().optional(),
})
export type PredictiveAbilityCell = z.infer<typeof PredictiveAbilityCellSchema>

export const PredictiveAbilityMatrixSchema = z.object({
  symbol: z.string(),
  source: z.string(),
  horizon: z.string(),
  categories: z.array(z.string()),
  n_obs: z.number(),
  buckets: z.array(z.string()),
  fwd_horizons: z.array(z.number()),
  cells: z.array(PredictiveAbilityCellSchema),
  available: z.boolean().default(true),
  message: z.string().nullable().optional(),
  current_score: z.number().nullable().optional(),
  current_bucket: z.string().nullable().optional(),
})
export type PredictiveAbilityMatrix = z.infer<typeof PredictiveAbilityMatrixSchema>

export const CategoryCombinationRowSchema = z.object({
  categories: z.array(z.string()),
  n_strong_buy: z.number(),
  n_strong_sell: z.number(),
  strong_buy_mean: z.number().nullable().optional(),
  strong_sell_mean: z.number().nullable().optional(),
  monotonicity_score: z.number().nullable().optional(),
})
export type CategoryCombinationRow = z.infer<typeof CategoryCombinationRowSchema>

export const CategoryCombinationsSchema = z.object({
  symbol: z.string(),
  source: z.string(),
  horizon: z.string(),
  fwd_h: z.number(),
  rows: z.array(CategoryCombinationRowSchema),
})
export type CategoryCombinations = z.infer<typeof CategoryCombinationsSchema>

export const PredictiveHistoryStatusSchema = z.object({
  total: z.number(),
  pending: z.number(),
  running: z.number(),
  succeeded: z.number(),
  failed: z.number(),
})
export type PredictiveHistoryStatus = z.infer<typeof PredictiveHistoryStatusSchema>

export interface PredictiveAbilityArgs {
  symbol: string
  source: "engine_legacy" | "engine_expanded" | "wfo" | "factor_x_ta"
  horizon: "short" | "medium" | "long"
  categories?: string[]
  fwdHorizons?: number[]
  lookback_days?: number
  return_calc_method?: string
}

export async function getPredictiveAbility(args: PredictiveAbilityArgs): Promise<PredictiveAbilityMatrix> {
  const params = new URLSearchParams({
    symbol: args.symbol,
    source: args.source,
    horizon: args.horizon,
    lookback_days: String(args.lookback_days ?? 0),
  })
  if (args.categories && args.categories.length > 0) {
    params.set("categories", args.categories.join(","))
  }
  if (args.fwdHorizons && args.fwdHorizons.length > 0) {
    params.set("fwd_horizons", args.fwdHorizons.join(","))
  }
  if (args.return_calc_method) {
    params.set("return_calc_method", args.return_calc_method)
  }
  const data = await request(`/analytics/predictive-ability?${params.toString()}`)
  return PredictiveAbilityMatrixSchema.parse(data)
}

export async function getCategoryCombinations(args: {
  symbol: string
  source: "engine_legacy" | "engine_expanded" | "wfo" | "factor_x_ta"
  horizon: "short" | "medium" | "long"
  fwd_h?: number
  lookback_days?: number
  return_calc_method?: string
}): Promise<CategoryCombinations> {
  const params = new URLSearchParams({
    symbol: args.symbol,
    source: args.source,
    horizon: args.horizon,
    fwd_h: String(args.fwd_h ?? 5),
    lookback_days: String(args.lookback_days ?? 0),
  })
  if (args.return_calc_method) {
    params.set("return_calc_method", args.return_calc_method)
  }
  const data = await request(`/analytics/predictive-ability/combinations?${params.toString()}`)
  return CategoryCombinationsSchema.parse(data)
}

export async function triggerPredictiveHistory(symbol: string): Promise<{ triggered: number; job_ids: string[] }> {
  const res = await fetch(`${API_BASE}/analytics/predictive-history/trigger?symbol=${encodeURIComponent(symbol)}`, {
    method: "POST",
  })
  if (!res.ok) throw new Error(`predictive-history trigger failed: ${res.status}`)
  return res.json()
}

export async function triggerAllPredictiveHistory(): Promise<{ triggered: number; job_ids: string[] }> {
  const res = await fetch(`${API_BASE}/analytics/predictive-history/trigger-all`, { method: "POST" })
  if (!res.ok) throw new Error(`predictive-history trigger-all failed: ${res.status}`)
  return res.json()
}

export async function fetchPredictiveHistoryBatchStatus(): Promise<PredictiveHistoryStatus> {
  const data = await request("/analytics/predictive-history/batch-status")
  return PredictiveHistoryStatusSchema.parse(data)
}

export const PredictiveLeaderboardRowSchema = z.object({
  symbol: z.string(),
  source: z.string(),
  n: z.number(),
  ic_by_fwd_h: z.record(z.string(), z.number().nullable()),
  tstat_by_fwd_h: z.record(z.string(), z.number().nullable()),
  mean_ic: z.number().nullable().optional(),
  mean_hit_rate: z.number().nullable().optional(),
  mean_sharpe: z.number().nullable().optional(),
})
export type PredictiveLeaderboardRow = z.infer<typeof PredictiveLeaderboardRowSchema>

export const PredictiveLeaderboardSchema = z.object({
  engine_horizon: z.string(),
  fwd_horizons: z.array(z.number()),
  rows: z.array(PredictiveLeaderboardRowSchema),
})
export type PredictiveLeaderboard = z.infer<typeof PredictiveLeaderboardSchema>

export async function getPredictiveAbilityLeaderboard(
  engineHorizon: "short" | "medium" | "long",
  lookback_days: number = 0,
  return_calc_method: string = "open_to_open",
): Promise<PredictiveLeaderboard> {
  const data = await request(
    `/analytics/predictive-ability/leaderboard?engine_horizon=${engineHorizon}&lookback_days=${lookback_days}&return_calc_method=${return_calc_method}`,
  )
  return PredictiveLeaderboardSchema.parse(data)
}

// ---------------------------------------------------------------------------
// Factor × TA — Phase 2
// ---------------------------------------------------------------------------

export const FactorConfigItemSchema = z.object({
  factor_ticker: z.string(),
  label: z.string(),
  enabled: z.boolean(),
})
export type FactorConfigItem = z.infer<typeof FactorConfigItemSchema>

export const FactorConfigResponseSchema = z.object({
  stock_symbol: z.string(),
  factors: z.array(FactorConfigItemSchema),
})
export type FactorConfigResponse = z.infer<typeof FactorConfigResponseSchema>

export const FamilyResultSummarySchema = z.object({
  family: z.string(),
  category: z.string(),
  status: z.string(),
  family_score_pct: z.number().nullable(),
  representative_count: z.number().nullable(),
  is_provisional: z.boolean().nullable(),
  representatives: z.array(z.record(z.unknown())),
  as_of: z.string().nullable(),
})
export type FamilyResultSummary = z.infer<typeof FamilyResultSummarySchema>

const PipelineResultSchema = z.object({
  families: z.array(FamilyResultSummarySchema),
  as_of: z.string().nullable(),
})
export type PipelineResult = z.infer<typeof PipelineResultSchema>

export const FactorXTaSignalResponseSchema = z.object({
  symbol: z.string(),
  horizon: z.string(),
  engine: PipelineResultSchema,
  wfo: PipelineResultSchema,
})
export type FactorXTaSignalResponse = z.infer<typeof FactorXTaSignalResponseSchema>

export const FactorConditionStateSchema = z.object({
  condition_id: z.string(),
  form: z.string(),
  lookback: z.number(),
  threshold: z.number(),
  direction: z.string(),
  current_metric_value: z.number().nullable(),
  is_active: z.boolean(),
  human_rule: z.string(),
})
export type FactorConditionState = z.infer<typeof FactorConditionStateSchema>

export const FactorStateEntrySchema = z.object({
  factor_ticker: z.string(),
  canonical_id: z.string(),
  current_value: z.number(),
  as_of: z.string().nullable(),
  conditions: z.array(FactorConditionStateSchema),
})
export type FactorStateEntry = z.infer<typeof FactorStateEntrySchema>

export const FactorXTaDetailSchema = z.object({
  family: z.string(),
  category: z.string(),
  status: z.string(),
  family_score_pct: z.number().nullable(),
  viable_count: z.number().nullable(),
  tested_count: z.number().nullable(),
  competitive_count: z.number().nullable(),
  representative_count: z.number().nullable(),
  is_provisional: z.boolean().nullable(),
  methodology_mode: z.string().nullable(),
  wfe_pct: z.number().nullable().optional(),
  robustness_ratio: z.number().nullable().optional(),
  robustness_grade: z.string().nullable().optional(),
  total_folds: z.number().nullable().optional(),
  profitable_folds: z.number().nullable().optional(),
  warning_message: z.string().nullable(),
  representatives: z.array(z.record(z.unknown())),
  family_detail: z.record(z.unknown()),
  as_of: z.string().nullable(),
})
export type FactorXTaDetail = z.infer<typeof FactorXTaDetailSchema>

export const FactorSelectionActiveRowSchema = z.object({
  symbol: z.string(),
  horizon: z.string(),
  factor_canonical_id: z.string(),
  rank: z.number().nullable(),
  ic: z.number().nullable(),
  spearman_ic: z.number().nullable().optional(),
  pearson_corr: z.number().nullable().optional(),
  ic_t_stat: z.number().nullable(),
  bh_p_adj: z.number().nullable(),
  lasso_coef: z.number().nullable(),
  relevance_score: z.number().nullable().optional(),
  n_obs: z.number().nullable().optional(),
  selected_reason: z.string().nullable().optional(),
  cusum_status: z.string(),
  low_confidence: z.boolean(),
  next_forced_recal: z.string().nullable(),
  history_n_days: z.number().nullable(),
  last_calibrated_at: z.string(),
  cusum_drift_score: z.number().nullable(),
  is_active: z.boolean(),
})
export type FactorSelectionActiveRow = z.infer<typeof FactorSelectionActiveRowSchema>

export const FactorSelectionStage1RowSchema = z.object({
  symbol: z.string(),
  horizon: z.string(),
  factor_canonical_id: z.string(),
  ic_mean: z.number(),
  spearman_ic: z.number().nullable().optional(),
  pearson_corr: z.number().nullable().optional(),
  ic_tstat: z.number(),
  bh_p_adj: z.number().nullable(),
  relevance_score: z.number().nullable().optional(),
  n_obs: z.number().nullable().optional(),
  selected_reason: z.string().nullable().optional(),
  passed_fdr: z.boolean(),
  regime_start: z.string().nullable(),
  low_confidence: z.boolean(),
  history_n_days: z.number().nullable(),
  calculated_at: z.string(),
})
export type FactorSelectionStage1Row = z.infer<typeof FactorSelectionStage1RowSchema>

export async function getFactorConfig(symbol: string): Promise<FactorConfigResponse> {
  const data = await request(`/factor-signals/${symbol}/config`)
  return FactorConfigResponseSchema.parse(data)
}

export async function updateFactorConfig(
  symbol: string,
  factors: FactorConfigItem[],
): Promise<FactorConfigResponse> {
  const data = await request(`/factor-signals/${symbol}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ factors }),
  })
  return FactorConfigResponseSchema.parse(data)
}

export async function getFactorXTaSignals(
  symbol: string,
  horizon: string,
): Promise<FactorXTaSignalResponse> {
  const data = await request(`/factor-signals/${symbol}/${horizon}`)
  return FactorXTaSignalResponseSchema.parse(data)
}

export async function getFactorXTaDetail(
  symbol: string,
  horizon: string,
  family: string,
  variant: "engine" | "wfo" = "engine",
): Promise<FactorXTaDetail> {
  const data = await request(
    `/factor-signals/${symbol}/${horizon}/detail?family=${encodeURIComponent(family)}&variant=${variant}`,
  )
  return FactorXTaDetailSchema.parse(data)
}

export async function getFactorXTaFactorState(
  symbol: string,
  horizon: string,
  variant: "engine" | "wfo" = "engine",
): Promise<FactorStateEntry[]> {
  const data = await request(
    `/factor-signals/${symbol}/${horizon}/factor-state?variant=${variant}`,
  )
  return z.array(FactorStateEntrySchema).parse(data)
}

export async function enqueueFactorXTaRun(
  symbol: string,
  horizon: string,
): Promise<{ engine_job_id: string; wfo_job_id: string }> {
  return request(`/factor-signals/${symbol}/${horizon}/run`, { method: "POST" })
}

export async function getFactorSelectionActive(
  symbol: string,
  horizon?: string,
): Promise<FactorSelectionActiveRow[]> {
  const qs = horizon ? `?horizon=${encodeURIComponent(horizon)}` : ""
  const data = await request(`/factor-selection/stocks/${symbol}/active${qs}`)
  return z.array(FactorSelectionActiveRowSchema).parse(data)
}

export async function getFactorSelectionStage1Cache(
  symbol: string,
  horizon?: string,
): Promise<FactorSelectionStage1Row[]> {
  const qs = horizon ? `?horizon=${encodeURIComponent(horizon)}` : ""
  const data = await request(`/factor-selection/stocks/${symbol}/stage1-cache${qs}`)
  return z.array(FactorSelectionStage1RowSchema).parse(data)
}

export async function triggerFactorSelectionRecalibration(
  symbol: string,
): Promise<{ status: string; job_id: string; symbol: string }> {
  return request(`/factor-selection/stocks/${symbol}/trigger-recalibration`, { method: "POST" })
}
