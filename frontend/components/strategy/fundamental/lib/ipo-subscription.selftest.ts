// Plain assert-style selftest for the IPO subscription model. No test runner
// is configured in this repo (no vitest/jest) - run directly with:
//   npx tsx components/strategy/fundamental/lib/ipo-subscription.selftest.ts
import {
  combinedExpectedEconomics,
  expectedAllocation,
  IPO_JOINT_PRESETS,
  IPO_RETURN_CALIBRATION,
  normalizeJointScenarios,
  optimalSubscriptionAcrossScenarios,
  subscriptionEconomics,
  type IpoAllocationParams,
  type IpoBaseParams,
  type IpoJointScenario,
} from "./ipo-subscription"

let passed = 0
let failed = 0

function ok(name: string, cond: boolean, detail?: string) {
  if (cond) {
    passed++
    console.log(`  ok   ${name}`)
  } else {
    failed++
    console.log(`  FAIL ${name}${detail ? " - " + detail : ""}`)
  }
}

function approx(a: number, b: number, tol = 1e-6): boolean {
  return Math.abs(a - b) <= tol
}

const OFFER_PRICE = 223

function sharesMad(shares: number): number {
  return shares * OFFER_PRICE
}

// -----------------------------------------------------------------------
// 1. SGTM replay: insufficient round-1 case.
// -----------------------------------------------------------------------
console.log("1. SGTM replay (insufficient round 1)")
{
  const params: IpoAllocationParams = {
    tranche: "retail",
    trancheShares: 1_793_721,
    offerPrice: OFFER_PRICE,
    expectedSubscriberCount: 171_000,
    oversubscription: 34, // unused when round 1 doesn't complete
    blockedDays: 12,
    financingRate: 0.03,
    coverageRate: 1,
    exitDays: 5,
  }
  const perCapitaCap = 1_793_721 / 171_000
  ok("perCapitaCap ~= 10.49", approx(perCapitaCap, 10.49, 0.01), String(perCapitaCap))

  const small = expectedAllocation(sharesMad(10), params)
  ok("Q=10 -> allocated=10 (full)", approx(small.allocatedShares, 10, 1e-6), String(small.allocatedShares))
  ok("Q=10 perCapitaCapShares set", small.perCapitaCapShares != null && approx(small.perCapitaCapShares, perCapitaCap, 1e-6))

  const large = expectedAllocation(sharesMad(10_000), params)
  ok("Q=10000 -> allocated ~= perCapitaCap", approx(large.allocatedShares, perCapitaCap, 1e-6), String(large.allocatedShares))
  ok("Q=10000 round2Shares = 0", approx(large.round2Shares, 0))
}

// -----------------------------------------------------------------------
// 2. Round-1-completes case.
// -----------------------------------------------------------------------
console.log("2. Round-1-completes")
{
  const trancheShares = 1_793_721
  const N = 15_000
  const oversubRetail = 50
  const params: IpoAllocationParams = {
    tranche: "retail",
    trancheShares,
    offerPrice: OFFER_PRICE,
    expectedSubscriberCount: N,
    oversubscription: oversubRetail,
    blockedDays: 12,
    financingRate: 0.03,
    coverageRate: 1,
    exitDays: 5,
  }
  ok("100*N < trancheShares (round 1 completes)", 100 * N < trancheShares)

  const at100 = expectedAllocation(sharesMad(100), params)
  ok("Q=100 -> allocated=100", approx(at100.allocatedShares, 100, 1e-6), String(at100.allocatedShares))

  const RTO = trancheShares - 100 * N // 293_721
  const RTD = oversubRetail * trancheShares - 100 * N
  ok("RTO = 293721", RTO === 293_721, String(RTO))
  const expectedAt10k = 100 + 9_900 * (RTO / RTD)
  const at10k = expectedAllocation(sharesMad(10_000), params)
  ok("Q=10000 -> 100 + 9900*RTO/RTD", approx(at10k.allocatedShares, expectedAt10k, 1e-6), `${at10k.allocatedShares} vs ${expectedAt10k}`)
}

