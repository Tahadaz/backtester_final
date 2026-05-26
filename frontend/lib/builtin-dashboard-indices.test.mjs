import test from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(here, "builtin-dashboard-indices.ts"), "utf8")

function parseComponents(constName) {
  const match = source.match(new RegExp(`const ${constName}: DashboardCustomIndexComponent\\[\\] = \\[([\\s\\S]*?)\\n\\]`))
  assert.ok(match, `missing component constant ${constName}`)

  const rows = []
  for (const row of match[1].matchAll(/symbol: "([^"]+)", shares: ([0-9_]+)/g)) {
    rows.push({
      symbol: row[1],
      shares: Number(row[2].replaceAll("_", "")),
    })
  }
  return rows
}

test("built-in workbook index component counts match the source workbook", () => {
  assert.equal(parseComponents("MASI_FLOATING_SHARE_COMPONENTS").length, 78)
  assert.equal(parseComponents("MASI20_FLOATING_SHARE_COMPONENTS").length, 20)
  assert.equal(parseComponents("MASI_ESG_FLOATING_SHARE_COMPONENTS").length, 20)
  assert.equal(parseComponents("MASI_MID_SMALL_FLOATING_SHARE_COMPONENTS").length, 30)

  const sectorDefinitions = source.match(/export const MASI_SECTOR_[A-Z0-9_]+_INDEX = builtinIndex/g) ?? []
  assert.equal(sectorDefinitions.length, 24)
})

test("MASI20 shares match the workbook rounded floating-share counts", () => {
  const masi20 = parseComponents("MASI20_FLOATING_SHARE_COMPONENTS")
  assert.equal(masi20.find((component) => component.symbol === "CMG")?.shares, 8_500_450)
  assert.equal(masi20.find((component) => component.symbol === "ATW")?.shares, 55_299_801)
})

test("built-in ids are unique and all component shares are positive integers", () => {
  const ids = [...source.matchAll(/"((?:builtin-)[^"]+)"/g)].map((match) => match[1])
  assert.equal(new Set(ids).size, ids.length)

  for (const row of source.matchAll(/symbol: "([^"]+)", shares: ([0-9_]+)/g)) {
    const shares = Number(row[2].replaceAll("_", ""))
    assert.ok(Number.isInteger(shares), `${row[1]} shares should be an integer`)
    assert.ok(shares > 0, `${row[1]} shares should be positive`)
  }
})
