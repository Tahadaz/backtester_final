"use client"

import { useEffect, useRef, useState } from "react"
import type { DashboardPreferences } from "@/lib/dashboard-preferences"
import { sanitizeDashboardPreferences } from "@/lib/dashboard-preferences"

interface DashboardPreferencesState {
  loaded: boolean
  error: string | null
}

export function useDashboardPreferences(
  enabled: boolean,
  preferences: DashboardPreferences,
  applyPreferences: (preferences: DashboardPreferences) => void,
): DashboardPreferencesState {
  const [loaded, setLoaded] = useState(!enabled)
  const [error, setError] = useState<string | null>(null)
  const hydratedRef = useRef(false)
  const skipNextSaveRef = useRef(false)

  useEffect(() => {
    if (!enabled) {
      hydratedRef.current = false
      setLoaded(true)
      setError(null)
      return
    }

    let cancelled = false
    hydratedRef.current = false
    setLoaded(false)
    setError(null)

    async function loadPreferences() {
      try {
        const response = await fetch("/api/account/preferences/dashboard", { cache: "no-store" })
        if (cancelled) return
        if (response.status === 401) {
          setLoaded(true)
          return
        }
        if (!response.ok) {
          throw new Error(`Preference load failed: ${response.status}`)
        }

        const payload = sanitizeDashboardPreferences(await response.json())
        skipNextSaveRef.current = true
        applyPreferences(payload)
        hydratedRef.current = true
        setLoaded(true)
      } catch (err) {
        if (cancelled) return
        hydratedRef.current = false
        setError(err instanceof Error ? err.message : "Preference load failed")
        setLoaded(true)
      }
    }

    void loadPreferences()

    return () => {
      cancelled = true
    }
  }, [applyPreferences, enabled])

  useEffect(() => {
    if (!enabled || !hydratedRef.current) return
    if (skipNextSaveRef.current) {
      skipNextSaveRef.current = false
      return
    }

    const timeoutId = window.setTimeout(() => {
      void fetch("/api/account/preferences/dashboard", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(preferences),
      }).catch((err) => {
        setError(err instanceof Error ? err.message : "Preference save failed")
      })
    }, 500)

    return () => window.clearTimeout(timeoutId)
  }, [enabled, preferences])

  return { loaded, error }
}
