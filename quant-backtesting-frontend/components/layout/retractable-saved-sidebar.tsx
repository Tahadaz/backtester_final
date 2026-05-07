"use client"

import { useEffect, useState, type CSSProperties, type ReactNode } from "react"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

const HANDLE_WIDTH = 28

interface RetractableSavedSidebarProps {
  storageKey: string
  label: string
  expandedWidth: number
  children: ReactNode
  className?: string
}

export function RetractableSavedSidebar({
  storageKey,
  label,
  expandedWidth,
  children,
  className,
}: RetractableSavedSidebarProps) {
  const [isOpen, setIsOpen] = useState(true)
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(storageKey)
      if (raw != null) {
        setIsOpen(raw === "true")
      }
    } catch {}
    setHydrated(true)
  }, [storageKey])

  useEffect(() => {
    if (!hydrated) return
    try {
      window.localStorage.setItem(storageKey, String(isOpen))
    } catch {}
  }, [hydrated, isOpen, storageKey])

  return (
    <div
      className={cn(
        "flex min-w-0 max-xl:w-full",
        hydrated ? "transition-[width] duration-200 ease-in-out" : "transition-none",
        !isOpen && "max-xl:justify-end",
        className,
      )}
      style={
        {
          "--saved-sidebar-width": `${expandedWidth}px`,
          width: undefined,
        } as CSSProperties
      }
    >
      <div
        className={cn(
          "min-w-0 overflow-hidden",
          hydrated ? "transition-[width,opacity] duration-200 ease-in-out" : "transition-none",
          isOpen ? "w-[calc(100%-28px)] opacity-100 xl:w-[var(--saved-sidebar-width)]" : "w-0 opacity-0",
        )}
        aria-hidden={!isOpen}
      >
        {children}
      </div>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={() => setIsOpen((value) => !value)}
            className="flex h-full w-7 shrink-0 flex-col items-center justify-center gap-2 border-r border-border/70 bg-muted/20 text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground max-xl:min-h-20"
            aria-label={`${isOpen ? "Hide" : "Show"} saved ${label.toLowerCase()}`}
            title={`${isOpen ? "Hide" : "Show"} saved ${label.toLowerCase()}`}
          >
            {isOpen ? <ChevronLeft className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            <span className="[writing-mode:vertical-rl] rotate-180 text-[10px] font-semibold uppercase tracking-[0.2em]">
              Saved
            </span>
          </button>
        </TooltipTrigger>
        <TooltipContent side="right">
          {isOpen ? `Hide saved ${label.toLowerCase()}` : `Show saved ${label.toLowerCase()}`}
        </TooltipContent>
      </Tooltip>
    </div>
  )
}
