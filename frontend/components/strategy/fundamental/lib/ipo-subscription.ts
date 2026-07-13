// IPO subscription sizing model, rebuilt against the AMMC-visaed prospectus
// (note d'operation p.57) for T2S Group Holding.
//
// Type I (institutional): pure pro-rata allocation, ratio = 1 / oversubscription.
// Type II (retail): iteration of ONE share per subscriber per round, up to a
// max of 100 shares per subscriber ("1ere allocation"). If the tranche cannot
// cover 100 shares for every subscriber, every subscriber is instead served in
// full up to a per-capita cap (trancheShares / N) and there is zero marginal
// allocation beyond that cap. Only when the first round completes (tranche >=
// 100 * N) does a second, pro-rata round distribute the residual tranche
// (RTO) against residual demand (RTD).
//
// Both tranches share a regulatory cap of 10% of the offer per investor
// (493 273 shares).

import { IPO_T2S } from "./ipo-data"

export type IpoTrancheKind = "retail" | "institutional"

export type IpoAllocationParams = {
  tranche: IpoTrancheKind
  trancheShares: number
  offerPrice: number
  expectedSubscriberCount: number // Type II: N, subscribers in the retail tranche (round 1)
  oversubscription: number // Type I: NTD/NTO of the tranche. Type II: total demand / trancheShares
  blockedDays: number
  financingRate: number
  // Fraction of the requested amount that must be covered (blocked as cash/cheque/wire
  // or collateral) for the duration of the subscription window (prospectus p.15-16,
  // p.53). Retail (non-qualified) = 1.0 (100% coverage required). Qualified Moroccan
  // institutional investors = 0.0 (no coverage at subscription, pay only at settlement).
  coverageRate: number
  // Trading days after listing needed to realize the pop and exit the position -
  // funds the ALLOCATED amount from settlement (31/07) until sale. Default 5.
  exitDays: number
  feesMad?: number
  institutionalMinShares?: number
  retailBlockSize?: number
  subscriptionCapShares?: number // 10% of the offer, per investor, both tranches
}

// A single conditional pop scenario (bear/base/bull) within a joint scenario.
export type IpoPopScenario = {
  key: string
  label: string
  pop: number
  probability: number
}

// Joint scenario: ties together the tranche-specific oversubscription levels,
// the retail subscriber count, and a CONDITIONAL pop distribution - i.e. the
// winner's curse correlation between how hot the deal is and what the pop
// ends up being (Rock 1986: cold deals -> worse pops).
export type IpoJointScenario = {
  key: string
  label: string
  probability: number
  oversubInstit: number
  oversubRetail: number
  retailSubscribers: number
  pops: IpoPopScenario[]
}

export type IpoAllocationResult = {
  requestedMad: number
  requestedShares: number
  allocatedShares: number
  allocatedMad: number
  returnedMad: number
  satisfactionRate: number
  firstBlockFillRate: number
  excessFillRate: number
  residualOversubscription: number
  perCapitaCapShares: number | null // Type II only: null once round 1 completes
  round1Shares: number
  round2Shares: number
  valid: boolean
  reason?: "below_institutional_minimum" | "above_subscription_cap"
}

export type IpoScenarioEconomics = {
  scenario: IpoPopScenario
  profitMad: number
  periodReturn: number
  annualizedReturn: number
}

export type IpoEconomicsResult = IpoAllocationResult & {
  financingCostMad: number
  capitalEngagedMad: number
  feesMad: number
  scenarios: IpoScenarioEconomics[]
  expectedProfitMad: number
  expectedPeriodReturn: number
  expectedAnnualizedReturn: number
}

export type IpoKellyResult = {
  fullKellyFraction: number
  halfKellyFraction: number
  suggestedFraction: number
  maxAllocatedExposureMad: number
  maxSubscriptionMad: number
}

