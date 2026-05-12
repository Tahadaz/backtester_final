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
          ? "h-[calc(100vh-3.5rem)] overflow-hidden"
          : "mx-auto w-full max-w-7xl px-4 py-6",
      )}
    >
      {children}
    </main>
  )
}
