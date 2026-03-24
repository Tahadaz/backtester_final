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
})
export type LeaderboardRow = z.infer<typeof LeaderboardRowSchema>

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

class ApiError extends Error {
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

export async function uploadExcelFile(file: File): Promise<{ dataset_id: string; job_id: string }> {
  const form = new FormData()
  form.append("file", file)
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
  { intervalMs = 1500, timeoutMs = 30_000 } = {},
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
})
export type MarketCatalogRow = z.infer<typeof MarketCatalogRowSchema>

export async function listMarketCatalog(): Promise<MarketCatalogRow[]> {
  const rows = await request<unknown[]>("/market-data/catalog")
  return z.array(MarketCatalogRowSchema).parse(rows)
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
  best_variant_id: z.string().default(""),
})
export type FamilyCombinedSignal = z.infer<typeof FamilyCombinedSignalSchema>

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
}): Promise<FamilyCombinedSignal> {
  const payload: Record<string, unknown> = {
    family: body.family,
    symbol: body.symbol,
    horizon: body.horizon,
    timeframe: body.timeframe ?? "1D",
  }
  if (body.cost_bps != null) payload.cost_bps = body.cost_bps
  if (body.cooldown_bars != null) payload.cooldown_bars = body.cooldown_bars
  const raw = await request<unknown>("/strategy/signal/family-ensemble", {
    method: "POST",
    body: JSON.stringify(payload),
  })
  return FamilyCombinedSignalSchema.parse(raw)
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
  signal_value: z.number().default(0),
  signal_label: z.string().optional(),
  correlated_with: z.string().nullable().optional(),
  correlated_with_label: z.string().nullable().optional(),
  correlation: z.number().nullable().optional(),
  threshold_score: z.number().nullable().optional(),
  viability_detail: z.string().nullable().optional(),
  selection_status: z.string().optional(),
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

export async function fetchVariantDetail(body: {
  symbol: string
  horizon: string
  timeframe?: string
  variant_id: string
  cost_bps?: number
  cooldown_bars?: number
}): Promise<VariantDetail> {
  const payload: Record<string, unknown> = {
    symbol: body.symbol,
    horizon: body.horizon,
    timeframe: body.timeframe ?? "1D",
    variant_id: body.variant_id,
  }
  if (body.cost_bps != null) payload.cost_bps = body.cost_bps
  if (body.cooldown_bars != null) payload.cooldown_bars = body.cooldown_bars
  const raw = await request<unknown>("/strategy/signal/variant-detail", {
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
}): Promise<VariantBacktest> {
  const payload: Record<string, unknown> = {
    symbol: body.symbol,
    variant_id: body.variant_id,
    horizon: body.horizon ?? "medium",
    timeframe: body.timeframe ?? "1D",
  }
  if (body.cost_bps != null) payload.cost_bps = body.cost_bps
  if (body.cooldown_bars != null) payload.cooldown_bars = body.cooldown_bars
  const raw = await request<unknown>("/strategy/signal/variant-backtest", {
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
}): Promise<BatchScore[]> {
  const raw = await request<unknown[]>("/strategy/signal/batch-scores", {
    method: "POST",
    body: JSON.stringify({
      symbols: body.symbols,
      horizon: body.horizon,
      cost_bps: body.cost_bps ?? 10,
      cooldown_bars: body.cooldown_bars ?? 0,
    }),
  })
  return z.array(BatchScoreSchema).parse(raw)
}
