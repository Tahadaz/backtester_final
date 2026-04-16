"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { ChartColumnIncreasing, Database, Gauge, LayoutDashboard, Target } from "lucide-react"

const isPublicDashboardOnly = process.env.NEXT_PUBLIC_DASHBOARD_PUBLIC_ONLY === "true"
const publicBasePath = process.env.NEXT_PUBLIC_BASE_PATH || ""

const defaultNavItems = [
  { href: "/dashboard", label: "Tableau de Bord", icon: LayoutDashboard },
  { href: "/data", label: "Data", icon: Database },
  { href: "/signals", label: "Signals", icon: Gauge },
  { href: "/strategy", label: "Strategy", icon: Target },
  { href: "/backtest", label: "Backtest", icon: ChartColumnIncreasing },
]

const publicNavItems = [
  { href: "/v1", label: "Tableau de bord", icon: LayoutDashboard },
  { href: "/signals", label: "Signaux", icon: Gauge },
]

const navItems = isPublicDashboardOnly ? publicNavItems : defaultNavItems

function toPublicHref(path: string): string {
  const withSlash = path.endsWith("/") ? path : `${path}/`
  return `${publicBasePath}${withSlash}`
}

export function SignalsHeader() {
  const pathname = usePathname()
  const [isAtTop, setIsAtTop] = useState(true)

  useEffect(() => {
    const onScroll = () => {
      setIsAtTop(window.scrollY <= 8)
    }

    onScroll()
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => window.removeEventListener("scroll", onScroll)
  }, [])

  return (
    <header
      className={cn(
        "sticky top-0 z-50 w-full border-b border-border bg-card/80 backdrop-blur-md transition-transform duration-200",
        isAtTop ? "translate-y-0" : "-translate-y-full",
      )}
    >
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
        {isPublicDashboardOnly ? (
          <a href={toPublicHref("/v1")} className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-xs font-black tracking-wider text-primary-foreground">
              BT
            </div>
            <div>
              <div className="text-sm font-bold leading-tight text-foreground">
                Backtest
              </div>
              <div className="text-[10px] leading-tight text-muted-foreground">
                Signal Engine
              </div>
            </div>
          </a>
        ) : (
          <Link href="/dashboard" className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-xs font-black tracking-wider text-primary-foreground">
              BT
            </div>
            <div>
              <div className="text-sm font-bold leading-tight text-foreground">
                Backtest
              </div>
              <div className="text-[10px] leading-tight text-muted-foreground">
                Signal Engine
              </div>
            </div>
          </Link>
        )}

        <nav className="flex items-center gap-1">
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
                  "gap-1.5 text-xs font-semibold",
                  isActive && "bg-secondary text-secondary-foreground",
                )}
              >
                {isPublicDashboardOnly ? (
                  <a href={publicHref}>
                    <item.icon className="h-3.5 w-3.5" />
                    {item.label}
                  </a>
                ) : (
                  <Link href={item.href}>
                    <item.icon className="h-3.5 w-3.5" />
                    {item.label}
                  </Link>
                )}
              </Button>
            )
          })}
        </nav>
      </div>
    </header>
  )
}
