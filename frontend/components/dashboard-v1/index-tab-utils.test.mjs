import test from "node:test"
import assert from "node:assert/strict"

import {
  buildDashboardIndexPayload,
  normalizeDashboardIndexName,
  normalizeDashboardIndexShares,
  normalizeDashboardIndexSymbol,
} from "./index-tab-utils.mjs"

test("normalizeDashboardIndexName trims whitespace-only names to empty", () => {
  assert.equal(normalizeDashboardIndexName("   "), "")
  assert.equal(normalizeDashboardIndexName("\n\t  Atlas  \t"), "Atlas")
})

test("buildDashboardIndexPayload rejects blank names and trims valid names", () => {
  assert.equal(buildDashboardIndexPayload("", [{ symbol: "IAM", shares: 10 }]), null)
  assert.equal(buildDashboardIndexPayload("   ", [{ symbol: "IAM", shares: 10 }]), null)

  assert.deepEqual(buildDashboardIndexPayload("  Growth Watch  ", [
    { symbol: " iam ", shares: "12" },
    { symbol: "BCP", shares: 5 },
  ]), {
    name: "Growth Watch",
    components: [
      { symbol: "IAM", shares: 12 },
      { symbol: "BCP", shares: 5 },
    ],
  })
})

test("buildDashboardIndexPayload requires valid whole-share components", () => {
  assert.equal(buildDashboardIndexPayload("Empty", []), null)
  assert.equal(buildDashboardIndexPayload("Invalid", [{ symbol: "IAM", shares: 0 }]), null)
  assert.equal(buildDashboardIndexPayload("Invalid", [{ symbol: "IAM", shares: 1.5 }]), null)
  assert.equal(buildDashboardIndexPayload("Invalid", [{ symbol: "IAM", shares: "" }]), null)

  assert.deepEqual(buildDashboardIndexPayload("Deduped", [
    { symbol: "iam", shares: "10" },
    { symbol: "IAM", shares: "20" },
    { symbol: " atw ", shares: "3" },
  ]), {
    name: "Deduped",
    components: [
      { symbol: "IAM", shares: 10 },
      { symbol: "ATW", shares: 3 },
    ],
  })
})

test("normalizers clean symbols and share counts", () => {
  assert.equal(normalizeDashboardIndexSymbol(" iam "), "IAM")
  assert.equal(normalizeDashboardIndexShares("12"), 12)
  assert.equal(normalizeDashboardIndexShares("12,0"), 12)
  assert.equal(normalizeDashboardIndexShares("12.5"), null)
  assert.equal(normalizeDashboardIndexShares("0"), null)
})
