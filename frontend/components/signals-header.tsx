"use client"

import { useTransition } from "react"
import Link from "next/link"
import { signOut } from "next-auth/react"
import { usePathname } from "next/navigation"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import {
  Activity,
  BookOpen,
  ChartColumnIncreasing,
  Database,
  Gauge,
  FlaskConical,
  LayoutDashboard,
  Landmark,
  LogIn,
  LogOut,
  RefreshCw,
  Repeat2,
  Settings,
  Target,
} from "lucide-react"

const isPublicDashboardOnly = process.env.NEXT_PUBLIC_DASHBOARD_PUBLIC_ONLY === "true"
const publicBasePath = process.env.NEXT_PUBLIC_BASE_PATH || ""

const defaultNavItems = [
  { href: "/dashboard", label: "Tableau de Bord", icon: LayoutDashboard },
  { href: "/data", label: "Data", icon: Database },
  { href: "/signals", label: "Signals", icon: Activity },
  { href: "/fundamental-strategy", label: "Fundamental Lab", icon: FlaskConical },
  { href: "/strategy", label: "Strategy", icon: Target },
  { href: "/backtest", label: "Backtest", icon: Gauge },
  { href: "/analytics", label: "Analytics", icon: ChartColumnIncreasing },
  { href: "/cross-asset-research", label: "Cross-Asset Research", icon: Repeat2 },
  { href: "/offshore-lab", label: "Offshore Lab", icon: Landmark },
  { href: "/glossary", label: "Glossaire", icon: BookOpen },
]

const adminNavItems = [
  { href: "/admin/ops", label: "Ops", icon: Settings },
]

const publicNavItems = [
  { href: "/v1", label: "Tableau de bord", icon: LayoutDashboard },
  { href: "/signals", label: "Signaux", icon: Gauge },
]

const hiddenWorkspaceNavHrefs = new Set(["/strategy", "/backtest", "/analytics", "/fundamentals", "/fundamental-strategy"])

interface SignalsHeaderProps {
  sessionEmail?: string | null
  hideWorkspaceNavItems?: boolean
  isAdmin?: boolean
}

function getNavItems(hideWorkspaceNavItems: boolean, isAdmin: boolean) {
  if (isPublicDashboardOnly) return publicNavItems
  const base = !hideWorkspaceNavItems
    ? defaultNavItems
    : defaultNavItems.filter((item) => !hiddenWorkspaceNavHrefs.has(item.href))

  return isAdmin ? [...base, ...adminNavItems] : base
}

function toPublicHref(path: string): string {
  const withSlash = path.endsWith("/") ? path : `${path}/`
  return `${publicBasePath}${withSlash}`
}

function initialsFromEmail(email: string | null | undefined): string {
  const value = email?.trim()
  if (!value) return "?"

  const localPart = value.split("@")[0] || value
  const parts = localPart.split(/[\s._-]+/).filter(Boolean)
  const initials =
    parts.length > 1
      ? `${parts[0]?.[0] ?? ""}${parts[1]?.[0] ?? ""}`
      : localPart.slice(0, 2)

  return initials.toUpperCase()
}

