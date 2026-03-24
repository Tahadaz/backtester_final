"use client"

import { cn } from "@/lib/utils"

function getSignalInfo(value: number | null | undefined) {
  if (value == null) return { label: "NEUTRE", cls: "text-slate-500", dotColor: "bg-slate-400" }
  if (value > 50) return { label: "ACHAT FORT", cls: "text-emerald-700", dotColor: "bg-emerald-600" }
  if (value > 15) return { label: "ACHAT", cls: "text-green-600", dotColor: "bg-green-500" }
  if (value >= -15) return { label: "NEUTRE", cls: "text-slate-500", dotColor: "bg-slate-400" }
  if (value >= -50) return { label: "VENTE", cls: "text-orange-600", dotColor: "bg-orange-500" }
  return { label: "VENTE FORTE", cls: "text-red-700", dotColor: "bg-red-600" }
}

const SIZE_CONFIG = {
  sm: { barH: "h-1.5", textSize: "text-xs", scoreSize: "text-xs", dotSize: "h-3 w-3", gap: "gap-1", showScale: false },
  md: { barH: "h-2", textSize: "text-sm", scoreSize: "text-sm", dotSize: "h-4 w-4", gap: "gap-1.5", showScale: false },
  lg: { barH: "h-2.5", textSize: "text-base", scoreSize: "text-base", dotSize: "h-4 w-4", gap: "gap-2", showScale: true },
}

export function SignalScoreBar({
  value,
  label,
  size = "md",
  className,
}: {
  value: number | null | undefined
  label?: string
  size?: "sm" | "md" | "lg"
  className?: string
}) {
  const s = SIZE_CONFIG[size]
  const info = getSignalInfo(value)
  // Map [-100, +100] to [0%, 100%]
  const norm = value != null ? Math.max(0, Math.min(100, ((value + 100) / 200) * 100)) : 50

  return (
    <div className={cn("flex flex-col", s.gap, className)}>
      {/* Label + score */}
      <div className="flex items-center justify-between">
        <span className={cn("font-bold tracking-wide", s.textSize, info.cls)}>
          {info.label}
        </span>
        <span className={cn("font-mono font-semibold", s.scoreSize, info.cls)}>
          {value != null ? (value > 0 ? `+${value.toFixed(0)}` : value.toFixed(0)) : "—"}
        </span>
      </div>

      {label && (
        <span className="text-[10px] text-muted-foreground">{label}</span>
      )}

      {/* Bar */}
      <div className="relative">
        <div
          className={cn(
            "w-full rounded-full overflow-hidden",
            s.barH,
          )}
          style={{
            background: "linear-gradient(to right, #dc2626, #ef4444, #d4d4d8, #22c55e, #16a34a)",
          }}
        />
        {/* Marker dot */}
        <div
          className={cn(
            "absolute top-1/2 -translate-y-1/2 -translate-x-1/2 rounded-full border-2 border-white shadow-sm",
            s.dotSize,
            info.dotColor,
          )}
          style={{ left: `${norm}%` }}
        />
      </div>

      {/* Scale labels (lg only) */}
      {s.showScale && (
        <div className="flex justify-between text-[10px] text-muted-foreground font-mono">
          <span>-100</span>
          <span>0</span>
          <span>+100</span>
        </div>
      )}
    </div>
  )
}