export type IpoOptimalPoint = {
  requestedMad: number
  requestedShares: number
  allocatedShares: number
  satisfactionRate: number
  expectedProfitMad: number
  expectedAnnualizedReturn: number
}

export type IpoOptimalSubscription = {
  recommendedMad: number
  recommendedShares: number
  expectedAllocatedShares: number
  expectedSatisfactionRate: number
  expectedProfitMad: number
  expectedAnnualizedReturn: number
  kelly: IpoKellyResult
  binding: boolean
  shouldSubscribe: boolean
  reason?: "negative_expected_profit" | "below_institutional_minimum" | "kelly_cap_zero"
  grid: IpoOptimalPoint[]
}

export const DEFAULT_SUBSCRIPTION_CAP_SHARES = 493_273

type HistoricalReturnField = "j5Return" | "j10Return"

function historicalReturn(ipo: string, field: HistoricalReturnField, fallback: number): number {
  const value = IPO_T2S.casablancaBaseRates.find((row) => row.ipo === ipo)?.[field]
  return value == null || !Number.isFinite(value) ? fallback : value
}

// Use the same observations shown in the base-rate table. With the default
// J5 exit, bear is the worst observed J10 path, base keeps only half of the
// matching J5 anchor, and bull keeps the full J5 anchor. Probabilities remain
// separate, editable assumptions.
const HISTORICAL_DOWNSIDE = Math.min(
  ...IPO_T2S.casablancaBaseRates.map((row) => row.j10Return).filter((value): value is number => value != null),
)
const COLD_J5_ANCHOR = historicalReturn("CMGP", "j5Return", 0.25)
const CENTRAL_J5_ANCHOR =
  (historicalReturn("Vicenne", "j5Return", 0.4) + historicalReturn("Cash Plus", "j5Return", 0.4)) / 2
const HOT_J5_ANCHOR = historicalReturn("SGTM", "j5Return", 0.45)

export const IPO_RETURN_CALIBRATION = {
  horizon: "J5",
  baseHaircut: 0.5,
  downside: HISTORICAL_DOWNSIDE,
  coldAnchor: COLD_J5_ANCHOR,
  centralAnchor: CENTRAL_J5_ANCHOR,
  hotAnchor: HOT_J5_ANCHOR,
} as const

// Default joint scenarios: Rock 1986 winner's curse logic (cold deals -> worse
// pops), calibrated on Casablanca 2024-25 base rates. High turnout (SGTM:
// 171 377 subscribers, the record) means a BIG pop but a tiny per-capita
// retail allocation (1 793 721 / 150 000 ~= 12 shares) - the winner's curse in
// its purest form: SGTM was NOT a cold deal, its 34x oversub was only that low
// because the offer itself was huge (4.8 Bn MAD). N figures below are
// estimates for T2S (deal size 1.1 Bn MAD); anchors: CMGP 33.7k subscribers,
// Vicenne 37.7k, Cash Plus 81.5k, SGTM 171.4k.
export const IPO_JOINT_PRESETS: IpoJointScenario[] = [
  {
    key: "cold",
    label: "Demande faible (CMGP 2024-like)",
    probability: 0.25,
    oversubInstit: 25,
    oversubRetail: 30,
    retailSubscribers: 35_000,
    pops: [
      { key: "bear", label: "Bear", pop: HISTORICAL_DOWNSIDE, probability: 0.3 },
      { key: "base", label: "Base", pop: COLD_J5_ANCHOR * 0.5, probability: 0.5 },
      { key: "bull", label: "Bull", pop: COLD_J5_ANCHOR, probability: 0.2 },
    ],
  },
  {
    key: "central",
    label: "Demande moyenne (Vicenne/Cash Plus-like)",
    probability: 0.45,
    oversubInstit: 45,
    oversubRetail: 55,
    retailSubscribers: 60_000,
    pops: [
      { key: "bear", label: "Bear", pop: HISTORICAL_DOWNSIDE, probability: 0.15 },
      { key: "base", label: "Base", pop: CENTRAL_J5_ANCHOR * 0.5, probability: 0.6 },
      { key: "bull", label: "Bull", pop: CENTRAL_J5_ANCHOR, probability: 0.25 },
    ],
  },
  {
    key: "hot",
    label: "Frénésie (SGTM-like, record)",
    probability: 0.3,
    oversubInstit: 60,
    oversubRetail: 75,
    retailSubscribers: 150_000,
    pops: [
      { key: "bear", label: "Bear", pop: HISTORICAL_DOWNSIDE, probability: 0.1 },
      { key: "base", label: "Base", pop: HOT_J5_ANCHOR * 0.5, probability: 0.5 },
      { key: "bull", label: "Bull", pop: HOT_J5_ANCHOR, probability: 0.4 },
    ],
  },
]

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value))
}