// -----------------------------------------------------------------------
// 3. Institutional: pro-rata + minimum + cap clamp.
// -----------------------------------------------------------------------
console.log("3. Institutional")
{
  const params: IpoAllocationParams = {
    tranche: "institutional",
    trancheShares: 3_139_013,
    offerPrice: OFFER_PRICE,
    expectedSubscriberCount: 1,
    oversubscription: 45,
    blockedDays: 12,
    financingRate: 0.03,
    coverageRate: 0,
    exitDays: 5,
    institutionalMinShares: 13_452,
  }
  const atMin = expectedAllocation(sharesMad(13_452), params)
  ok("Q=13452 -> allocated=13452/45", approx(atMin.allocatedShares, 13_452 / 45, 1e-6), String(atMin.allocatedShares))
  ok("Q=13452 valid", atMin.valid)

  const belowMin = expectedAllocation(sharesMad(5_000), params)
  ok("Q below min -> invalid, reason below_institutional_minimum", !belowMin.valid && belowMin.reason === "below_institutional_minimum")

  const overCap = expectedAllocation(sharesMad(600_000), params)
  ok("Q=600000 -> requestedShares clamped to 493273", overCap.requestedShares === 493_273, String(overCap.requestedShares))
  ok("Q=600000 -> reason above_subscription_cap", overCap.reason === "above_subscription_cap")
  ok("Q=600000 -> allocated=493273/45", approx(overCap.allocatedShares, 493_273 / 45, 1e-6), String(overCap.allocatedShares))
}

// -----------------------------------------------------------------------
// 4. Monotonicity (retail, round-1-completes case).
// -----------------------------------------------------------------------
console.log("4. Monotonicity")
{
  const params: IpoAllocationParams = {
    tranche: "retail",
    trancheShares: 1_793_721,
    offerPrice: OFFER_PRICE,
    expectedSubscriberCount: 15_000,
    oversubscription: 50,
    blockedDays: 12,
    financingRate: 0.03,
    coverageRate: 1,
    exitDays: 5,
  }
  const shareSteps = [0, 50, 100, 500, 2_000, 10_000, 50_000]
  let prevAllocated = -Infinity
  let prevSatisfaction = Infinity
  let monotonicAlloc = true
  let monotonicSat = true
  for (const shares of shareSteps) {
    const result = expectedAllocation(sharesMad(shares), params)
    if (result.allocatedShares < prevAllocated - 1e-9) monotonicAlloc = false
    if (shares > 0 && result.satisfactionRate > prevSatisfaction + 1e-9) monotonicSat = false
    prevAllocated = result.allocatedShares
    if (shares > 0) prevSatisfaction = result.satisfactionRate
  }
  ok("allocated shares non-decreasing in Q", monotonicAlloc)
  ok("satisfaction non-increasing in Q", monotonicSat)
}

