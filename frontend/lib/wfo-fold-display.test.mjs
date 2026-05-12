import test from "node:test"
import assert from "node:assert/strict"

import { formatWfoFoldRange } from "./wfo-fold-display.js"

test("formatWfoFoldRange prefers persisted date fields", () => {
  assert.equal(
    formatWfoFoldRange(
      {
        train_start: 0,
        train_end: 5,
        train_start_date: "2026-01-01",
        train_end_date: "2026-01-05",
      },
      "train",
    ),
    "2026-01-01 to 2026-01-05",
  )
})

test("formatWfoFoldRange trims timestamp date values", () => {
  assert.equal(
    formatWfoFoldRange(
      {
        oos_start_date: "2026-01-06T00:00:00+00:00",
        oos_end_date: "2026-01-08T00:00:00+00:00",
      },
      "oos",
    ),
    "2026-01-06 to 2026-01-08",
  )
})

test("formatWfoFoldRange falls back to bar offsets", () => {
  assert.equal(
    formatWfoFoldRange(
      {
        train_start: 0,
        train_end: 5,
      },
      "train",
    ),
    "bar 0 to bar 5",
  )
})
