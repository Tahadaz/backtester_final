"use client"

import { useState } from "react"
import { signIn } from "next-auth/react"
import { useRouter } from "next/navigation"
import Link from "next/link"

const defaultRedirect = process.env.NEXT_PUBLIC_DASHBOARD_PUBLIC_ONLY === "true" ? "/v1" : "/dashboard"

function resolvePostLoginUrl(): string {
  const raw = new URLSearchParams(window.location.search).get("callbackUrl")
  if (!raw) return defaultRedirect

  try {
    const url = new URL(raw, window.location.origin)
    if (url.origin !== window.location.origin) return defaultRedirect
    if (url.pathname === "/login" || url.pathname.startsWith("/signup")) return defaultRedirect
    return `${url.pathname}${url.search}${url.hash}` || defaultRedirect
  } catch {
    return defaultRedirect
  }
}

export default function LoginPage() {
  const router = useRouter()
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    const fd = new FormData(e.currentTarget)
    const result = await signIn("credentials", {
      email: String(fd.get("email") ?? ""),
      password: String(fd.get("password") ?? ""),
      redirect: false,
    })
    setLoading(false)
    if (result?.error) {
      setError("Email ou mot de passe incorrect.")
    } else {
      router.push(resolvePostLoginUrl())
      router.refresh()
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Connexion</h1>
          <p className="text-sm text-muted-foreground">Accès réservé à l&apos;équipe.</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <label htmlFor="email" className="text-sm font-medium">
              Email
            </label>
            <input
              id="email"
              name="email"
              type="email"
              required
              autoComplete="email"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          <div className="space-y-1">
            <label htmlFor="password" className="text-sm font-medium">
              Mot de passe
            </label>
            <input
              id="password"
              name="password"
              type="password"
              required
              autoComplete="current-password"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow hover:bg-primary/90 disabled:opacity-60"
          >
            {loading ? "Connexion…" : "Se connecter"}
          </button>
        </form>

        <p className="text-center text-sm text-muted-foreground">
          Pas de compte ?{" "}
          <Link href="/signup" className="underline underline-offset-4 hover:text-primary">
            Demander l&apos;accès
          </Link>
        </p>
      </div>
    </div>
  )
}
