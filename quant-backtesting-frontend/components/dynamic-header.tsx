"use client"

import { usePathname } from "next/navigation"
import { AppHeader } from "@/components/app-header"
import { SignalsHeader } from "@/components/signals-header"

export function DynamicHeader() {
  const pathname = usePathname()

  if (
    pathname.startsWith("/data") ||
    pathname.startsWith("/signals") ||
    pathname.startsWith("/strategy") ||
    pathname.startsWith("/backtest")
  ) {
    return <SignalsHeader />
  }

  return <AppHeader />
}