function safeProbabilities<T extends { probability: number }>(rows: T[]): T[] {
  const total = rows.reduce((sum, row) => sum + Math.max(0, row.probability), 0)
  if (total <= 0) {
    const equal = rows.length > 0 ? 1 / rows.length : 0
    return rows.map((row) => ({ ...row, probability: equal }))
  }
  return rows.map((row) => ({ ...row, probability: Math.max(0, row.probability) / total }))
}

// Normalizes both the joint-scenario weights and each scenario's internal
// (conditional) pop distribution.
export function normalizeJointScenarios(scenarios: IpoJointScenario[]): IpoJointScenario[] {
  const normalizedTop = safeProbabilities(scenarios)
  return normalizedTop.map((scenario) => ({ ...scenario, pops: safeProbabilities(scenario.pops) }))
}

// Flattens joint scenarios into a single mixture pop distribution: weight of
// each (scenario, pop) pair = scenario.probability * pop.probability. Used
// for the Kelly fraction search, which only cares about the unconditional
// distribution of outcomes on allocated capital.
export function mixturePopScenarios(scenarios: IpoJointScenario[]): IpoPopScenario[] {
  const normalized = normalizeJointScenarios(scenarios)
  const flat: IpoPopScenario[] = []
  for (const scenario of normalized) {
    for (const pop of scenario.pops) {
      flat.push({ key: `${scenario.key}-${pop.key}`, label: `${scenario.label} / ${pop.label}`, pop: pop.pop, probability: scenario.probability * pop.probability })
    }
  }
  return safeProbabilities(flat)
}

// Mixture mean pop across normalized joint scenarios: Sigma
// scenario.probability * pop.probability * pop.pop. Pure - used to headline
// the expected stock-price variation independent of any subscription amount.
export function expectedMixturePop(scenarios: IpoJointScenario[]): number {
  return mixturePopScenarios(scenarios).reduce((sum, pop) => sum + pop.probability * pop.pop, 0)
}

function madToWholeShares(requestedMad: number, offerPrice: number): number {
  if (!(requestedMad > 0) || !(offerPrice > 0)) return 0
  return Math.floor(requestedMad / offerPrice)
}

function sharesToMad(shares: number, offerPrice: number): number {
  return Math.max(0, shares) * offerPrice
}