export function SignalsHeader({ sessionEmail, hideWorkspaceNavItems = false, isAdmin = false }: SignalsHeaderProps) {
  const pathname = usePathname()
  const [isSigningOut, startSignOut] = useTransition()
  const initials = initialsFromEmail(sessionEmail)
  const navItems = getNavItems(hideWorkspaceNavItems, isAdmin)
  const mobileNavItems = navItems.filter((item) =>
    isPublicDashboardOnly
      ? item.href === "/v1" || item.href === "/signals"
      : ["/dashboard", "/data", "/signals", "/fundamental-strategy", "/glossary", "/admin/ops"].includes(item.href),
  )

  return (
    <>
    <header className="sticky top-0 z-50 h-14 w-full border-b border-line bg-[oklch(0.99_0.002_250_/_0.85)] backdrop-blur-md max-md:hidden">
      <div className="mx-auto flex h-full max-w-7xl items-center gap-3.5 px-4">
        {isPublicDashboardOnly ? (
          <a href={toPublicHref("/v1")} className="flex items-center gap-2.5" aria-label="RDT Alpha">
            <div className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-[linear-gradient(135deg,#1d4ed8_0%,#0f766e_100%)] text-[11px] font-black tracking-[0.04em] text-white">
              RDT
            </div>
            <div className="flex flex-col leading-none">
              <div className="text-[13px] font-bold tracking-normal text-foreground">
                RDT Alpha
              </div>
              <div className="mt-0.5 text-[10px] tracking-[0.04em] text-muted-foreground">
                Road to Alpha
              </div>
            </div>
          </a>
        ) : (
          <Link href="/dashboard" className="flex items-center gap-2.5" aria-label="RDT Alpha">
            <div className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-[linear-gradient(135deg,#1d4ed8_0%,#0f766e_100%)] text-[11px] font-black tracking-[0.04em] text-white">
              RDT
            </div>
            <div className="flex flex-col leading-none">
              <div className="text-[13px] font-bold tracking-normal text-foreground">
                RDT Alpha
              </div>
              <div className="mt-0.5 text-[10px] tracking-[0.04em] text-muted-foreground">
                Road to Alpha
              </div>
            </div>
          </Link>
        )}

        <nav className="ml-3 flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto">
          {navItems.map((item) => {
            const isActive = pathname.startsWith(item.href)
            const publicHref = toPublicHref(item.href)
            return (
              <Button
                key={item.href}
                variant={isActive ? "secondary" : "ghost"}
                size="sm"
                asChild
                className={cn(
                  "h-8 rounded-lg px-2.5 text-[13px] font-medium text-muted-foreground shadow-none hover:bg-bg3 hover:text-foreground",
                  isActive && "bg-bg3 text-foreground hover:bg-bg3",
                )}
              >
                {isPublicDashboardOnly ? (
                  <a href={publicHref}>
                    <item.icon className="h-3.5 w-3.5 stroke-[1.75]" suppressHydrationWarning />
                    {item.label}
                  </a>
                ) : (
                  <Link href={item.href}>
                    <item.icon className="h-3.5 w-3.5 stroke-[1.75]" suppressHydrationWarning />
                    {item.label}
                  </Link>
                )}
              </Button>
            )
          })}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <span className="hidden h-[30px] items-center gap-1.5 rounded-full border border-line bg-card px-2.5 text-xs text-muted-foreground sm:inline-flex">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--success)]" />
            MASI · live
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            title="Refresh"
            onClick={() => window.location.reload()}
            className="h-[30px] w-[30px] rounded-md border border-transparent text-muted-foreground hover:bg-bg3 hover:text-foreground"
          >
            <RefreshCw className="h-3.5 w-3.5 stroke-[1.75]" suppressHydrationWarning />
          </Button>
          {!isPublicDashboardOnly && (
            sessionEmail ? (
              <>
                <Button
                  asChild
                  variant="ghost"
                  size="sm"
                  className="h-[30px] max-w-[190px] rounded-full border border-line bg-card px-1.5 pr-2 text-muted-foreground hover:bg-bg3 hover:text-foreground"
                >
                  <Link href="/account" title={sessionEmail}>
                    <span className="grid h-[22px] w-[22px] shrink-0 place-items-center rounded-full bg-[oklch(0.86_0.04_250)] text-[10px] font-bold text-[oklch(0.30_0.06_250)]">
                      {initials}
                    </span>
                    <span className="hidden max-w-[130px] truncate text-xs lg:inline">
                      {sessionEmail}
                    </span>
                  </Link>
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  title="Se deconnecter"
                  aria-label="Se deconnecter"
                  disabled={isSigningOut}
                  onClick={() => {
                    startSignOut(() => {
                      void signOut({ redirectTo: "/login" })
                    })
                  }}
                  className="h-[30px] w-[30px] rounded-md border border-transparent text-muted-foreground hover:bg-bg3 hover:text-foreground"
                >
                  <LogOut className="h-3.5 w-3.5 stroke-[1.75]" suppressHydrationWarning />
                </Button>
              </>
            ) : (
              <Button
                asChild
                variant="ghost"
                size="sm"
                className="h-[30px] rounded-md border border-line bg-card px-2.5 text-xs font-medium text-muted-foreground hover:bg-bg3 hover:text-foreground"
              >
                <Link href="/login">
                  <LogIn className="h-3.5 w-3.5 stroke-[1.75]" suppressHydrationWarning />
                  <span className="hidden sm:inline">Se connecter</span>
                </Link>
              </Button>
            )
          )}
        </div>
      </div>
    </header>
    <nav className="fixed inset-x-0 bottom-0 z-50 border-t border-line bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden" aria-label="Mobile navigation">
      <div className="grid h-14" style={{ gridTemplateColumns: `repeat(${Math.max(mobileNavItems.length, 1)}, minmax(0, 1fr))` }}>
        {mobileNavItems.map((item) => {
          const isActive = pathname.startsWith(item.href)
          const publicHref = toPublicHref(item.href)
          return isPublicDashboardOnly ? (
            <a
              key={item.href}
              href={publicHref}
              className={cn(
                "flex min-w-0 flex-col items-center justify-center gap-0.5 px-1 text-[10px] font-medium text-muted-foreground",
                isActive && "text-primary",
              )}
            >
              <item.icon className="h-5 w-5 stroke-[1.75]" suppressHydrationWarning />
              <span className="max-w-full truncate">{item.label}</span>
            </a>
          ) : (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex min-w-0 flex-col items-center justify-center gap-0.5 px-1 text-[10px] font-medium text-muted-foreground",
                isActive && "text-primary",
              )}
            >
              <item.icon className="h-5 w-5 stroke-[1.75]" suppressHydrationWarning />
              <span className="max-w-full truncate">{item.label}</span>
            </Link>
          )
        })}
      </div>
    </nav>
    </>
  )
}
