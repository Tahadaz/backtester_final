"use client"

import type { ReactNode } from "react"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"

const isPublicDashboardOnly = process.env.NEXT_PUBLIC_DASHBOARD_PUBLIC_ONLY === "true"

export function AppMain({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const isWorkspaceShellPage =
    !isPublicDashboardOnly && (pathname === "/signals" || pathname === "/backtest" || pathname === "/analytics")

  return (
    <main
      className={cn(
        isWorkspaceShellPage
          ? "h-[calc(100vh-3.5rem)] overflow-hidden max-md:h-auto max-md:min-h-[calc(100dvh-4.5rem)] max-md:overflow-visible max-md:pb-[calc(4.5rem+env(safe-area-inset-bottom))]"
          : "mx-auto w-full max-w-7xl px-4 py-6 max-md:px-3 max-md:py-4 max-md:pb-[calc(4.5rem+env(safe-area-inset-bottom))]",
      )}
    >
      {children}
    </main>
  )
}