export function expectedAllocation(requestedMad: number, params: IpoAllocationParams): IpoAllocationResult {
  const retailBlockSize = Math.max(1, params.retailBlockSize ?? 100)
  const institutionalMinShares = Math.max(1, params.institutionalMinShares ?? 13_452)
  const subscriptionCapShares = Math.max(1, params.subscriptionCapShares ?? DEFAULT_SUBSCRIPTION_CAP_SHARES)

  let requestedShares = madToWholeShares(requestedMad, params.offerPrice)
  let capReason: IpoAllocationResult["reason"] | undefined
  if (requestedShares > subscriptionCapShares) {
    requestedShares = subscriptionCapShares
    capReason = "above_subscription_cap"
  }

  if (params.tranche === "institutional" && requestedShares > 0 && requestedShares < institutionalMinShares) {
    return {
      requestedMad: sharesToMad(requestedShares, params.offerPrice),
      requestedShares,
      allocatedShares: 0,
      allocatedMad: 0,
      returnedMad: sharesToMad(requestedShares, params.offerPrice),
      satisfactionRate: 0,
      firstBlockFillRate: 0,
      excessFillRate: 0,
      residualOversubscription: params.oversubscription,
      perCapitaCapShares: null,
      round1Shares: 0,
      round2Shares: 0,
      valid: false,
      reason: "below_institutional_minimum",
    }
  }

  if (requestedShares <= 0) {
    return {
      requestedMad: 0,
      requestedShares: 0,
      allocatedShares: 0,
      allocatedMad: 0,
      returnedMad: 0,
      satisfactionRate: 0,
      firstBlockFillRate: 0,
      excessFillRate: 0,
      residualOversubscription: params.oversubscription,
      perCapitaCapShares: null,
      round1Shares: 0,
      round2Shares: 0,
      valid: true,
    }
  }

  const requestedRoundedMad = sharesToMad(requestedShares, params.offerPrice)

  if (params.tranche === "institutional") {
    const fillRate = params.oversubscription > 0 ? 1 / params.oversubscription : 0
    const allocatedShares = requestedShares * fillRate
    const allocatedMad = sharesToMad(allocatedShares, params.offerPrice)
    return {
      requestedMad: requestedRoundedMad,
      requestedShares,
      allocatedShares,
      allocatedMad,
      returnedMad: Math.max(0, requestedRoundedMad - allocatedMad),
      satisfactionRate: requestedShares > 0 ? allocatedShares / requestedShares : 0,
      firstBlockFillRate: fillRate,
      excessFillRate: fillRate,
      residualOversubscription: params.oversubscription,
      perCapitaCapShares: null,
      round1Shares: allocatedShares,
      round2Shares: 0,
      valid: true,
      reason: capReason,
    }
  }

  // Type II retail: 1ere allocation by 1-share-per-subscriber iteration, capped at 100.
  const N = Math.max(1, params.expectedSubscriberCount)
  const round1Capacity = retailBlockSize * N
  const round1Completes = params.trancheShares >= round1Capacity

  if (!round1Completes) {
    // Insufficient case: everyone served in full up to the per-capita cap; zero
    // marginal allocation beyond it.
    const perCapitaCapShares = params.trancheShares / N
    const round1Shares = Math.min(requestedShares, perCapitaCapShares)
    const allocatedShares = round1Shares
    const allocatedMad = sharesToMad(allocatedShares, params.offerPrice)
    return {
      requestedMad: requestedRoundedMad,
      requestedShares,
      allocatedShares,
      allocatedMad,
      returnedMad: Math.max(0, requestedRoundedMad - allocatedMad),
      satisfactionRate: requestedShares > 0 ? allocatedShares / requestedShares : 0,
      firstBlockFillRate: perCapitaCapShares > 0 ? clamp01(perCapitaCapShares / retailBlockSize) : 0,
      excessFillRate: 0,
      residualOversubscription: round1Capacity / Math.max(1, params.trancheShares),
      perCapitaCapShares,
      round1Shares,
      round2Shares: 0,
      valid: true,
      reason: capReason,
    }
  }

  // Round 1 completes: everyone gets min(their demand, 100). Residual tranche
  // (RTO) is then allocated pro-rata against residual demand (RTD).
  const round1Shares = Math.min(requestedShares, retailBlockSize)
  const residualRequestShares = Math.max(0, requestedShares - retailBlockSize)
  const RTO = Math.max(0, params.trancheShares - round1Capacity)
  const totalDemandShares = Math.max(0, params.oversubscription) * params.trancheShares
  const RTD = Math.max(0, totalDemandShares - round1Capacity)
  const excessFillRate = RTO > 0 && RTD > 0 ? clamp01(RTO / RTD) : 0
  const round2Shares = residualRequestShares * excessFillRate
  const allocatedShares = round1Shares + round2Shares
  const allocatedMad = sharesToMad(allocatedShares, params.offerPrice)
  const residualOversubscription = RTO > 0 ? RTD / RTO : Infinity

  return {
    requestedMad: requestedRoundedMad,
    requestedShares,
    allocatedShares,
    allocatedMad,
    returnedMad: Math.max(0, requestedRoundedMad - allocatedMad),
    satisfactionRate: requestedShares > 0 ? allocatedShares / requestedShares : 0,
    firstBlockFillRate: 1,
    excessFillRate,
    residualOversubscription,
    perCapitaCapShares: null,
    round1Shares,
    round2Shares,
    valid: true,
    reason: capReason,
  }
}

