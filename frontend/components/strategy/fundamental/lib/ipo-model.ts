// Interactive DCF + comparables model for the T2S IPO.
//
// This is a self-contained, client-side valuation engine seeded from the AMMC
// prospectus so the user can run THEIR OWN analysis: edit growth, margins, WACC,
// terminal g, tax/BFR/capex intensity, or peer multiples, and watch fair value /
// upside / sensitivity recompute. The "base" scenario reproduces the prospectus
// exactly (fair value 301 MAD/share at WACC 10.28%, g 2.0%), which doubles as a
// correctness check (see ipo-model.selftest.ts).
//
// Model matches the prospectus FCFF definition verbatim:
//   FCFF_t = EBE_t + IS_theorique_sur_le_REX_t + variation_BFR_t + investissements_t
// expressed here as intensity ratios on revenue so growth/margins are editable:
//   FCFF_t = Revenue_t * (ebeMargin_t - taxPctRev_t - bfrPctRev_t - capexPctRev_t)
// Discounting uses the mid-year convention (period = index + 0.5), as the note does.

import { IPO_T2S, type IpoPeer, type IpoPeerStats } from "./ipo-data"

export type IpoScenarioKey = "bear" | "base" | "bull"

export type IpoDcfInputs = {
  revenueBase: number // last actual revenue (2025), MMAD
  years: string[] // explicit forecast labels, e.g. ["2026e".."2030p"]
  revenueGrowth: number[] // per explicit year (decimals)
  ebeMargin: number[] // EBE / revenue per year
  taxPctRev: number[] // cash tax (IS theorique sur le REX) as % of revenue, stored positive
  bfrPctRev: number[] // variation BFR as % of revenue, stored positive (a cash outflow)
  capexPctRev: number[] // investissements as % of revenue, stored positive (a cash outflow)
  wacc: number
  terminalGrowth: number
  terminalEbeMargin: number
  terminalTaxPctRev: number
  terminalBfrPctRev: number
  terminalCapexPctRev: number
  netDebt: number // MMAD (positive = net debt subtracted from EV)
  shares: number // million shares
  offerPrice: number // MAD / share
  midYear: boolean
}

export type IpoDcfYear = {
  year: string
  revenue: number
  ebe: number
  tax: number
  deltaBfr: number
  capex: number
  fcff: number
  period: number
  discountFactor: number
  pv: number
}

export type IpoDcfResult = {
  rows: IpoDcfYear[]
  normativeRevenue: number
  normativeFcff: number
  explicitPv: number
  terminalValue: number
  terminalPeriod: number
  terminalPv: number
  terminalPvPct: number
  enterpriseValue: number
  equityValue: number
  fairValuePerShare: number
  upsideVsOffer: number
  revenueCagr: number
  valid: boolean // false when WACC <= g (Gordon undefined)
}

function round2(x: number): number {
  return Math.round(x * 100) / 100
}