// -----------------------------------------------------------------------
// 5. Decision rule: no double-counted financing cost.
// -----------------------------------------------------------------------
console.log("5. Decision rule")
{
  // coverageRate=1 + exitDays=0 reproduces the pre-coverage-aware formula
  // exactly (capitalEngaged = requestedMad, no second financing term), so the
  // pre-existing decision-rule assertions below still hold unchanged.
  const baseParams: IpoBaseParams = {
    tranche: "retail",
    trancheShares: 1_793_721,
    offerPrice: OFFER_PRICE,
    blockedDays: 12,
    financingRate: 0.03,
    coverageRate: 1,
    exitDays: 0,
  }
  const allBearScenarios: IpoJointScenario[] = [
    {
      key: "cold",
      label: "Froid",
      probability: 1,
      oversubInstit: 30,
      oversubRetail: 38,
      retailSubscribers: 90_000,
      pops: [
        { key: "bear", label: "Bear", pop: -0.2, probability: 1 },
        { key: "base", label: "Base", pop: -0.1, probability: 0 },
        { key: "bull", label: "Bull", pop: -0.05, probability: 0 },
      ],
    },
  ]
  const negativeResult = optimalSubscriptionAcrossScenarios(baseParams, allBearScenarios, 500_000, 500_000)
  ok("all-negative pops -> shouldSubscribe=false", negativeResult.shouldSubscribe === false)
  ok("all-negative pops -> reason negative_expected_profit", negativeResult.reason === "negative_expected_profit" || negativeResult.recommendedShares === 0)

  // Construct a case where expected profit is slightly positive but the
  // annualized return on blocked capital is below the financing rate - under
  // the old (buggy) rule (annualizedReturn >= financingRate) this would have
  // been rejected; under the fixed rule (profit > 0, no double count) it must
  // be accepted. Retail Q=500 at N=15000/oversubRetail=50 sits past the
  // round-1 cap (100 shares) into the pro-rata round-2, so satisfaction < 1;
  // with blockedDays=360 the annualized return equals the period return, so
  // we just need 0 < grossProfit/requestedMad - financingRate < financingRate.
  const modestParams: IpoBaseParams = { ...baseParams, financingRate: 0.02, blockedDays: 360 }
  const modestPopScenarios: IpoJointScenario[] = [
    {
      key: "central",
      label: "Central",
      probability: 1,
      oversubInstit: 45,
      oversubRetail: 50,
      retailSubscribers: 15_000,
      pops: [
        { key: "bear", label: "Bear", pop: 0.15, probability: 1 },
        { key: "base", label: "Base", pop: 0.15, probability: 0 },
        { key: "bull", label: "Bull", pop: 0.15, probability: 0 },
      ],
    },
  ]
  const modestQMad = sharesMad(500)
  const combinedAtQ = combinedExpectedEconomics(modestQMad, modestParams, modestPopScenarios)
  ok("constructed case has positive expected profit at Q=500", combinedAtQ.expectedProfitMad > 0, String(combinedAtQ.expectedProfitMad))
  ok(
    "constructed case has annualized return below financing rate (would have failed old >= rule)",
    combinedAtQ.expectedAnnualizedReturn < modestParams.financingRate,
    `${combinedAtQ.expectedAnnualizedReturn} vs ${modestParams.financingRate}`,
  )
  const positiveResult = optimalSubscriptionAcrossScenarios(modestParams, modestPopScenarios, modestQMad, modestQMad)
  ok("shouldSubscribe=true despite annualized return < financingRate", positiveResult.shouldSubscribe === true, JSON.stringify(positiveResult))
}

// -----------------------------------------------------------------------
// 6. Probability normalization.
// -----------------------------------------------------------------------
console.log("6. Probability normalization")
{
  const scenarios: IpoJointScenario[] = [2, 2, 2].map((p, i) => ({
    key: `s${i}`,
    label: `S${i}`,
    probability: p,
    oversubInstit: 30,
    oversubRetail: 30,
    retailSubscribers: 60_000,
    pops: [
      { key: "bear", label: "Bear", pop: -0.1, probability: 1 },
      { key: "base", label: "Base", pop: 0.2, probability: 1 },
      { key: "bull", label: "Bull", pop: 0.4, probability: 1 },
    ],
  }))
  const normalized = normalizeJointScenarios(scenarios)
  ok("3 equal-weight scenarios normalize to 1/3 each", normalized.every((s) => approx(s.probability, 1 / 3, 1e-9)), JSON.stringify(normalized.map((s) => s.probability)))
  ok("normalized pops also sum to 1 each scenario", normalized.every((s) => approx(s.pops.reduce((sum, p) => sum + p.probability, 0), 1, 1e-9)))
}

