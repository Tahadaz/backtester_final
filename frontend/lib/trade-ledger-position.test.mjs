import test from "node:test"
import assert from "node:assert/strict"

import {
  ledgerRowsWithDisplayPositions,
  tradeLedgerPositionDelta,
} from "./trade-ledger-position.js"

test("tradeLedgerPositionDelta treats buys and covers as plus one", () => {
  assert.equal(tradeLedgerPositionDelta({ side: "ACHAT" }), 1)
  assert.equal(tradeLedgerPositionDelta({ marker_label: "Buy 1" }), 1)
  assert.equal(tradeLedgerPositionDelta({ marker_label: "Cover 1" }), 1)
})

test("tradeLedgerPositionDelta treats sells and shorts as minus one", () => {
  assert.equal(tradeLedgerPositionDelta({ side: "VENTE" }), -1)
  assert.equal(tradeLedgerPositionDelta({ marker_label: "Sell 1" }), -1)
  assert.equal(tradeLedgerPositionDelta({ marker_label: "Short 1" }), -1)
})

test("ledgerRowsWithDisplayPositions accumulates consecutive buys without a cap", () => {
  const rows = ledgerRowsWithDisplayPositions([
    { marker_label: "Buy 1" },
    { marker_label: "Buy 2" },
    { marker_label: "Buy 3" },
    { marker_label: "Buy 4" },
  ])

  assert.deepEqual(rows.map((item) => item.displayPosition), [1, 2, 3, 4])
})

test("ledgerRowsWithDisplayPositions accumulates consecutive shorts without a cap", () => {
  const rows = ledgerRowsWithDisplayPositions([
    { marker_label: "Short 1" },
    { marker_label: "Short 2" },
    { marker_label: "Short 3" },
    { marker_label: "Short 4" },
  ])

  assert.deepEqual(rows.map((item) => item.displayPosition), [-1, -2, -3, -4])
})

test("ledgerRowsWithDisplayPositions applies every buy and sell as one unit", () => {
  const rows = ledgerRowsWithDisplayPositions([
    { side: "ACHAT" },
    { side: "ACHAT" },
    { side: "VENTE" },
    { side: "VENTE" },
    { side: "VENTE" },
    { side: "ACHAT" },
  ])

  assert.deepEqual(rows.map((item) => item.displayPosition), [1, 2, 1, 0, -1, 0])
})

test("ledgerRowsWithDisplayPositions seeds filtered ledgers from backend position", () => {
  const rows = ledgerRowsWithDisplayPositions([
    { marker_label: "Sell 2", position: 0 },
    { marker_label: "Buy 3", position: 1 },
    { marker_label: "Buy 4", position: 2 },
  ])

  assert.deepEqual(rows.map((item) => item.displayPosition), [0, 1, 2])
})