export function computeDcf(inputs: IpoDcfInputs): IpoDcfResult {
  const n = inputs.years.length
  const rows: IpoDcfYear[] = []
  let revenue = inputs.revenueBase
  let explicitPv = 0
  for (let i = 0; i < n; i++) {
    revenue = revenue * (1 + inputs.revenueGrowth[i])
    const ebe = revenue * inputs.ebeMargin[i]
    const tax = -revenue * inputs.taxPctRev[i]
    const deltaBfr = -revenue * inputs.bfrPctRev[i]
    const capex = -revenue * inputs.capexPctRev[i]
    const fcff = ebe + tax + deltaBfr + capex
    const period = inputs.midYear ? i + 0.5 : i + 1
    const discountFactor = 1 / Math.pow(1 + inputs.wacc, period)
    const pv = fcff * discountFactor
    explicitPv += pv
    rows.push({ year: inputs.years[i], revenue, ebe, tax, deltaBfr, capex, fcff, period, discountFactor, pv })
  }

  const valid = inputs.wacc > inputs.terminalGrowth
  const lastRevenue = rows.length ? rows[rows.length - 1].revenue : inputs.revenueBase
  const normativeRevenue = lastRevenue * (1 + inputs.terminalGrowth)
  const normativeFcff =
    normativeRevenue *
    (inputs.terminalEbeMargin - inputs.terminalTaxPctRev - inputs.terminalBfrPctRev - inputs.terminalCapexPctRev)
  const terminalValue = valid ? normativeFcff / (inputs.wacc - inputs.terminalGrowth) : NaN
  // Terminal value sits at the end of the last explicit year; mid-year keeps it at N - 0.5.
  const terminalPeriod = inputs.midYear ? n - 0.5 : n
  const terminalDf = 1 / Math.pow(1 + inputs.wacc, terminalPeriod)
  const terminalPv = valid ? terminalValue * terminalDf : NaN
  const enterpriseValue = explicitPv + (valid ? terminalPv : 0)
  const equityValue = enterpriseValue - inputs.netDebt
  const fairValuePerShare = inputs.shares > 0 ? equityValue / inputs.shares : NaN
  const upsideVsOffer = inputs.offerPrice > 0 ? fairValuePerShare / inputs.offerPrice - 1 : NaN
  const revenueCagr = n > 0 ? Math.pow(lastRevenue / inputs.revenueBase, 1 / n) - 1 : 0

  return {
    rows,
    normativeRevenue,
    normativeFcff,
    explicitPv,
    terminalValue,
    terminalPeriod,
    terminalPv,
    terminalPvPct: valid && enterpriseValue !== 0 ? terminalPv / enterpriseValue : NaN,
    enterpriseValue,
    equityValue,
    fairValuePerShare,
    upsideVsOffer,
    revenueCagr,
    valid,
  }
}

// ---- Comparables (equity value bridges as the prospectus builds them) ----

export function compsEvEbeFairValue(args: {
  multiple: number
  ebe: number
  netDebt: number
  otherAdjustments: number // e.g. Cyclopharma acquisition (102 MMAD)
  shares: number
}): { enterpriseValue: number; equityValue: number; perShare: number } {
  const enterpriseValue = args.multiple * args.ebe
  const equityValue = enterpriseValue - args.netDebt - args.otherAdjustments
  return { enterpriseValue, equityValue, perShare: args.shares > 0 ? equityValue / args.shares : NaN }
}

export function compsPeFairValue(args: { multiple: number; netIncome: number; shares: number }): {
  equityValue: number
  perShare: number
} {
  const equityValue = args.multiple * args.netIncome
  return { equityValue, perShare: args.shares > 0 ? equityValue / args.shares : NaN }
}

function averageNullable(values: Array<number | null>): number | null {
  const finite = values.filter((value): value is number => Number.isFinite(value))
  if (!finite.length) return null
  return finite.reduce((sum, value) => sum + value, 0) / finite.length
}

function medianNullable(values: Array<number | null>): number | null {
  const finite = values.filter((value): value is number => Number.isFinite(value)).sort((a, b) => a - b)
  if (!finite.length) return null
  const mid = Math.floor(finite.length / 2)
  return finite.length % 2 === 0 ? (finite[mid - 1] + finite[mid]) / 2 : finite[mid]
}

export function recomputeIpoPeerStats(peers: IpoPeer[]): IpoPeerStats {
  return {
    mean: {
      evEbe2026e: averageNullable(peers.map((peer) => peer.evEbe2026e)),
      evEbe2027p: averageNullable(peers.map((peer) => peer.evEbe2027p)),
      pe2026e: averageNullable(peers.map((peer) => peer.pe2026e)),
      pe2027p: averageNullable(peers.map((peer) => peer.pe2027p)),
    },
    median: {
      evEbe2026e: medianNullable(peers.map((peer) => peer.evEbe2026e)),
      evEbe2027p: medianNullable(peers.map((peer) => peer.evEbe2027p)),
      pe2026e: medianNullable(peers.map((peer) => peer.pe2026e)),
      pe2027p: medianNullable(peers.map((peer) => peer.pe2027p)),
    },
  }
}

