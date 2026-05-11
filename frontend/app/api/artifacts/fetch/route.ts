import { NextRequest, NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
])

function addHostFromUrl(hosts: Set<string>, value: string | undefined) {
  if (!value) return
  try {
    const parsed = new URL(value)
    hosts.add(parsed.hostname.toLowerCase())
  } catch {
    // Not a URL; ignore it.
  }
}

function allowedArtifactHosts(): Set<string> {
  const hosts = new Set(["minio", "localhost", "127.0.0.1", "::1"])
  const minioHost = process.env.ARTIFACT_MINIO_HOST?.trim().toLowerCase()
  if (minioHost) hosts.add(minioHost)
  addHostFromUrl(hosts, process.env.ARTIFACT_MINIO_PUBLIC_ORIGIN)
  return hosts
}

function responseHeaders(upstream: Response): Headers {
  const headers = new Headers(upstream.headers)
  for (const name of HOP_BY_HOP_HEADERS) headers.delete(name)
  headers.delete("set-cookie")
  headers.set("cache-control", "no-store")
  return headers
}

export async function GET(req: NextRequest) {
  const rawUrl = req.nextUrl.searchParams.get("url")
  if (!rawUrl) {
    return NextResponse.json({ error: "Missing artifact URL" }, { status: 400 })
  }

  let artifactUrl: URL
  try {
    artifactUrl = new URL(rawUrl)
  } catch {
    return NextResponse.json({ error: "Invalid artifact URL" }, { status: 400 })
  }

  if (!["http:", "https:"].includes(artifactUrl.protocol)) {
    return NextResponse.json({ error: "Unsupported artifact URL protocol" }, { status: 400 })
  }

  const allowedHosts = allowedArtifactHosts()
  if (!allowedHosts.has(artifactUrl.hostname.toLowerCase())) {
    return NextResponse.json({ error: "Artifact host is not allowed" }, { status: 400 })
  }

  const accept = req.headers.get("accept") ?? undefined
  const upstream = await fetch(artifactUrl, {
    headers: accept ? { accept } : undefined,
    cache: "no-store",
  })

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: responseHeaders(upstream),
  })
}
