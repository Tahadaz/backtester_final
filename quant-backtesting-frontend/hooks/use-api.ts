"use client"

import useSWR from "swr"
import type {
  AvailabilityCalendar,
  Artifact,
  BatchScore,
  Dataset,
  FamilyCombinedSignal,
  RegimeConsensus,
  FillRow,
  LeaderboardRow,
  LevelsResult,
  MarketCatalogRow,
  MarketHealth,
  MarketRefreshRun,
  MarketSymbolRow,
  MeanReversionReport,
  MetricRow,
  OhlcvHistory,
  OhlcvPreview,
  PositionRow,
  Run,
  RunIntegrity,
  RunRisk,
  RunSignificanceRow,
  RunWalkForward,
  SavedStrategy,
  SavedStrategyListItem,
  StrategyAllocation,
  ExecutionPlan,
  SignalConsensus,
  SignalZoneChart,
  SizingResult,
  StockMaster,
  StrategyDecision,
  UniverseStock,
  UploadFormatReference,
  VariantBacktest,
  VariantDetail,
} from "@/lib/api"
import {
  fetchBatchScores,
  fetchExecution,
  fetchRegimeConsensus,
  fetchFamilyEnsemble,
  fetchSizing,
  fetchLevels,
  fetchMasiTickers,
  fetchSignalConsensus,
  fetchSignalZoneChart,
  fetchSmaEnsemble,
  fetchStrategies,
  fetchStrategy,
  fetchStrategyAllocation,
  fetchUniverse,
  fetchVariantBacktest,
  fetchVariantDetail,
} from "@/lib/api"
import type { MasiTicker } from "@/lib/api"

const API_BASE = "/api"

async function apiFetcher<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Accept": "application/json" },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error")
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

export function useRuns(params?: {
  status?: string
  run_type?: string
  limit?: number
  offset?: number
}) {
  const qs = new URLSearchParams()
  if (params?.status) qs.set("status", params.status)
  if (params?.run_type) qs.set("run_type", params.run_type)
  if (params?.limit) qs.set("limit", String(params.limit))
  if (params?.offset) qs.set("offset", String(params.offset))
  const q = qs.toString()

  return useSWR<Run[]>(`/runs${q ? `?${q}` : ""}`, apiFetcher, {
    refreshInterval: 5000,
    revalidateOnFocus: true,
  })
}

export function useRun(runId: string | null) {
  const shouldPoll = (data: Run | undefined) => {
    if (!data) return 2000
    const status = data.status
    if (status === "created" || status === "queued" || status === "running") {
      return 2000
    }
    return 0
  }

  return useSWR<Run>(
    runId ? `/runs/${runId}` : null,
    apiFetcher,
    {
      refreshInterval: shouldPoll,
      revalidateOnFocus: true,
    }
  )
}

export function useLeaderboard(
  runId: string | null,
  params?: { symbol?: string; best_only?: boolean }
) {
  const qs = new URLSearchParams()
  if (params?.symbol) qs.set("symbol", params.symbol)
  if (params?.best_only !== undefined)
    qs.set("best_only", String(params.best_only))
  const q = qs.toString()

  return useSWR<LeaderboardRow[]>(
    runId ? `/runs/${runId}/leaderboard${q ? `?${q}` : ""}` : null,
    apiFetcher
  )
}

export function useRunDecisions(
  runId: string | null,
  params?: { symbol?: string; best_only?: boolean }
) {
  const qs = new URLSearchParams()
  if (params?.symbol) qs.set("symbol", params.symbol)
  if (params?.best_only !== undefined) qs.set("best_only", String(params.best_only))
  const q = qs.toString()

  return useSWR<StrategyDecision[]>(
    runId ? `/runs/${runId}/decisions${q ? `?${q}` : ""}` : null,
    apiFetcher
  )
}

export function useMetrics(runId: string | null) {
  return useSWR<MetricRow[]>(
    runId ? `/runs/${runId}/metrics` : null,
    apiFetcher
  )
}

export function useFills(
  runId: string | null,
  params?: { symbol?: string; limit?: number; cursor?: string }
) {
  const qs = new URLSearchParams()
  if (params?.symbol) qs.set("symbol", params.symbol)
  if (params?.limit) qs.set("limit", String(params.limit))
  if (params?.cursor) qs.set("cursor", params.cursor)
  const q = qs.toString()

  return useSWR<FillRow[]>(
    runId ? `/runs/${runId}/fills${q ? `?${q}` : ""}` : null,
    apiFetcher
  )
}