// ---- Sensitivity ----

export type SensitivityAxis = "wacc" | "terminalGrowth" | "terminalEbeMargin" | "revenueGrowthShift"

// Apply an axis override to a copy of the inputs. revenueGrowthShift adds an
// absolute delta (in decimals) to every explicit-year growth rate.
function withAxis(inputs: IpoDcfInputs, axis: SensitivityAxis, value: number): IpoDcfInputs {
  if (axis === "wacc") return { ...inputs, wacc: value }
  if (axis === "terminalGrowth") return { ...inputs, terminalGrowth: value }
  if (axis === "terminalEbeMargin") return { ...inputs, terminalEbeMargin: value }
  return { ...inputs, revenueGrowth: inputs.revenueGrowth.map((g) => g + value) }
}

export function sensitivityGrid(args: {
  inputs: IpoDcfInputs
  xAxis: SensitivityAxis
  yAxis: SensitivityAxis
  xs: number[]
  ys: number[]
  metric?: "perShare" | "upside"
}): Array<Array<number>> {
  const metric = args.metric ?? "perShare"
  return args.ys.map((y) =>
    args.xs.map((x) => {
      const inputs = withAxis(withAxis(args.inputs, args.xAxis, x), args.yAxis, y)
      const res = computeDcf(inputs)
      return metric === "upside" ? res.upsideVsOffer : res.fairValuePerShare
    }),
  )
}

// ---- Base inputs seeded from the prospectus (single source of truth) ----

function flowRow(key: string): number[] {
  const row = IPO_T2S.dcfFlows.find((r) => r.key === key)
  if (!row) throw new Error(`ipo-model: missing dcf flow row ${key}`)
  return row.values.map((v) => v ?? 0)
}

// Build the base (prospectus) inputs by deriving intensity ratios from the
// prospectus MMAD arrays, so "base" reproduces the note exactly.
export function buildBaseInputs(): IpoDcfInputs {
  const revenueRow = IPO_T2S.bp.find((r) => r.key === "revenue")
  if (!revenueRow) throw new Error("ipo-model: missing revenue bp row")
  // bpYears: 0..7 = 2023..2030p; explicit forecast = indices 3..7 (2026e..2030p).
  const revenueSeries = revenueRow.values.map((v) => v ?? 0)
  const revenueBase = revenueSeries[2] // 2025 actual
  const explicitRevenue = revenueSeries.slice(3) // 2026e..2030p
  const years = IPO_T2S.bpYears.slice(3)

  const ebe = flowRow("ebe").slice(0, 5)
  const tax = flowRow("tax").slice(0, 5)
  const wc = flowRow("wc").slice(0, 5)
  const capex = flowRow("capex").slice(0, 5)

  const revenueGrowth: number[] = []
  let prev = revenueBase
  for (const r of explicitRevenue) {
    revenueGrowth.push(r / prev - 1)
    prev = r
  }
  const ebeMargin = explicitRevenue.map((r, i) => ebe[i] / r)
  const taxPctRev = explicitRevenue.map((r, i) => Math.abs(tax[i]) / r)
  const bfrPctRev = explicitRevenue.map((r, i) => Math.abs(wc[i]) / r)
  const capexPctRev = explicitRevenue.map((r, i) => Math.abs(capex[i]) / r)

  // Normatif column (index 5) of the prospectus flow table.
  const lastRevenue = explicitRevenue[explicitRevenue.length - 1]
  const terminalGrowth = 0.02
  const normativeRevenue = lastRevenue * (1 + terminalGrowth)
  const terminalEbeMargin = flowRow("ebe")[5] / normativeRevenue
  const terminalTaxPctRev = Math.abs(flowRow("tax")[5]) / normativeRevenue
  const terminalBfrPctRev = Math.abs(flowRow("wc")[5]) / normativeRevenue
  const terminalCapexPctRev = Math.abs(flowRow("capex")[5]) / normativeRevenue

  return {
    revenueBase,
    years,
    revenueGrowth,
    ebeMargin,
    taxPctRev,
    bfrPctRev,
    capexPctRev,
    wacc: 0.1028,
    terminalGrowth,
    terminalEbeMargin,
    terminalTaxPctRev,
    terminalBfrPctRev,
    terminalCapexPctRev,
    netDebt: IPO_T2S.meta.netDebt2025Mmad,
    shares: IPO_T2S.meta.sharesOutstanding / 1_000_000,
    offerPrice: IPO_T2S.meta.offerPrice,
    midYear: true,
  }
}