// Coverage-aware financing cost (prospectus p.15-16, p.53): retail subscribers
// must cover 100% of the REQUESTED amount at subscription (cash/cheque/wire or
// collateral), blocked until allocation (22/07) - first term. Qualified
// institutional investors post no coverage at subscription and only fund the
// ALLOCATED amount from settlement (31/07) until they exit the pop - second
// term. capitalEngagedMad is the largest amount actually at risk over the
// life of the trade (coverage while blocked, or the allocated position once
// settled, whichever is larger) and is what returns are measured against.
export function subscriptionEconomics(requestedMad: number, params: IpoAllocationParams, popScenarios: IpoPopScenario[]): IpoEconomicsResult {
  const allocation = expectedAllocation(requestedMad, params)
  const r = Math.max(0, params.financingRate)
  const blockedDays = Math.max(0, params.blockedDays)
  const exitDays = Math.max(0, params.exitDays)
  const coverageRate = clamp01(params.coverageRate)
  const financingCostMad = coverageRate * allocation.requestedMad * r * blockedDays / 360 + allocation.allocatedMad * r * exitDays / 360
  const capitalEngagedMad = Math.max(coverageRate * allocation.requestedMad, allocation.allocatedMad)
  const feesMad = Math.max(0, params.feesMad ?? 0)
  const normalizedScenarios = safeProbabilities(popScenarios)
  const scenarios = normalizedScenarios.map((scenario) => {
    const grossProfit = allocation.allocatedMad * scenario.pop
    const profitMad = grossProfit - financingCostMad - feesMad
    const periodReturn = capitalEngagedMad > 0 ? profitMad / capitalEngagedMad : 0
    const annualizedReturn = blockedDays + exitDays > 0 ? periodReturn * 360 / (blockedDays + exitDays) : 0
    return { scenario, profitMad, periodReturn, annualizedReturn }
  })
  const expectedProfitMad = scenarios.reduce((sum, item) => sum + item.profitMad * item.scenario.probability, 0)
  const expectedPeriodReturn = scenarios.reduce((sum, item) => sum + item.periodReturn * item.scenario.probability, 0)
  const expectedAnnualizedReturn = scenarios.reduce((sum, item) => sum + item.annualizedReturn * item.scenario.probability, 0)
  return {
    ...allocation,
    financingCostMad,
    capitalEngagedMad,
    feesMad,
    scenarios,
    expectedProfitMad,
    expectedPeriodReturn,
    expectedAnnualizedReturn,
  }
}

function expectedLogGrowth(fraction: number, scenarios: IpoPopScenario[]): number {
  let sum = 0
  for (const scenario of scenarios) {
    const gross = 1 + fraction * scenario.pop
    if (gross <= 0) return -Infinity
    sum += scenario.probability * Math.log(gross)
  }
  return sum
}

// Params shared by both tranches when scanning across joint scenarios - the
// tranche-specific oversubscription/subscriber count come from each scenario.
export type IpoBaseParams = Omit<IpoAllocationParams, "expectedSubscriberCount" | "oversubscription">