export function usePositionLedger(
  runId: string | null,
  params?: { symbol?: string; limit?: number; cursor?: string }
) {
  const qs = new URLSearchParams()
  if (params?.symbol) qs.set("symbol", params.symbol)
  if (params?.limit) qs.set("limit", String(params.limit))
  if (params?.cursor) qs.set("cursor", params.cursor)
  const q = qs.toString()

  return useSWR<PositionRow[]>(
    runId ? `/runs/${runId}/position-ledger${q ? `?${q}` : ""}` : null,
    apiFetcher
  )
}

export function useArtifacts(
  runId: string | null,
  params?: { symbol?: string }
) {
  const qs = new URLSearchParams()
  if (params?.symbol) qs.set("symbol", params.symbol)
  const q = qs.toString()

  return useSWR<Artifact[]>(
    runId ? `/runs/${runId}/artifacts${q ? `?${q}` : ""}` : null,
    apiFetcher,
    {
      refreshInterval: 120000,
      revalidateOnFocus: true,
    }
  )
}

export function useRunIntegrity(runId: string | null) {
  return useSWR<RunIntegrity>(
    runId ? `/runs/${runId}/integrity` : null,
    apiFetcher
  )
}

export function useRunWalkForward(runId: string | null) {
  return useSWR<RunWalkForward>(
    runId ? `/runs/${runId}/walk-forward` : null,
    apiFetcher
  )
}

export function useRunSignificance(runId: string | null) {
  return useSWR<RunSignificanceRow[]>(
    runId ? `/runs/${runId}/significance` : null,
    apiFetcher
  )
}

export function useRunRisk(runId: string | null) {
  return useSWR<RunRisk>(
    runId ? `/runs/${runId}/risk` : null,
    apiFetcher
  )
}

export function useRunMeanReversion(runId: string | null) {
  return useSWR<MeanReversionReport>(
    runId ? `/runs/${runId}/mean-reversion` : null,
    apiFetcher
  )
}

export function useDatasets() {
  return useSWR<Dataset[]>("/datasets", apiFetcher, {
    refreshInterval: 15000,
    revalidateOnFocus: true,
  })
}

export function useMasiTickers() {
  return useSWR<MasiTicker[]>(
    "/market-data/masi-tickers",
    () => fetchMasiTickers(),
    { revalidateOnFocus: false }
  )
}

export function useMarketCatalog() {
  return useSWR<MarketCatalogRow[]>(
    "/market-data/catalog",
    apiFetcher,
    { refreshInterval: 30000, revalidateOnFocus: true }
  )
}

export function useMarketSymbols(params?: { timeframe?: string }) {
  const qs = new URLSearchParams()
  if (params?.timeframe) qs.set("timeframe", params.timeframe)
  const q = qs.toString()

  return useSWR<MarketSymbolRow[]>(
    `/market-data/symbols${q ? `?${q}` : ""}`,
    apiFetcher,
    { refreshInterval: 30000, revalidateOnFocus: true }
  )
}

export function useTrackedStocks(params?: { is_active?: boolean }) {
  const qs = new URLSearchParams()
  if (params?.is_active !== undefined) qs.set("is_active", String(params.is_active))
  const q = qs.toString()

  return useSWR<StockMaster[]>(
    `/market-data/stocks${q ? `?${q}` : ""}`,
    apiFetcher,
    { refreshInterval: 60000, revalidateOnFocus: true }
  )
}

export function useRefreshRun(refreshRunId: string | null) {
  const shouldPoll = (data: MarketRefreshRun | undefined) => {
    if (!data) return 2000
    if (data.status === "queued" || data.status === "running") return 2000
    return 0
  }

  return useSWR<MarketRefreshRun>(
    refreshRunId ? `/market-data/refresh/${refreshRunId}` : null,
    apiFetcher,
    { refreshInterval: shouldPoll, revalidateOnFocus: true }
  )
}

export function useMarketHealth() {
  return useSWR<MarketHealth>(
    "/market-data/health",
    apiFetcher,
    { refreshInterval: 30000, revalidateOnFocus: true }
  )
}

export function useStockOhlcvPreview(symbol: string | null, params?: { limit?: number }) {
  const qs = new URLSearchParams()
  if (params?.limit) qs.set("limit", String(params.limit))
  const q = qs.toString()

  return useSWR<OhlcvPreview>(
    symbol ? `/market-data/stocks/${symbol}/ohlcv-preview${q ? `?${q}` : ""}` : null,
    apiFetcher
  )
}

