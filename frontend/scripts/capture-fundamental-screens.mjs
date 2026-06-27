#!/usr/bin/env node

import { spawnSync } from "node:child_process"
import fs from "node:fs/promises"
import path from "node:path"
import { fileURLToPath } from "node:url"

const SCRIPT_PATH = fileURLToPath(import.meta.url)
const SCRIPT_DIR = path.dirname(SCRIPT_PATH)
const REPO_ROOT = path.resolve(SCRIPT_DIR, "../..")
const OUT_DIR = path.join(REPO_ROOT, "docs/fundamentals-layer/assets/screens")

const CAPTURES = [
  { file: "01-tearsheet.png", tab: "thesis", scenario: "base", selector: "[data-capture=tearsheet]" },
  { file: "02-valuation-models.png", tab: "valuation", scenario: "base", selector: "[data-capture=valuation-models]" },
  { file: "03-wacc-buildup.png", tab: "valuation", scenario: "base", selector: "[data-capture=wacc-buildup]" },
  { file: "04-scenarios.png", tab: "thesis", scenario: "base", selector: "[data-capture=scenarios]" },
  { file: "05-sensitivity.png", tab: "valuation", scenario: "base", selector: "[data-capture=sensitivity]" },
  { file: "06-scoring.png", tab: "quality", scenario: "base", selector: "[data-capture=scoring]" },
  { file: "07-diagnostics.png", tab: "quality", scenario: "base", selector: "[data-capture=diagnostics]" },
]

function argValue(name, fallback) {
  const flag = `--${name}`
  const index = process.argv.indexOf(flag)
  if (index >= 0 && process.argv[index + 1]) return process.argv[index + 1]
  return fallback
}

async function maybeLoadPlaywright() {
  try {
    return await import("playwright")
  } catch (error) {
    console.log(`Playwright module unavailable, using CLI fallback: ${error instanceof Error ? error.message : String(error)}`)
    return null
  }
}

function signalUrl(baseUrl, symbol, capture) {
  const url = new URL("/signals", baseUrl)
  url.searchParams.set("mode", "fundamental")
  url.searchParams.set("symbol", symbol)
  url.searchParams.set("scenario", capture.scenario)
  url.searchParams.set("fund_tab", capture.tab)
  return url.toString()
}

async function captureOne(context, baseUrl, symbol, capture) {
  const page = await context.newPage()
  const outputPath = path.join(OUT_DIR, capture.file)
  try {
    await page.goto(signalUrl(baseUrl, symbol, capture), { waitUntil: "networkidle", timeout: 45_000 })
    const locator = page.locator(capture.selector).first()
    await locator.waitFor({ state: "visible", timeout: 25_000 })
    await locator.scrollIntoViewIfNeeded()
    await page.waitForTimeout(500)
    await locator.screenshot({ path: outputPath, timeout: 15_000 })
    const stat = await fs.stat(outputPath)
    if (stat.size <= 0) throw new Error("empty screenshot")
    console.log(`CAPTURE ${capture.file}`)
    return true
  } catch (error) {
    console.log(`SKIP ${capture.file}: ${error instanceof Error ? error.message : String(error)}`)
    return false
  } finally {
    await page.close()
  }
}

async function captureOneWithCli(baseUrl, symbol, capture) {
  const outputPath = path.join(OUT_DIR, capture.file)
  const args = [
    "npx",
    "--yes",
    "playwright",
    "screenshot",
    "--browser",
    "chromium",
    "--viewport-size",
    "1600,1000",
    "--wait-for-selector",
    capture.selector,
    "--wait-for-timeout",
    "500",
    "--timeout",
    "45000",
    "--full-page",
    signalUrl(baseUrl, symbol, capture),
    outputPath,
  ]
  const result = process.platform === "win32"
    ? spawnSync(
        "powershell.exe",
        ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "& " + args.map((arg) => `'${String(arg).replace(/'/g, "''")}'`).join(" ")],
        { stdio: "inherit" },
      )
    : spawnSync(args[0], args.slice(1), { stdio: "inherit" })
  if ((result.status ?? 1) !== 0) {
    console.log(`SKIP ${capture.file}: Playwright CLI exited with ${result.status ?? 1}`)
    return false
  }
  const stat = await fs.stat(outputPath)
  if (stat.size <= 0) {
    console.log(`SKIP ${capture.file}: empty screenshot`)
    return false
  }
  console.log(`CAPTURE ${capture.file}`)
  return true
}

async function main() {
  const baseUrl = argValue("base-url", process.env.FUND_CAPTURE_BASE_URL || "http://localhost:3000").replace(/\/+$/, "")
  const symbol = argValue("symbol", process.env.FUND_CAPTURE_SYMBOL || "BOA").trim().toUpperCase()
  const minimum = Number(argValue("min", process.env.FUND_CAPTURE_MIN || "6"))
  const playwright = await maybeLoadPlaywright()

  await fs.mkdir(OUT_DIR, { recursive: true })
  if (playwright) {
    const browser = await playwright.chromium.launch({ headless: true })
    const context = await browser.newContext({
      viewport: { width: 1600, height: 1000 },
      deviceScaleFactor: 2,
    })
    try {
      let successCount = 0
      for (const capture of CAPTURES) {
        if (await captureOne(context, baseUrl, symbol, capture)) successCount += 1
      }
      if (successCount < minimum) {
        throw new Error(`Only ${successCount} screenshots captured; expected at least ${minimum}.`)
      }
      console.log(`WROTE ${successCount} screenshots to ${OUT_DIR}`)
    } finally {
      await context.close()
      await browser.close()
    }
    return
  }

  {
    let successCount = 0
    for (const capture of CAPTURES) {
      if (await captureOneWithCli(baseUrl, symbol, capture)) successCount += 1
    }
    if (successCount < minimum) {
      throw new Error(`Only ${successCount} screenshots captured; expected at least ${minimum}.`)
    }
    console.log(`WROTE ${successCount} screenshots to ${OUT_DIR}`)
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error))
  process.exit(1)
})
