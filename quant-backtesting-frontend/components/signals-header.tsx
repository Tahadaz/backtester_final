"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { ChartColumnIncreasing, Database, Gauge, Target } from "lucide-react"

const navItems = [
  { href: "/data", label: "Data", icon: Database },
  { href: "/signals", label: "Signals", icon: Gauge },
  { href: "/strategy", label: "Strategy", icon: Target },
  { href: "/backtest", label: "Backtest", icon: ChartColumnIncreasing },
]

export function SignalsHeader() {
  const pathname = usePathname()

  return (
    <header className="sticky top-0 z-50 w-full border-b border-border bg-card/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
        <Link href="/data" className="flex items-center gap-2.5">
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

        <nav className="flex items-center gap-1">
          {navItems.map((item) => {
            const isActive = pathname.startsWith(item.href)
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
                <Link href={item.href}>
                  <item.icon className="h-3.5 w-3.5" />
                  {item.label}
                </Link>
              </Button>
            )
          })}
        </nav>
      </div>
    </header>
  )
}