export function useUploadFormatReference() {
  return useSWR<UploadFormatReference>(
    "/market-data/upload-format-reference",
    apiFetcher,
    { revalidateOnFocus: false }
  )
}

export function useStockOhlcvHistory(symbol: string | null, params?: { timeframe?: string }) {
  const qs = new URLSearchParams()
  if (params?.timeframe) qs.set("timeframe", params.timeframe)
  const q = qs.toString()

  return useSWR<OhlcvHistory>(
    symbol ? `/market-data/stocks/${symbol}/ohlcv-history${q ? `?${q}` : ""}` : null,
    apiFetcher
  )
}

export function useStockAvailabilityCalendar(symbol: string | null, params?: { timeframe?: string }) {
  const qs = new URLSearchParams()
  if (params?.timeframe) qs.set("timeframe", params.timeframe)
  const q = qs.toString()

  return useSWR<AvailabilityCalendar>(
    symbol ? `/market-data/stocks/${symbol}/availability-calendar${q ? `?${q}` : ""}` : null,
    apiFetcher
  )
}

export function useSmaEnsemble(symbol: string | null, horizon: string | null, costBps?: number) {
  const key =
    symbol && horizon
      ? `/strategy/signal/sma-ensemble?s=${symbol}&h=${horizon}&c=${costBps ?? ""}`
      : null
  return useSWR<FamilyCombinedSignal>(
    key,
    () => fetchSmaEnsemble({ symbol: symbol!, horizon: horizon!, cost_bps: costBps }),
    { revalidateOnFocus: false }
  )
}

export function useFamilyEnsemble(family: string | null, symbol: string | null, horizon: string | null, costBps?: number, cooldownBars?: number) {
  const key =
    family && symbol && horizon
      ? `/strategy/signal/family-ensemble?f=${family}&s=${symbol}&h=${horizon}&c=${costBps ?? ""}&cd=${cooldownBars ?? ""}`
      : null
  return useSWR<FamilyCombinedSignal>(
    key,
    () => fetchFamilyEnsemble({ family: family!, symbol: symbol!, horizon: horizon!, cost_bps: costBps, cooldown_bars: cooldownBars }),
    { revalidateOnFocus: false }
  )
}

export function useVariantBacktest(
  variantId: string | null,
  symbol: string | null,
  horizon: string | null,
  costBps?: number,
  cooldownBars?: number,
) {
  const key =
    variantId && symbol && horizon
      ? `/strategy/signal/variant-backtest?v=${variantId}&s=${symbol}&h=${horizon}&c=${costBps ?? ""}&cd=${cooldownBars ?? ""}`
      : null
  return useSWR<VariantBacktest>(
    key,
    () =>
      fetchVariantBacktest({
        symbol: symbol!,
        variant_id: variantId!,
        horizon: horizon!,
        cost_bps: costBps,
        cooldown_bars: cooldownBars,
      }),
    { revalidateOnFocus: false }
  )
}

export function useVariantDetail(
  variantId: string | null,
  symbol: string | null,
  horizon: string | null,
  costBps?: number,
  cooldownBars?: number,
) {
  const key =
    variantId && symbol && horizon
      ? `/strategy/signal/variant-detail?v=${variantId}&s=${symbol}&h=${horizon}&c=${costBps ?? ""}&cd=${cooldownBars ?? ""}`
      : null
  return useSWR<VariantDetail>(
    key,
    () =>
      fetchVariantDetail({
        symbol: symbol!,
        horizon: horizon!,
        variant_id: variantId!,
        cost_bps: costBps,
        cooldown_bars: cooldownBars,
      }),
    { revalidateOnFocus: false }
  )
}

export function useBatchScores(symbols: string[], horizon: string, cooldownBars?: number) {
  const key =
    symbols.length > 0
      ? `/strategy/signal/batch-scores?h=${horizon}&n=${symbols.length}&cd=${cooldownBars ?? ""}`
      : null
  return useSWR<BatchScore[]>(
    key,
    () => fetchBatchScores({ symbols, horizon, cooldown_bars: cooldownBars }),
    { revalidateOnFocus: false }
  )
}

// ── Signal Engine — Regime Consensus (Layer H) ──────────────────────────────

