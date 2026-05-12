import { NextRequest, NextResponse } from "next/server"

// Local `next dev` reaches the API through localhost; containerized setups
// should continue overriding this via UPSTREAM_API_BASE or API_URL.
const UPSTREAM =
  process.env.UPSTREAM_API_BASE ??
  process.env.API_URL ??
  "http://127.0.0.1:8000"
const API_KEY = process.env.API_KEY ?? ""
const IS_PROD = process.env.NODE_ENV === "production"
const UPSTREAM_TIMEOUT_MS = Number(process.env.UPSTREAM_TIMEOUT_MS ?? "120000")
const OFFLINE_EMPTY_GET_PATHS = new Set([
  "/runs",
  "/defaults/runs",
  "/datasets",
  "/market-data/symbols",
])

type RouteParams = { path?: string[] }
type RouteContext = { params: Promise<RouteParams> | RouteParams }

function normalizePathParts(path: unknown): string[] {
  if (!Array.isArray(path)) return []
  return path.filter((part): part is string => typeof part === "string")
}

function buildTargetUrl(req: NextRequest, pathParts: string[]): string {
  const base = UPSTREAM.endsWith("/") ? UPSTREAM.slice(0, -1) : UPSTREAM
  const path = pathParts.length > 0 ? `/${pathParts.join("/")}` : ""
  return `${base}${path}${req.nextUrl.search}`
}

function buildUpstreamHeaders(req: NextRequest): Headers {
  const headers = new Headers()
  const contentType = req.headers.get("content-type")
  const accept = req.headers.get("accept")
  const authorization = req.headers.get("authorization")
  const cookie = req.headers.get("cookie")

  if (contentType) headers.set("content-type", contentType)
  if (accept) headers.set("accept", accept)
  if (authorization) headers.set("authorization", authorization)
  if (cookie) headers.set("cookie", cookie)
  if (API_KEY) headers.set("x-api-key", API_KEY)
  return headers
}

function buildResponseHeaders(upstream: Response): Headers {
  const headers = new Headers(upstream.headers)
  headers.delete("connection")
  headers.delete("transfer-encoding")
  return headers
}

function maybeOfflineFallback(method: string, pathParts: string[]): NextResponse | null {
  if (IS_PROD || method !== "GET") return null
  const path = `/${pathParts.join("/")}`
  if (!OFFLINE_EMPTY_GET_PATHS.has(path)) return null

  return NextResponse.json([], {
    status: 200,
    headers: {
      "x-upstream-offline-fallback": "1",
    },
  })
}

async function proxy(req: NextRequest, { params }: RouteContext) {
  const resolved = await params
  const pathParts = normalizePathParts(resolved?.path)
  const target = buildTargetUrl(req, pathParts)

  const method = req.method.toUpperCase()
  const headers = buildUpstreamHeaders(req)

  const init: RequestInit & { duplex?: "half" } = {
    method,
    headers,
    redirect: "manual",
  }

  if (method !== "GET" && method !== "HEAD") {
    const body = await req.arrayBuffer()
    if (body.byteLength > 0) init.body = body
  }

  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS)
  init.signal = controller.signal

  try {
    const upstream = await fetch(target, init)
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: buildResponseHeaders(upstream),
    })
  } catch (error) {
    const fallback = maybeOfflineFallback(method, pathParts)
    if (fallback) return fallback

    const detail =
      error instanceof Error && error.name === "AbortError"
        ? `Upstream request timed out after ${UPSTREAM_TIMEOUT_MS}ms`
        : error instanceof Error
          ? error.message
          : String(error)
    return NextResponse.json(
      {
        error: "Upstream API unavailable",
        detail,
        upstream: UPSTREAM,
        target,
      },
      { status: 503 }
    )
  } finally {
    clearTimeout(timeoutId)
  }
}

export async function GET(req: NextRequest, ctx: RouteContext) {
  return proxy(req, ctx)
}

export async function POST(req: NextRequest, ctx: RouteContext) {
  return proxy(req, ctx)
}

export async function PUT(req: NextRequest, ctx: RouteContext) {
  return proxy(req, ctx)
}

export async function PATCH(req: NextRequest, ctx: RouteContext) {
  return proxy(req, ctx)
}

export async function DELETE(req: NextRequest, ctx: RouteContext) {
  return proxy(req, ctx)
}
