import test from "node:test"
import assert from "node:assert/strict"

import { buildWfoDetailHref } from "./signals-page-utils.js"

test("buildWfoDetailHref preserves the requested variant", () => {
  const href = buildWfoDetailHref({
    symbol: "IAM",
    horizon: "medium",
    category: "tendance",
    variant: "legacy",
  })

  assert.equal(
    href,
    "/signals/wfo-detail?symbol=IAM&horizon=medium&category=tendance&variant=legacy",
  )
})

test("buildWfoDetailHref defaults to expanded when variant is omitted", () => {
  const href = buildWfoDetailHref({
    symbol: "BCP",
    horizon: "short",
    category: "momentum",
  })

  assert.equal(
    href,
    "/signals/wfo-detail?symbol=BCP&horizon=short&category=momentum&variant=expanded",
  )
})
