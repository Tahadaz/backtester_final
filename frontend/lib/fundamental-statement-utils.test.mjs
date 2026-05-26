import test from "node:test"
import assert from "node:assert/strict"

import {
  availableFinancialPeriodTypes,
  buildFinancialStatementTable,
  buildFinancialSummary,
} from "./fundamental-statement-utils.js"

function makeDetail() {
  return {
    latest_statement_year: 2024,
    metrics: {
      Current_Price: 120,
      MarketCap_Calc: 1200,
      Shares_Outstanding: 10,
      PER: 12,
      ROE: 0.14,
      Dividend_Yield: 0.04,
    },
    annual: [
      {
        statement_year: 2024,
        metrics: {
          Chiffre_daffaires: 1000,
          Resultat_net: 100,
          Capitaux_Propres: 90,
          Clean_Capitaux_Propres: 120,
          Total_Equity: 80,
          Free_Cash_Flow: 75,
          Dividendes: 20,
        },
      },
    ],
    period_metrics: [
      {
        fiscal_year: 2024,
        period_type: "quarterly",
        period_label: "Q2",
        metric_name: "Resultat_net",
        metric_value: 42,
      },
    ],
  }
}

test("available periods include annual plus stored quarterly rows", () => {
  assert.deepEqual(availableFinancialPeriodTypes(makeDetail()), ["annual", "quarterly"])
})

test("balance sheet collapses raw and clean equity aliases into one display row", () => {
  const table = buildFinancialStatementTable(makeDetail(), "balance", "annual")
  const equity = table.rows.find((row) => row.key === "total_equity")

  assert.equal(equity?.label, "Capitaux propres")
  assert.equal(equity?.values[0]?.value, 120)
  assert.equal(equity?.values[0]?.sourceMetric, "Clean_Capitaux_Propres")
  assert.equal(table.rows.filter((row) => row.label.includes("Capitaux propres")).length, 1)
})

test("quarterly period metrics feed statement tables", () => {
  const table = buildFinancialStatementTable(makeDetail(), "income", "quarterly")

  assert.deepEqual(table.periods.map((period) => period.label), ["2024 Q2"])
  assert.equal(table.rows.find((row) => row.key === "net_income")?.values[0]?.value, 42)
})

test("financial summary uses latest metrics for key ratio cards", () => {
  const summary = buildFinancialSummary(makeDetail(), "annual")

  assert.equal(summary.keyRatios.find((row) => row.key === "per")?.value, 12)
  assert.equal(summary.highlights.rows.find((row) => row.key === "free_cash_flow")?.values[0]?.value, 75)
})