export function useRegimeConsensus(
  symbol: string | null,
  horizon: string | null,
  cooldownBars?: number,
) {
  const key =
    symbol && horizon
      ? `/strategy/signal/regime-consensus?s=${symbol}&h=${horizon}&cd=${cooldownBars ?? ""}`
      : null
  return useSWR<RegimeConsensus>(
    key,
    () =>
      fetchRegimeConsensus({
        symbol: symbol!,
        horizon: horizon!,
        cooldown_bars: cooldownBars,
      }),
    { revalidateOnFocus: false }
  )
}

// ── Strategy Plan ─────────────────────────────────────────────────────────────

export function useUniverse(
  horizon: string,
  params?: {
    min_bars?: number
    min_abs_signal?: number
    min_adv20?: number
    sector_filter?: string[]
    cost_bps?: number
    cooldown_bars?: number
    sort_by?: "adv20" | "signal_score"
    sort_dir?: "asc" | "desc"
  },
) {
  const key = `/strategy/plan/universe?h=${horizon}&mb=${params?.min_bars ?? ""}&ms=${params?.min_abs_signal ?? ""}&ma=${params?.min_adv20 ?? ""}&sf=${params?.sector_filter?.join(",") ?? ""}&sb=${params?.sort_by ?? ""}&sd=${params?.sort_dir ?? ""}`
  return useSWR<UniverseStock[]>(
    key,
    () =>
      fetchUniverse({
        horizon,
        min_bars: params?.min_bars,
        min_abs_signal: params?.min_abs_signal,
        min_adv20: params?.min_adv20,
        sector_filter: params?.sector_filter,
        cost_bps: params?.cost_bps,
        cooldown_bars: params?.cooldown_bars,
        sort_by: params?.sort_by,
        sort_dir: params?.sort_dir,
      }),
    { revalidateOnFocus: false }
  )
}

export function useStrategyAllocation(
  symbols: string[],
  params: {
    total_capital_mad: number
    method?: "hrp"
    timeframe?: string
    lookback_bars?: number
    manual_overrides_by_symbol?: Record<string, number>
  },
) {
  const symbolKey = [...symbols].sort().join(",")
  const manualKey = JSON.stringify(
    Object.fromEntries(Object.entries(params.manual_overrides_by_symbol ?? {}).sort(([a], [b]) => a.localeCompare(b)))
  )
  const key = symbols.length > 0
    ? `/strategy/plan/allocation?s=${symbolKey}&c=${params.total_capital_mad}&m=${params.method ?? "hrp"}&t=${params.timeframe ?? ""}&lb=${params.lookback_bars ?? ""}&mo=${manualKey}`
    : null

  return useSWR<StrategyAllocation>(
    key,
    () =>
      fetchStrategyAllocation({
        symbols,
        total_capital_mad: params.total_capital_mad,
        method: params.method,
        timeframe: params.timeframe,
        lookback_bars: params.lookback_bars,
        manual_overrides_by_symbol: params.manual_overrides_by_symbol,
      }),
    { revalidateOnFocus: false },
  )
}

export function useLevels(
  symbol: string | null,
  horizon: string,
  params?: {
    execution_holding_bars?: number
    left_bars?: number
    right_bars?: number
    lookback?: number
    max_levels?: number
  },
) {
  const key = symbol
    ? `/strategy/plan/levels?s=${symbol}&h=${horizon}&eh=${params?.execution_holding_bars ?? ""}&lb=${params?.left_bars ?? ""}&rb=${params?.right_bars ?? ""}&lk=${params?.lookback ?? ""}`
    : null
  return useSWR<LevelsResult>(
    key,
    () =>
      fetchLevels({
        symbol: symbol!,
        horizon,
        execution_holding_bars: params?.execution_holding_bars,
        left_bars: params?.left_bars,
        right_bars: params?.right_bars,
        lookback: params?.lookback,
        max_levels: params?.max_levels,
      }),
    { revalidateOnFocus: false }
  )
}

// ── Saved Strategies ─────────────────────────────────────────────────────────

export function useStrategies(status?: string) {
  const key = `/strategy/plan/strategies?s=${status ?? ""}`
  return useSWR<SavedStrategyListItem[]>(
    key,
    () => fetchStrategies(status),
    { revalidateOnFocus: false }
  )
}

export function useStrategy(id: string | null) {
  return useSWR<SavedStrategy>(
    id ? `/strategy/plan/strategies/${id}` : null,
    () => fetchStrategy(id!),
    { revalidateOnFocus: false }
  )
}

// ── Signal Consensus ─────────────────────────────────────────────────────────