function paramsForScenario(baseParams: IpoBaseParams, scenario: IpoJointScenario): IpoAllocationParams {
  if (baseParams.tranche === "institutional") {
    return { ...baseParams, oversubscription: scenario.oversubInstit, expectedSubscriberCount: scenario.retailSubscribers }
  }
  return { ...baseParams, oversubscription: scenario.oversubRetail, expectedSubscriberCount: scenario.retailSubscribers }
}

export function combinedExpectedEconomics(requestedMad: number, baseParams: IpoBaseParams, jointScenarios: IpoJointScenario[]) {
  const normalized = normalizeJointScenarios(jointScenarios)
  const detailed = normalized.map((jointScenario) => {
    const params = paramsForScenario(baseParams, jointScenario)
    const economics = subscriptionEconomics(requestedMad, params, jointScenario.pops)
    return { jointScenario, economics }
  })

  const expectedAllocatedShares = detailed.reduce((sum, row) => sum + row.economics.allocatedShares * row.jointScenario.probability, 0)
  const expectedSatisfactionRate = detailed.reduce((sum, row) => sum + row.economics.satisfactionRate * row.jointScenario.probability, 0)
  const expectedProfitMad = detailed.reduce((sum, row) => sum + row.economics.expectedProfitMad * row.jointScenario.probability, 0)
  const expectedAnnualizedReturn = detailed.reduce((sum, row) => sum + row.economics.expectedAnnualizedReturn * row.jointScenario.probability, 0)

  return {
    expectedAllocatedShares,
    expectedSatisfactionRate,
    expectedProfitMad,
    expectedAnnualizedReturn,
    detailed,
  }
}

export function kellySuggestedMax(
  baseParams: IpoBaseParams,
  jointScenarios: IpoJointScenario[],
  capitalMad: number,
  useHalfKelly = true,
): IpoKellyResult {
  const mixture = mixturePopScenarios(jointScenarios)
  let bestFraction = 0
  let bestScore = expectedLogGrowth(0, mixture)
  const STEPS = 1000
  const MAX_FRACTION = 5
  for (let step = 1; step <= STEPS; step++) {
    const fraction = (step / STEPS) * MAX_FRACTION // 0.005 increments up to 5
    const score = expectedLogGrowth(fraction, mixture)
    if (score > bestScore) {
      bestScore = score
      bestFraction = fraction
    }
  }
  const fullKellyFraction = bestFraction
  const halfKellyFraction = fullKellyFraction / 2
  const suggestedFraction = useHalfKelly ? halfKellyFraction : fullKellyFraction
  const maxAllocatedExposureMad = Math.max(0, capitalMad) * suggestedFraction

  let maxSubscriptionMad = 0
  const maxSharesToScan = Math.max(baseParams.institutionalMinShares ?? 13_452, madToWholeShares(Math.max(0, capitalMad), baseParams.offerPrice))
  const stepShares = 100
  for (let shares = 0; shares <= maxSharesToScan; shares += stepShares) {
    const requestedMad = sharesToMad(shares, baseParams.offerPrice)
    const combined = combinedExpectedEconomics(requestedMad, baseParams, jointScenarios)
    const allocatedMad = combined.expectedAllocatedShares * baseParams.offerPrice
    if (allocatedMad <= maxAllocatedExposureMad + 1e-9) maxSubscriptionMad = requestedMad
  }

  return {
    fullKellyFraction,
    halfKellyFraction,
    suggestedFraction,
    maxAllocatedExposureMad,
    maxSubscriptionMad,
  }
}

