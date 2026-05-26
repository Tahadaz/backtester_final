import test from "node:test"
import assert from "node:assert/strict"

import { buildFundamentalEstimateTable } from "./fundamental-estimates-utils.js"

function makeDetail(years) {
  return {
    latest_statement_year: years.at(-1) ?? null,
    metrics: {
      Chiffre_daffaires: 120,
      Resultat_net: 12,
      Free_Cash_Flow: 10,
      ROE: 0.12,
      Operating_Margin: 0.2,
      NetIncome_Growth: 0.03,
    },
    annual: years.map((year, index) => ({
      statement_year: year,
      metrics: {
        Chiffre_daffaires: 100 + index * 10,
        Resultat_net: 10 + index,
        Free_Cash_Flow: 8 + index,
        ROE: 0.1 + index * 0.01,
        Operating_Margin: 0.18 + index * 0.01,
      },
    })),
  }
}

test("estimate table includes 2026E when actual rows end in 2025", () => {
  const table = buildFundamentalEstimateTable(makeDetail([2023, 2024, 2025]), { currentYear: 2026 })

  assert.deepEqual(table.years, ["2023A", "2024A", "2025A", "2026E", "2027E", "2028E"])
  assert.equal(table.currentEstimateLabel, "2026E")
  assert.equal(table.currentEstimateIndex, 3)
})

test("estimate table treats a 2026 annual row as estimated during 2026", () => {
  const table = buildFundamentalEstimateTable(makeDetail([2024, 2025, 2026]), { currentYear: 2026 })

  assert.deepEqual(table.years, ["2024A", "2025A", "2026E", "2027E", "2028E"])
  assert.equal(table.years.includes("2026A"), false)
  assert.equal(table.currentEstimateLabel, "2026E")
  assert.equal(table.currentEstimateIndex, 2)
})

test("estimate table still surfaces 2026E when actual rows end in 2024", () => {
  const table = buildFundamentalEstimateTable(makeDetail([2022, 2023, 2024]), { currentYear: 2026 })

  assert.deepEqual(table.years, ["2022A", "2023A", "2024A", "2025E", "2026E", "2027E"])
  assert.equal(table.currentEstimateLabel, "2026E")
  assert.equal(table.currentEstimateIndex, 4)
})
