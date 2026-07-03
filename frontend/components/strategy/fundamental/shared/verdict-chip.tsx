"use client"

import { AlertTriangle, CircleAlert, CircleCheck, Minus } from "lucide-react"
import { GlossaryTerm } from "@/components/ui/glossary-term"
import { cn } from "@/lib/utils"

export type VerdictTone = "good" | "warning" | "serious" | "neutral"

const TONE_CLASSES: Record<VerdictTone, string> = {
  good: "border-emerald-300/60 bg-emerald-500/10 text-emerald-700 dark:border-emerald-900/60 dark:text-emerald-400",
  warning: "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-200",
  serious: "border-red-300/60 bg-red-500/10 text-red-700 dark:border-red-900/60 dark:text-red-400",
  neutral: "border-line bg-muted/40 text-muted-foreground",
}

const TONE_ICONS: Record<VerdictTone, typeof CircleCheck> = {
  good: CircleCheck,
  warning: AlertTriangle,
  serious: CircleAlert,
  neutral: Minus,
}

export function VerdictChip({
  tone,
  label,
  glossaryId,
  onClick,
}: {
  tone: VerdictTone
  label: string
  glossaryId?: string
  onClick?: () => void
}) {
  const Icon = TONE_ICONS[tone]
  const clickable = Boolean(onClick)

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        TONE_CLASSES[tone],
        clickable && "cursor-pointer hover:brightness-95 dark:hover:brightness-125",
      )}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={onClick}
      onKeyDown={
        clickable
          ? (event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault()
              onClick?.()
            }
          }
          : undefined
      }
    >
      <Icon className="h-3 w-3 shrink-0" aria-hidden="true" />
      <span>{label}</span>
      {glossaryId ? <GlossaryTerm id={glossaryId} iconOnly /> : null}
    </span>
  )
}
