import { dirname } from "node:path"
import { fileURLToPath } from "node:url"

const __dirname = dirname(fileURLToPath(import.meta.url))
const buildTarget = process.env.NEXT_BUILD_TARGET === "pages" ? "pages" : "app"
const isPagesBuild = buildTarget === "pages"

/** @type {import('next').NextConfig} */
const nextConfig = {
  ...(isPagesBuild ? { output: "export", trailingSlash: true, distDir: ".next-pages" } : {}),
  basePath: isPagesBuild ? process.env.NEXT_PUBLIC_BASE_PATH || "" : "",
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