export function optimalSubscriptionAcrossScenarios(
  baseParams: IpoBaseParams,
  jointScenarios: IpoJointScenario[],
  capitalMad: number,
  maxQMad?: number,
): IpoOptimalSubscription {
  const capitalCap = Math.max(0, capitalMad)
  const scanCap = Math.max(0, Math.min(maxQMad ?? capitalCap, capitalCap))

  if (baseParams.tranche === "institutional") {
    const minShares = Math.max(0, baseParams.institutionalMinShares ?? 13_452)
    const minMad = minShares * baseParams.offerPrice
    if (capitalCap < minMad) {
      const kelly = kellySuggestedMax(baseParams, jointScenarios, capitalCap, true)
      return {
        recommendedMad: 0,
        recommendedShares: 0,
        expectedAllocatedShares: 0,
        expectedSatisfactionRate: 0,
        expectedProfitMad: 0,
        expectedAnnualizedReturn: 0,
        kelly,
        binding: false,
        shouldSubscribe: false,
        reason: "below_institutional_minimum",
        grid: [],
      }
    }
  }

  const kelly = kellySuggestedMax(baseParams, jointScenarios, capitalCap, true)
  const kellyLimited = kelly.maxSubscriptionMad > 0 && kelly.maxSubscriptionMad < scanCap - 1e-6
  const effectiveCap = Math.min(scanCap, kelly.maxSubscriptionMad > 0 ? kelly.maxSubscriptionMad : scanCap)
  const minShares = baseParams.tranche === "institutional" ? Math.max(0, baseParams.institutionalMinShares ?? 13_452) : 0
  const maxShares = madToWholeShares(effectiveCap, baseParams.offerPrice)
  // Retail: the optimum sits at the per-capita cap (tens of shares), so scan
  // finely; institutional amounts are large enough for 100-share steps.
  const stepShares = baseParams.tranche === "retail" ? 10 : 100
  const grid: IpoOptimalPoint[] = []

  if (effectiveCap <= 0 || kelly.maxAllocatedExposureMad <= 0) {
    return {
      recommendedMad: 0,
      recommendedShares: 0,
      expectedAllocatedShares: 0,
      expectedSatisfactionRate: 0,
      expectedProfitMad: 0,
      expectedAnnualizedReturn: 0,
      kelly,
      binding: false,
      shouldSubscribe: false,
      reason: "kelly_cap_zero",
      grid,
    }
  }

  let best: IpoOptimalPoint | null = null
  for (let shares = minShares; shares <= maxShares; shares += stepShares) {
    const requestedMad = sharesToMad(shares, baseParams.offerPrice)
    const combined = combinedExpectedEconomics(requestedMad, baseParams, jointScenarios)
    const point: IpoOptimalPoint = {
      requestedMad,
      requestedShares: shares,
      allocatedShares: combined.expectedAllocatedShares,
      satisfactionRate: combined.expectedSatisfactionRate,
      expectedProfitMad: combined.expectedProfitMad,
      expectedAnnualizedReturn: combined.expectedAnnualizedReturn,
    }
    grid.push(point)
    if (!best || point.expectedProfitMad > best.expectedProfitMad) best = point
  }

  if (!best) {
    return {
      recommendedMad: 0,
      recommendedShares: 0,
      expectedAllocatedShares: 0,
      expectedSatisfactionRate: 0,
      expectedProfitMad: 0,
      expectedAnnualizedReturn: 0,
      kelly,
      binding: false,
      shouldSubscribe: false,
      reason: "kelly_cap_zero",
      grid,
    }
  }

  const binding = kellyLimited && best.requestedShares >= maxShares - stepShares
  const shouldSubscribe = best.expectedProfitMad > 0
  return {
    recommendedMad: best.requestedMad,
    recommendedShares: best.requestedShares,
    expectedAllocatedShares: best.allocatedShares,
    expectedSatisfactionRate: best.satisfactionRate,
    expectedProfitMad: best.expectedProfitMad,
    expectedAnnualizedReturn: best.expectedAnnualizedReturn,
    kelly,
    binding,
    shouldSubscribe,
    reason: shouldSubscribe ? undefined : "negative_expected_profit",
    grid,
  }
}
