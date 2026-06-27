import test from "node:test"
import assert from "node:assert/strict"

import { buildValuationModelStory } from "./fundamental-valuation-story-utils.js"

function check(story, label) {
  return story.checks.find((item) => item.label === label)
}

test("residual income story reconciles BVPS plus discounted residual income", () => {
  const expectedFairValue = 10 + 2.2 / 1.1 + 1.1 / (1.1 ** 2) + 0.5
  const story = buildValuationModelStory({
    model: "residual_income",
    fair_value: expectedFairValue,
    inputs: {
      book_value_per_share: 10,
      cost_of_equity: 0.1,
      payout: 0.4,
      terminal_growth: 0.03,
    },
    outputs: {
      projected_residual_income: [
        { year: 1, roe: 0.15, book_value: 10.6, residual_income: 2.2 },
        { year: 2, roe: 0.13, book_value: 11.1, residual_income: 1.1 },
      ],
      terminal_residual_income_pv: 0.5,
    },
  }, {})

  assert.equal(story.model, "residual_income")
  assert.equal(check(story, "Reconciliation FV")?.ok, true)
  const pvMetric = story.steps[1].metrics.find((item) => item.label === "FV calculee")
  assert.ok(Math.abs(pvMetric.value - expectedFairValue) < 1e-9)
})

test("justified multiples story uses median implied price", () => {
  const story = buildValuationModelStory({
    model: "justified_multiples",
    fair_value: 105,
    current_price: 100,
    inputs: {
      roe: 0.14,
      roe_source: "roe_3y_trailing",
      payout: 0.45,
      growth: 0.03,
      cost_of_equity: 0.1,
      sustainable_growth: 0.077,
    },
    outputs: {
      implied_prices: {
        justified_pb: 90,
        justified_pe: 120,
      },
      justified_multiples: {
        implied_pb: 1.5714285714285714,
        implied_pe: 6.621428571428572,
      },
    },
  }, {
    metrics: {
      Current_Price: 100,
      Price_to_Book: 1.8,
      PER: 12,
    },
  })

  assert.equal(story.model, "justified_multiples")
  assert.equal(check(story, "Reconciliation mediane")?.ok, true)
  const medianMetric = story.steps[1].metrics.find((item) => item.label === "Median prix")
  assert.equal(medianMetric.value, 105)
  const roeMetric = story.steps[0].metrics.find((item) => item.label === "ROE")
  assert.equal(roeMetric.value, 0.14)
  assert.equal(roeMetric.source, "3Y trailing average of annual ROE")
  assert.equal(check(story, "ROE source connue")?.ok, true)
  assert.deepEqual(story.steps[1].table.columns, ["Multiple", "Observe", "Justifie", "Calcul", "Prix implicite"])
  assert.match(story.steps[1].table.rows[0][3], /14\.00% - 3\.00%/)
})

test("relative multiples story explains peer rows and EV bridge", () => {
  const story = buildValuationModelStory({
    model: "relative_multiples",
    fair_value: 105,
    inputs: {
      peer_stats: {
        PER: { median: 12, count: 8, scope: "sector" },
        Price_to_Book: { median: 1.8, count: 8, scope: "sector" },
        Price_to_Sales: { median: 2, count: 8, scope: "sector" },
        EV_to_EBITDA: { median: 7, count: 6, scope: "sector" },
      },
      own_multiples: {
        PER: 10,
        Price_to_Book: 1.5,
        Price_to_Sales: 1.6,
        EV_to_EBITDA: 6,
      },
      ev_to_ebitda_bridge: {
        ebitda: 1000,
        net_debt: 200,
        net_debt_source: "reported",
        shares: 100,
      },
    },
    outputs: {
      implied_prices: {
        PER: 120,
        Price_to_Book: 120,
        Price_to_Sales: 125,
        EV_to_EBITDA: 90,
      },
    },
  }, {})

  assert.equal(story.model, "relative_multiples")
  assert.equal(check(story, "Au moins 2 multiples")?.ok, true)
  assert.equal(check(story, "Reconciliation mediane")?.ok, false)
  assert.equal(story.summary.includes("fair value/action"), true)
  assert.deepEqual(story.steps[0].table.columns, ["Ratio", "Multiple titre", "Multiple pairs", "n/scope", "Fair value / action"])
  assert.equal(story.steps[0].metrics.find((item) => item.label === "FV P/E")?.value, 120)
  assert.equal(story.steps[0].metrics.find((item) => item.label === "FV P/B")?.value, 120)
  assert.equal(story.steps[0].metrics.find((item) => item.label === "FV P/S")?.value, 125)
  assert.equal(story.steps[0].metrics.find((item) => item.label === "FV EV/EBITDA")?.value, 90)
  assert.equal(story.steps[0].metrics.find((item) => item.label === "Median FV")?.value, 120)
  const evMetric = story.steps[1].metrics.find((item) => item.label === "FV EV/EBITDA")
  assert.equal(evMetric.value, 90)
})

test("reverse DCF story computes the growth gap versus model terminal growth", () => {
  const story = buildValuationModelStory({
    model: "reverse_dcf",
    inputs: {
      market_cap: 1000,
      wacc: 0.09,
      fcf_yield: 0.05,
    },
    outputs: {
      implied_perpetual_growth: 0.04,
      interpretation: "Market implies 4.0% perpetual FCF growth at WACC=9.0%.",
    },
  }, {
    assumptions: {
      terminal_growth_firm: 0.03,
    },
  })

  assert.equal(story.model, "reverse_dcf")
  assert.match(story.title, /pas pricing/i)
  assert.match(story.summary, /pas une juste valeur/i)
  assert.equal(check(story, "g implicite calcule")?.ok, true)
  assert.equal(check(story, "Pas un prix")?.ok, true)
  const gap = story.steps[1].metrics.find((item) => item.label === "Ecart vs modele")
  assert.ok(Math.abs(gap.value - 0.01) < 1e-9)
  const fairValueMetric = story.steps[1].metrics.find((item) => item.label === "Fair value/share")
  assert.equal(fairValueMetric.value, "N/A - diagnostic")
})
