# 06 — Static Export and GitHub Pages

## Overview

Configure the Next.js app for static export so it can be deployed to GitHub Pages.
This step should be done LAST, after all dashboard functionality works in dev mode.

---

## File: `frontend/next.config.mjs` (MODIFY)

### Current state

```javascript
import { dirname } from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = dirname(fileURLToPath(import.meta.url))

/** @type {import('next').NextConfig} */
const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  turbopack: {
    root: __dirname,
  },
}

export default nextConfig
```

### Replace with

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "export",
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || "",
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
}

export default nextConfig
```

### Changes explained

1. **Added `output: "export"`** — tells Next.js to produce a static `out/` folder instead of a server bundle
2. **Added `basePath`** — empty in dev, set to `/<repo-name>` for GitHub Pages deployment
3. **Removed `turbopack.root`** — not needed for production builds, was only for dev server, and the `dirname`/`fileURLToPath` imports are no longer needed

---

## Fix dynamic routes for static export

Next.js static export cannot handle dynamic routes unless they have `generateStaticParams()`.
The following files need modification:

### `frontend/app/runs/[runId]/page.tsx`

Add at the top level of the file (outside the component):
```typescript
export function generateStaticParams() {
  return []
}
```

### `frontend/app/signals/variant/[id]/page.tsx`

Add at the top level:
```typescript
export function generateStaticParams() {
  return []
}
```

### `frontend/app/backtest/window/[runId]/[symbol]/[windowIndex]/page.tsx`

Add at the top level:
```typescript
export function generateStaticParams() {
  return []
}
```

### `frontend/app/api/[...path]/route.ts`

This is a catch-all API proxy route. It CANNOT exist in a static export.

**Option A** (recommended): Delete the file entirely. The dashboard doesn't use it (it reads static JSON). Other pages will lose API functionality in the static build, but that's expected — the static build is only for the dashboard demo.

**Option B**: Rename to `route.ts.bak` to keep it in the repo but exclude from the build.

**Choose Option A** — delete `frontend/app/api/[...path]/route.ts`. If you need the API proxy back for dev mode, you can restore it from git history. But note: `npm run dev` with `output: "export"` still works fine for local development — the only difference is the build output.

**IMPORTANT**: If deleting the API route breaks `npm run dev` because other pages depend on `/api/...` calls, then instead of deleting, simply add this line to the file:

```typescript
export const dynamic = "force-dynamic"
```

This tells Next.js to skip this route during static export but keep it functional in dev mode. However, `output: "export"` may still error on this. Test and adjust.

**Safest approach**: Keep the API route file, and only set `output: "export"` in a separate build script, not in the default config:

```json
// package.json — add a new script
"build:static": "NEXT_PUBLIC_BASE_PATH='' next build",
"build:pages": "NEXT_PUBLIC_BASE_PATH='/<repo-name>' next build"
```

And use a conditional in next.config:
```javascript
const nextConfig = {
  ...(process.env.STATIC_EXPORT === "true" ? { output: "export" } : {}),
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || "",
  typescript: { ignoreBuildErrors: true },
  images: { unoptimized: true },
}
```

Then build with: `STATIC_EXPORT=true npm run build`

This way, regular `npm run dev` and `npm run build` work as before, and `STATIC_EXPORT=true npm run build` produces the static output.

---

## GitHub Actions workflow

### File: `.github/workflows/deploy-pages.yml` (CREATE)

**Note**: This file goes in the REPO ROOT `.github/` directory, not in `frontend/.github/`.

```yaml
name: Deploy Dashboard to GitHub Pages

on:
  push:
    branches: [main]
    paths: ["frontend/**"]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        run: cd frontend && npm ci

      - name: Build static site
        run: cd frontend && STATIC_EXPORT=true NEXT_PUBLIC_BASE_PATH="/${{ github.event.repository.name }}" npm run build

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: frontend/out

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

### GitHub repo setup required

1. Go to repo Settings > Pages
2. Set Source to "GitHub Actions"
3. Push to main with changes in `frontend/` to trigger the workflow

---

## Verification

### Local static build

```bash
cd frontend
STATIC_EXPORT=true npm run build
npx serve out
```

Then open `http://localhost:3000/dashboard` and verify:
- Dashboard page loads
- Horizon tabs switch data
- View tabs switch between stocks/sectors/index
- No network errors (all data from static JSON)
- No API calls in the Network tab

### GitHub Pages

After deploying, visit `https://<user>.github.io/<repo-name>/dashboard` and verify the same.