// Illustrative bull/bear presets: the user can still edit every field afterwards.
// These are NOT from the prospectus - only "base" is.
export function buildScenarioInputs(scenario: IpoScenarioKey): IpoDcfInputs {
  const base = buildBaseInputs()
  if (scenario === "base") return base
  if (scenario === "bull") {
    return {
      ...base,
      revenueGrowth: base.revenueGrowth.map((g) => g + 0.03),
      ebeMargin: base.ebeMargin.map((m) => m + 0.02),
      terminalEbeMargin: base.terminalEbeMargin + 0.02,
      terminalGrowth: base.terminalGrowth + 0.005,
      wacc: base.wacc - 0.005,
    }
  }
  // bear
  return {
    ...base,
    revenueGrowth: base.revenueGrowth.map((g) => Math.max(0, g - 0.04)),
    ebeMargin: base.ebeMargin.map((m) => Math.max(0, m - 0.02)),
    terminalEbeMargin: Math.max(0, base.terminalEbeMargin - 0.02),
    terminalGrowth: Math.max(0, base.terminalGrowth - 0.005),
    wacc: base.wacc + 0.01,
  }
}

export const IPO_MODEL_ROUND2 = round2

// ---- Quick-start expander for manually-added (non-prospectus) IPOs ----
//
// A user adding a custom IPO shouldn't have to hand-fill five years of
// per-year ratios up front. This expands a handful of flat assumptions into
// a full explicit-year IpoDcfInputs; every year is then independently
// editable afterwards in the same trajectory table used for T2S.

export type IpoQuickStartInputs = {
  lastActualYear: number // e.g. 2025 - the anchor year the forecast is built on
  revenueBase: number // MMAD, last actual FY revenue
  forecastYears?: number // default 5
  flatRevenueGrowth: number // decimal, applied flat across all forecast years
  flatEbeMargin: number // decimal
  flatTaxPctRev: number // decimal, positive
  flatBfrPctRev: number // decimal, positive
  flatCapexPctRev: number // decimal, positive
  wacc: number
  terminalGrowth: number
  netDebt: number // MMAD
  shares: number // million shares
  offerPrice: number // MAD / share
}

export function defaultForecastYearLabels(lastActualYear: number, forecastYears: number): string[] {
  const labels: string[] = []
  for (let i = 1; i <= forecastYears; i++) {
    const year = lastActualYear + i
    labels.push(i <= 1 ? `${year}e` : `${year}p`)
  }
  return labels
}

export function buildQuickStartInputs(q: IpoQuickStartInputs): IpoDcfInputs {
  const forecastYears = q.forecastYears ?? 5
  const years = defaultForecastYearLabels(q.lastActualYear, forecastYears)
  return {
    revenueBase: q.revenueBase,
    years,
    revenueGrowth: years.map(() => q.flatRevenueGrowth),
    ebeMargin: years.map(() => q.flatEbeMargin),
    taxPctRev: years.map(() => q.flatTaxPctRev),
    bfrPctRev: years.map(() => q.flatBfrPctRev),
    capexPctRev: years.map(() => q.flatCapexPctRev),
    wacc: q.wacc,
    terminalGrowth: q.terminalGrowth,
    terminalEbeMargin: q.flatEbeMargin,
    terminalTaxPctRev: q.flatTaxPctRev,
    terminalBfrPctRev: q.flatBfrPctRev,
    terminalCapexPctRev: q.flatCapexPctRev,
    netDebt: q.netDebt,
    shares: q.shares,
    offerPrice: q.offerPrice,
    midYear: true,
  }
}