// -----------------------------------------------------------------------
// 7. Coverage-aware financing cost (AMMC prospectus p.15-16, p.53): retail
// must cover 100% at subscription, qualified institutional investors post no
// coverage and only fund the ALLOCATED amount from settlement to exit.
// -----------------------------------------------------------------------
console.log("7. Coverage-aware financing cost")
{
  const commonBase = {
    trancheShares: 3_139_013,
    offerPrice: OFFER_PRICE,
    expectedSubscriberCount: 1,
    oversubscription: 45,
    blockedDays: 12,
    financingRate: 0.03,
    exitDays: 5,
    institutionalMinShares: 13_452,
  }
  const noCoverageParams: IpoAllocationParams = { ...commonBase, tranche: "institutional", coverageRate: 0 }
  const fullCoverageParams: IpoAllocationParams = { ...commonBase, tranche: "institutional", coverageRate: 1 }

  const requestedMad = sharesMad(20_000) // requested >> allocated (fillRate = 1/45)
  const popScenarios = [{ key: "base", label: "Base", pop: 0.2, probability: 1 }]

  const econNoCoverage = subscriptionEconomics(requestedMad, noCoverageParams, popScenarios)
  const econFullCoverage = subscriptionEconomics(requestedMad, fullCoverageParams, popScenarios)

  const expectedFinancingCostNoCoverage = econNoCoverage.allocatedMad * noCoverageParams.financingRate * noCoverageParams.exitDays / 360
  ok(
    "coverageRate=0 -> financing cost = allocatedMad x r x exitDays/360 only",
    approx(econNoCoverage.financingCostMad, expectedFinancingCostNoCoverage, 1e-6),
    `${econNoCoverage.financingCostMad} vs ${expectedFinancingCostNoCoverage}`,
  )

  ok(
    "coverageRate=0 profit strictly higher than coverageRate=1 (same allocation, same pop)",
    econNoCoverage.scenarios[0].profitMad > econFullCoverage.scenarios[0].profitMad,
    `${econNoCoverage.scenarios[0].profitMad} vs ${econFullCoverage.scenarios[0].profitMad}`,
  )

  ok(
    "capitalEngagedMad = allocatedMad when coverage=0",
    approx(econNoCoverage.capitalEngagedMad, econNoCoverage.allocatedMad, 1e-6),
    String(econNoCoverage.capitalEngagedMad),
  )
  ok(
    "capitalEngagedMad = requestedMad when coverage=1 (requested > allocated)",
    approx(econFullCoverage.capitalEngagedMad, econFullCoverage.requestedMad, 1e-6),
    `${econFullCoverage.capitalEngagedMad} vs ${econFullCoverage.requestedMad}`,
  )

  const expectedAnnualized = econNoCoverage.scenarios[0].periodReturn * 360 / (noCoverageParams.blockedDays + noCoverageParams.exitDays)
  ok(
    "annualization uses blockedDays + exitDays",
    approx(econNoCoverage.scenarios[0].annualizedReturn, expectedAnnualized, 1e-9),
    String(econNoCoverage.scenarios[0].annualizedReturn),
  )
}

console.log("8. Historical return calibration")
{
  const cold = IPO_JOINT_PRESETS.find((row) => row.key === "cold")!
  const central = IPO_JOINT_PRESETS.find((row) => row.key === "central")!
  const hot = IPO_JOINT_PRESETS.find((row) => row.key === "hot")!
  const pop = (scenario: IpoJointScenario, key: string) => scenario.pops.find((row) => row.key === key)!.pop

  ok("calibration horizon is J5", IPO_RETURN_CALIBRATION.horizon === "J5")
  ok("cold bull equals CMGP J5", approx(pop(cold, "bull"), IPO_RETURN_CALIBRATION.coldAnchor))
  ok("central base applies 50% haircut", approx(pop(central, "base"), IPO_RETURN_CALIBRATION.centralAnchor * 0.5))
  ok("hot bull equals SGTM J5", approx(pop(hot, "bull"), IPO_RETURN_CALIBRATION.hotAnchor))
  ok("bear uses worst observed path", approx(pop(hot, "bear"), IPO_RETURN_CALIBRATION.downside))
}

console.log(`\n${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)
