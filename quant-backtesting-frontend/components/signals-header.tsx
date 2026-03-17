"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Database, Gauge } from "lucide-react"

const navItems = [
  { href: "/data", label: "Données", icon: Database },
  { href: "/signals", label: "Signaux", icon: Gauge },
]

export function SignalsHeader() {
  const pathname = usePathname()

  return (
    <header className="sticky top-0 z-50 w-full border-b border-border bg-card/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
        <Link href="/" className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground text-xs font-black tracking-wider">
            BT
          </div>
          <div>
            <div className="text-sm font-bold text-foreground leading-tight">
              Backtest
            </div>
            <div className="text-[10px] text-muted-foreground leading-tight">
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
                  isActive && "bg-secondary text-secondary-foreground"
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
