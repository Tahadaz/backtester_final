const fs = require("node:fs")
const path = require("node:path")

const outDir = path.join(__dirname, "..", "out-pages")

if (!fs.existsSync(outDir)) {
  console.error(`Missing export output: ${outDir}`)
  process.exit(1)
}

const keepTopLevel = new Set([
  "_next",
  "v1",
  "signals",
  "data",
  "index.html",
  "404.html",
  "icon.svg",
  "icon-light-32x32.png",
  "icon-dark-32x32.png",
  "apple-icon.png",
  "favicon.ico",
])

for (const entry of fs.readdirSync(outDir)) {
  if (keepTopLevel.has(entry)) continue
  const target = path.join(outDir, entry)
  fs.rmSync(target, { recursive: true, force: true })
  console.log(`Removed unexpected export entry: ${entry}`)
}

// Keep static JSON datasets under /data, but remove the public /data page artifacts.
const dataDir = path.join(outDir, "data")
if (fs.existsSync(dataDir)) {
  for (const entry of fs.readdirSync(dataDir)) {
    const keepDataFile =
      entry === ".gitkeep" ||
      /^scores-(short|medium|long)\.json$/.test(entry) ||
      /^signals-(short|medium|long)\.json$/.test(entry)

    if (keepDataFile) continue

    const target = path.join(dataDir, entry)
    fs.rmSync(target, { recursive: true, force: true })
    console.log(`Removed /data route artifact: data/${entry}`)
  }
}

const forbiddenPaths = [
  path.join(outDir, "api"),
  path.join(outDir, "backtest"),
  path.join(outDir, "data", "index.html"),
  path.join(outDir, "data", "index.txt"),
  path.join(outDir, "defaults-discovery"),
  path.join(outDir, "glossary"),
  path.join(outDir, "new-run"),
  path.join(outDir, "results"),
  path.join(outDir, "runs"),
  path.join(outDir, "strategy"),
  path.join(outDir, "technical-study"),
  path.join(outDir, "v2"),
  path.join(outDir, "dashboard"),
]

const remainingForbidden = forbiddenPaths.filter((item) => fs.existsSync(item))
if (remainingForbidden.length > 0) {
  console.error("Forbidden public routes detected in static artifact:")
  for (const item of remainingForbidden) {
    console.error(`- ${path.relative(outDir, item)}`)
  }
  process.exit(1)
}

console.log("Prune and route guard passed for public v1 + signals publish (data page hidden, JSON kept).")
