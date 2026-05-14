import { NextRequest, NextResponse } from "next/server"
import { auth } from "@/auth"

// Local `next dev` reaches the API through localhost; containerized setups
// should continue overriding this via UPSTREAM_API_BASE or API_URL.
const UPSTREAM =
  process.env.UPSTREAM_API_BASE ??
  process.env.API_URL ??
  "http://127.0.0.1:8000"
const API_KEY = process.env.API_KEY ?? ""
const ADMIN_API_KEY = process.env.ADMIN_API_KEY ?? ""
const IS_PROD = process.env.NODE_ENV === "production"
const UPSTREAM_TIMEOUT_MS = Number(process.env.UPSTREAM_TIMEOUT_MS ?? "120000")
const STRATEGY_UNIVERSE_TIMEOUT_MS = Number(process.env.STRATEGY_UNIVERSE_TIMEOUT_MS ?? "4000")
const OFFLINE_EMPTY_GET_PATHS = new Set([
  "/runs",
  "/defaults/runs",
  "/datasets",
  "/market-data/symbols",
])

type RouteParams = { path?: string[] }
type RouteContext = { params: Promise<RouteParams> | RouteParams }

export const runtime = "nodejs"

function normalizePathParts(path: unknown): string[] {
  if (!Array.isArray(path)) return []
  return path.filter((part): part is string => typeof part === "string")
}

function buildTargetUrl(req: NextRequest, pathParts: string[]): string {
  const base = UPSTREAM.endsWith("/") ? UPSTREAM.slice(0, -1) : UPSTREAM
  const path = pathParts.length > 0 ? `/${pathParts.join("/")}` : ""
  return `${base}${path}${req.nextUrl.search}`
}

async function currentSessionUser(): Promise<{ id?: string | null; email?: string | null } | null> {
  try {
    const session = await auth()
    return session?.user ?? null
  } catch {
    return null
  }
}

function adminEmails(): Set<string> {
  return new Set(
    (process.env.ADMIN_EMAILS ?? "")
      .split(",")
      .map((email) => email.trim().toLowerCase())
      .filter(Boolean),
  )
}

function isAdminEmail(email: string | null | undefined): boolean {
  const normalized = email?.trim().toLowerCase()
  return Boolean(normalized && adminEmails().has(normalized))
}

async function buildUpstreamHeaders(req: NextRequest, pathParts: string[]): Promise<Headers> {
  const headers = new Headers()
  const contentType = req.headers.get("content-type")
  const accept = req.headers.get("accept")
  const authorization = req.headers.get("authorization")
  const cookie = req.headers.get("cookie")
  const ifNoneMatch = req.headers.get("if-none-match")
  const user = await currentSessionUser()

  if (contentType) headers.set("content-type", contentType)
  if (accept) headers.set("accept", accept)
  if (authorization) headers.set("authorization", authorization)
  if (cookie) headers.set("cookie", cookie)
  if (ifNoneMatch) headers.set("if-none-match", ifNoneMatch)
  if (API_KEY) headers.set("x-api-key", API_KEY)
  if (ADMIN_API_KEY && pathParts[0] === "ops" && isAdminEmail(user?.email)) {
    headers.set("x-admin-api-key", ADMIN_API_KEY)
  }
  if (user?.id) headers.set("x-app-user-id", user.id)
  if (user?.email) headers.set("x-app-user-email", user.email)
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

function timeoutForPath(pathParts: string[]): number {
  const path = `/${pathParts.join("/")}`
  if (path === "/strategy/plan/universe") return STRATEGY_UNIVERSE_TIMEOUT_MS
  return UPSTREAM_TIMEOUT_MS
}

async function proxy(req: NextRequest, { params }: RouteContext) {
  const resolved = await params
  const pathParts = normalizePathParts(resolved?.path)
  const target = buildTargetUrl(req, pathParts)

  const method = req.method.toUpperCase()
  const headers = await buildUpstreamHeaders(req, pathParts)

  const init: RequestInit & { duplex?: "half" } = {
    method,
    headers,
    redirect: "manual",
  }

  if (method !== "GET" && method !== "HEAD") {
    const body = await req.arrayBuffer()
    if (body.byteLength > 0) init.body = body
  }

  const upstreamTimeoutMs = timeoutForPath(pathParts)
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), upstreamTimeoutMs)
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
        ? `Upstream request timed out after ${upstreamTimeoutMs}ms`
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