export function useSignalConsensus(
  symbol: string | null,
  horizon: string,
  enabledFamilies: string[],
  costBps?: number,
  cooldownBars?: number,
) {
  const famKey = [...enabledFamilies].sort().join(",")
  const key =
    symbol && enabledFamilies.length > 0
      ? `/strategy/plan/signal-consensus?s=${symbol}&h=${horizon}&f=${famKey}&c=${costBps ?? ""}&cd=${cooldownBars ?? ""}`
      : null
  return useSWR<SignalConsensus>(
    key,
    () =>
      fetchSignalConsensus({
        symbol: symbol!,
        horizon,
        enabled_families: enabledFamilies,
        cost_bps: costBps,
        cooldown_bars: cooldownBars,
      }),
    { revalidateOnFocus: false }
  )
}

// ── Signal Zone Chart ────────────────────────────────────────────────────────

export function useSignalZoneChart(
  symbol: string | null,
  horizon: string,
  enabledFamilies: string[],
) {
  const famKey = [...enabledFamilies].sort().join(",")
  const key =
    symbol && enabledFamilies.length > 0
      ? `/strategy/signal/zone-chart?s=${symbol}&h=${horizon}&f=${famKey}`
      : null
  return useSWR<SignalZoneChart>(
    key,
    () =>
      fetchSignalZoneChart({
        symbol: symbol!,
        horizon,
        enabled_families: enabledFamilies,
      }),
    { revalidateOnFocus: false },
  )
}

// ── Execution Plan ───────────────────────────────────────────────────────────

export function useExecution(
  symbol: string | null,
  horizon: string,
  params: {
    enabled_families: string[]
    execution_holding_bars?: number
    side_policy: string
    entry_threshold?: number
    atr_multiplier?: number
    buffer_pct?: number
    min_rr?: number
    consensus_override?: number | null
  },
) {
  const famKey = [...params.enabled_families].sort().join(",")
  const key = symbol
    ? `/strategy/plan/execution?s=${symbol}&h=${horizon}&f=${famKey}&eh=${params.execution_holding_bars ?? ""}&sp=${params.side_policy}&et=${params.entry_threshold ?? ""}&am=${params.atr_multiplier ?? ""}&bp=${params.buffer_pct ?? ""}&rr=${params.min_rr ?? ""}&co=${params.consensus_override ?? ""}`
    : null
  return useSWR<ExecutionPlan>(
    key,
    () =>
      fetchExecution({
        symbol: symbol!,
        horizon,
        enabled_families: params.enabled_families,
        execution_holding_bars: params.execution_holding_bars,
        side_policy: params.side_policy,
        entry_threshold: params.entry_threshold,
        atr_multiplier: params.atr_multiplier,
        buffer_pct: params.buffer_pct,
        min_rr: params.min_rr,
        consensus_override: params.consensus_override,
      }),
    { revalidateOnFocus: false }
  )
}

// ── Sizing ────────────────────────────────────────────────────────────────────

export function useSizing(
  params: {
    stocks: Array<{
      symbol: string
      entry_price: number
      stop_price: number
      atr_pct?: number
      consensus?: number
      sector?: string
      status?: string
    }>
    account_equity: number
    kelly_modifier: number
    allocation_method: string
    max_position_pct: number
    max_sector_pct: number
    win_rate: number
    avg_wl_ratio: number
    focused_symbol?: string | null
  } | null,
) {
  const stocksKey = params
    ? params.stocks.map((s) => `${s.symbol}:${s.entry_price}:${s.stop_price}:${s.status ?? ""}`).join("|")
    : ""
  const key = params && params.stocks.length > 0
    ? `/strategy/plan/sizing?sk=${stocksKey}&eq=${params.account_equity}&km=${params.kelly_modifier}&m=${params.allocation_method}&mp=${params.max_position_pct}&ms=${params.max_sector_pct}&wr=${params.win_rate}&wl=${params.avg_wl_ratio}&fs=${params.focused_symbol ?? ""}`
    : null
  return useSWR<SizingResult>(
    key,
    () =>
      fetchSizing({
        stocks: params!.stocks,
        account_equity: params!.account_equity,
        kelly_modifier: params!.kelly_modifier,
        allocation_method: params!.allocation_method,
        max_position_pct: params!.max_position_pct,
        max_sector_pct: params!.max_sector_pct,
        win_rate: params!.win_rate,
        avg_wl_ratio: params!.avg_wl_ratio,
        focused_symbol: params!.focused_symbol,
      }),
    { revalidateOnFocus: false }
  )
}
