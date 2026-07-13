// Registry of IPO valuation profiles: the built-in, prospectus-sourced T2S
// profile plus any user-created custom profiles persisted to localStorage.
//
// Custom profiles are pure client-side scratch data - there is no backend
// endpoint for pre-IPO names (they have no price history to key off of), so
// this mirrors the existing valuation-exclusions localStorage pattern in
// view-models.ts: SSR-safe, fail-soft on parse errors, never throws.

import { IPO_T2S, type IpoPeer } from "./ipo-data"
import { buildBaseInputs, type IpoDcfInputs } from "./ipo-model"
import type { IpoJointScenario, IpoTrancheKind } from "./ipo-subscription"

export type IpoProfileMeta = {
  id: string
  name: string
  ticker: string
  sector: string
  offerPrice: number
  firstQuote: string // free text, e.g. "27/07/2026" or "n.d."
  isBuiltin: boolean
  // Anchor / last-actual-year context (what the forecast is built on top of).
  lastActualYear: number
  lastActualRevenue: number // MMAD - mirrors inputs.revenueBase, shown for context
  lastActualEbe: number | null // MMAD, null if not disclosed
  lastActualFcff: number | null // MMAD, null if not disclosed
  // Additional read-only historical years before lastActualYear, oldest first. Context only -
  // the model only cascades forward from lastActualYear's revenue (inputs.revenueBase).
  priorActualYears: Array<{ year: number; revenue: number; ebe: number | null; fcff: number | null }>
  // Reference material available for this profile (T2S has a prospectus; custom profiles don't).
  hasProspectusContext: boolean
  createdAt: string
}

export type IpoProfile = {
  meta: IpoProfileMeta
  inputs: IpoDcfInputs
  subscriptionSettings?: IpoSubscriptionSettings
  customPeers?: IpoPeer[]
}

export const T2S_PROFILE_ID = "t2s"

export type IpoSubscriptionSettings = {
  version: 5
  capitalMad: number
  tranche: IpoTrancheKind
  financingRate: number
  blockedDays: number
  // Coverage rate per tranche (prospectus p.15-16, p.53): retail must cover
  // 100% of the requested amount at subscription; qualified institutional
  // investors post none. Trading days after listing needed to exit the pop.
  retailCoverageRate: number
  institCoverageRate: number
  exitDays: number
  scenarios: IpoJointScenario[]
}

// Version 5 resets scenario returns to the J5/J10 historical calibration.
// Older settings would silently preserve the disconnected pre-calibration
// values, so they deliberately fall back to the fresh defaults.
export function isCurrentSubscriptionSettings(value: unknown): value is IpoSubscriptionSettings {
  return Boolean(value && typeof value === "object" && (value as { version?: unknown }).version === 5)
}

export function builtinT2sProfile(): IpoProfile {
  const stored = readStore().find((item) => item.meta?.id === T2S_PROFILE_ID)
  return {
    meta: {
      id: T2S_PROFILE_ID,
      name: IPO_T2S.meta.name,
      ticker: IPO_T2S.meta.ticker,
      sector: IPO_T2S.meta.sector,
      offerPrice: IPO_T2S.meta.offerPrice,
      firstQuote: IPO_T2S.meta.firstQuote,
      isBuiltin: true,
      lastActualYear: 2025,
      lastActualRevenue: 1_763,
      lastActualEbe: 388,
      lastActualFcff: null, // not broken out at FCFF granularity for historicals in the note d'operation
      priorActualYears: [
        { year: 2023, revenue: 1_374, ebe: 246, fcff: null },
        { year: 2024, revenue: 1_508, ebe: 276, fcff: null },
      ],
      hasProspectusContext: true,
      createdAt: "2026-07-06",
    },
    inputs: buildBaseInputs(),
    subscriptionSettings: isCurrentSubscriptionSettings(stored?.subscriptionSettings) ? stored.subscriptionSettings : undefined,
    customPeers: stored?.customPeers,
  }
}

const CUSTOM_IPO_STORAGE_KEY = "fundamental_custom_ipo_profiles_v1"

function readStore(): IpoProfile[] {
  if (typeof window === "undefined") return []
  try {
    const parsed = JSON.parse(window.localStorage.getItem(CUSTOM_IPO_STORAGE_KEY) ?? "[]")
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((item): item is IpoProfile => Boolean(item && typeof item === "object" && item.meta && item.inputs))
      .map((item) => (isCurrentSubscriptionSettings(item.subscriptionSettings) ? item : { ...item, subscriptionSettings: undefined }))
  } catch {
    return []
  }
}

function writeStore(profiles: IpoProfile[]) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(CUSTOM_IPO_STORAGE_KEY, JSON.stringify(profiles))
  } catch {
    // Ignore storage failures (quota, private mode, etc.) - the in-memory state still works for this session.
  }
}

export function listCustomIpoProfiles(): IpoProfile[] {
  return readStore().filter((item) => item.meta?.id !== T2S_PROFILE_ID)
}

export function saveCustomIpoProfile(profile: IpoProfile) {
  const existing = readStore()
  const next = existing.some((p) => p.meta.id === profile.meta.id)
    ? existing.map((p) => (p.meta.id === profile.meta.id ? profile : p))
    : [...existing, profile]
  writeStore(next)
}

export function deleteCustomIpoProfile(id: string) {
  writeStore(readStore().filter((p) => p.meta.id !== id))
}

export function getIpoProfile(id: string): IpoProfile | null {
  if (id === T2S_PROFILE_ID) return builtinT2sProfile()
  return readStore().find((p) => p.meta.id === id) ?? null
}

export function listAllIpoProfiles(): IpoProfile[] {
  return [builtinT2sProfile(), ...listCustomIpoProfiles()]
}

export function newCustomIpoId(): string {
  return `custom-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}
