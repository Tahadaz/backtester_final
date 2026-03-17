"use client"

import { cn } from "@/lib/utils"

const ZONES = [
  { max: 20, color: "#ef4444", label: "Vente forte" },
  { max: 40, color: "#f97316", label: "Vente" },
  { max: 60, color: "#eab308", label: "Neutre" },
  { max: 80, color: "#22c55e", label: "Achat" },
  { max: 100, color: "#16a34a", label: "Achat fort" },
]

function getZone(pct: number) {
  return ZONES.find((z) => pct <= z.max) ?? ZONES[ZONES.length - 1]
}

const SIZE_MAP = {
  sm: { width: 120, height: 70, stroke: 10, fontSize: 14, labelSize: 9 },
  md: { width: 180, height: 105, stroke: 14, fontSize: 22, labelSize: 11 },
  lg: { width: 260, height: 150, stroke: 18, fontSize: 32, labelSize: 13 },
}

export function Speedometer({
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
  const s = SIZE_MAP[size]
  const cx = s.width / 2
  const cy = s.height - 4
  const r = cx - s.stroke / 2 - 2

  const pct = value != null ? Math.max(0, Math.min(100, value)) : 50
  const zone = getZone(pct)

  // Arc: 180 degrees from left to right (π to 0)
  const startAngle = Math.PI
  const endAngle = 0

  function arcPath(startPct: number, endPct: number) {
    const a1 = startAngle - (startPct / 100) * Math.PI
    const a2 = startAngle - (endPct / 100) * Math.PI
    const x1 = cx + r * Math.cos(a1)
    const y1 = cy - r * Math.sin(a1)
    const x2 = cx + r * Math.cos(a2)
    const y2 = cy - r * Math.sin(a2)
    const large = endPct - startPct > 50 ? 1 : 0
    return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 0 ${x2} ${y2}`
  }

  // Needle angle
  const needleAngle = startAngle - (pct / 100) * Math.PI
  const needleLen = r - s.stroke / 2 - 4
  const nx = cx + needleLen * Math.cos(needleAngle)
  const ny = cy - needleLen * Math.sin(needleAngle)

  return (
    <div className={cn("flex flex-col items-center", className)}>
      <svg width={s.width} height={s.height} viewBox={`0 0 ${s.width} ${s.height}`}>
        {/* Background arc zones */}
        {ZONES.map((z, i) => {
          const from = i === 0 ? 0 : ZONES[i - 1].max
          return (
            <path
              key={z.max}
              d={arcPath(from, z.max)}
              fill="none"
              stroke={z.color}
              strokeWidth={s.stroke}
              strokeLinecap="round"
              opacity={0.25}
            />
          )
        })}

        {/* Active arc up to value */}
        {value != null && (
          <path
            d={arcPath(0, pct)}
            fill="none"
            stroke={zone.color}
            strokeWidth={s.stroke}
            strokeLinecap="round"
          />
        )}

        {/* Needle */}
        {value != null && (
          <>
            <line
              x1={cx}
              y1={cy}
              x2={nx}
              y2={ny}
              stroke="currentColor"
              strokeWidth={2}
              className="text-foreground"
            />
            <circle cx={cx} cy={cy} r={3} fill="currentColor" className="text-foreground" />
          </>
        )}

        {/* Value text */}
        <text
          x={cx}
          y={cy - needleLen * 0.35}
          textAnchor="middle"
          fontSize={s.fontSize}
          fontWeight="bold"
          fill="currentColor"
          className="text-foreground"
        >
          {value != null ? `${Math.round(pct)}%` : "N/A"}
        </text>

        {/* Zone label */}
        <text
          x={cx}
          y={cy - needleLen * 0.35 + s.fontSize + 2}
          textAnchor="middle"
          fontSize={s.labelSize}
          fill={zone.color}
          fontWeight="600"
        >
          {value != null ? zone.label : ""}
        </text>
      </svg>
      {label && (
        <span className="text-xs text-muted-foreground mt-1 text-center">{label}</span>
      )}
    </div>
  )
}
