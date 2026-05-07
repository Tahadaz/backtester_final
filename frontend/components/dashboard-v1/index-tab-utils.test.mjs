import test from "node:test"
import assert from "node:assert/strict"

import { buildDashboardIndexPayload, normalizeDashboardIndexName } from "./index-tab-utils.mjs"

test("normalizeDashboardIndexName trims whitespace-only names to empty", () => {
  assert.equal(normalizeDashboardIndexName("   "), "")
  assert.equal(normalizeDashboardIndexName("\n\t  Atlas  \t"), "Atlas")
})

test("buildDashboardIndexPayload rejects blank names and trims valid names", () => {
  assert.equal(buildDashboardIndexPayload("", ["IAM"]), null)
  assert.equal(buildDashboardIndexPayload("   ", ["IAM"]), null)

  assert.deepEqual(buildDashboardIndexPayload("  Growth Watch  ", ["IAM", "BCP"]), {
    name: "Growth Watch",
    symbols: ["IAM", "BCP"],
  })
})
