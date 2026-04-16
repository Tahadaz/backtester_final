const { spawnSync } = require("node:child_process")
const fs = require("node:fs")
const path = require("node:path")

if (!process.env.NEXT_PUBLIC_BASE_PATH) {
  console.warn("NEXT_PUBLIC_BASE_PATH is not set. Falling back to ''.")
}

const rootDir = path.join(__dirname, "..")
const outDir = path.join(rootDir, "out-pages")

const disableTargets = [
  "app/api/[...path]/route.ts",
  "app/signals/variant/[id]/page.tsx",
  "app/signals/sr-family/page.tsx",
  "app/signals/sr-method/[id]/page.tsx",
  "app/signals/sr-variant/[id]/page.tsx",
  "app/signals/sr-variants/page.tsx",
  "app/backtest/window/[runId]/page.tsx",
  "app/runs/[runId]/page.tsx",
]

if (fs.existsSync(outDir)) {
  fs.rmSync(outDir, { recursive: true, force: true })
}

// The pages build is the "public dashboard only" target. Pin this flag so
// `app/page.tsx` always redirects to /v1 (not /dashboard, which prune-pages-output.js
// strips), regardless of who sets NEXT_PUBLIC_DASHBOARD_PUBLIC_ONLY in the shell.
const env = {
  ...process.env,
  NEXT_BUILD_TARGET: "pages",
  NEXT_PUBLIC_BASE_PATH: process.env.NEXT_PUBLIC_BASE_PATH ?? "",
  NEXT_PUBLIC_DASHBOARD_PUBLIC_ONLY: "true",
}

const movedTargets = []

for (const relativeTarget of disableTargets) {
  const source = path.join(rootDir, relativeTarget)
  if (!fs.existsSync(source)) continue

  const backup = `${source}.__pages_build_disabled__`
  if (fs.existsSync(backup)) {
    fs.rmSync(backup, { recursive: true, force: true })
  }
  fs.renameSync(source, backup)
  movedTargets.push({ source, backup })
}

let exitCode = 1
try {
  const nextCli = require.resolve("next/dist/bin/next")
  const result = spawnSync(process.execPath, [nextCli, "build", "--webpack"], {
    stdio: "inherit",
    cwd: rootDir,
    env,
  })

  if (typeof result.status === "number") {
    exitCode = result.status
  }
} finally {
  if (exitCode === 0) {
    const outCandidate = path.join(rootDir, "out")
    const distCandidate = path.join(rootDir, ".next-pages")
    const builtOutDir = fs.existsSync(outCandidate) ? outCandidate : distCandidate

    if (!fs.existsSync(builtOutDir)) {
      console.error(`Missing export output: ${outCandidate} or ${distCandidate}`)
      exitCode = 1
    } else {
      fs.cpSync(builtOutDir, outDir, { recursive: true })
    }
  }

  for (const { source, backup } of movedTargets.reverse()) {
    if (fs.existsSync(source)) {
      fs.rmSync(source, { recursive: true, force: true })
    }
    if (fs.existsSync(backup)) {
      fs.renameSync(backup, source)
    }
  }
}

process.exit(exitCode)
