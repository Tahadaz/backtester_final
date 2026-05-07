"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import {
  BarChart3,
  BarChart2,
  PlusCircle,
  BookOpen,
  Layers3,
  Activity,
  SlidersHorizontal,
  Database,
} from "lucide-react"

const navItems = [
  { href: "/", label: "Dashboard", icon: BarChart3 },
  { href: "/new-run", label: "New Run", icon: PlusCircle },
  { href: "/results", label: "Global Results", icon: Layers3 },
  { href: "/defaults-discovery", label: "Defaults Discovery", icon: SlidersHorizontal },
  { href: "/technical-study", label: "Technical Study", icon: Activity },
  { href: "/analytics", label: "Analytics", icon: BarChart2 },
  { href: "/data", label: "Données", icon: Database },
  { href: "/glossary", label: "Glossary", icon: BookOpen },
]

export function AppHeader() {
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
              Quant Platform
            </div>
          </div>
        </Link>

        <nav className="flex items-center gap-1">
          {navItems.map((item) => {
            const isActive =
              item.href === "/"
                ? pathname === "/"
                : pathname.startsWith(item.href)
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
