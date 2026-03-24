"use client"

import { cn } from "@/lib/utils"

// Investing.com-style zones: filled wedge segments
const ZONES = [
  { label: "Vente forte", color: "#de5029" },
  { label: "Vente", color: "#ee7e31" },
  { label: "Neutre", color: "#b5b5b5" },
  { label: "Achat", color: "#4caf50" },
  { label: "Achat fort", color: "#2e7d32" },
]

const GAP_DEG = 1.5 // degrees gap between segments
const SEGMENT_SPAN = (180 - GAP_DEG * (ZONES.length - 1)) / ZONES.length // ~34.8° each

const SIZE_MAP = {
  sm: { width: 120, height: 72, innerR: 0.38, outerR: 0.92, needleR: 0.78, pivotR: 3, needleW: 1.5, labelSize: 8.5, edgeSize: 0 },
  md: { width: 180, height: 108, innerR: 0.38, outerR: 0.92, needleR: 0.78, pivotR: 4, needleW: 2, labelSize: 11, edgeSize: 8 },
  lg: { width: 260, height: 156, innerR: 0.38, outerR: 0.92, needleR: 0.78, pivotR: 5, needleW: 2.5, labelSize: 14, edgeSize: 9 },
}

function degToRad(deg: number) {
  return (deg * Math.PI) / 180
}

/** Build an SVG arc-wedge path (annular sector) from angle a1 to a2 (degrees, 0=right, CCW). */
function wedgePath(cx: number, cy: number, rInner: number, rOuter: number, a1Deg: number, a2Deg: number) {
  const a1 = degToRad(a1Deg)
  const a2 = degToRad(a2Deg)
  const large = Math.abs(a2Deg - a1Deg) > 180 ? 1 : 0

  // Outer arc: a1 → a2 (counterclockwise in SVG = sweep 0)
  const ox1 = cx + rOuter * Math.cos(a1)
  const oy1 = cy - rOuter * Math.sin(a1)
  const ox2 = cx + rOuter * Math.cos(a2)
  const oy2 = cy - rOuter * Math.sin(a2)

  // Inner arc: a2 → a1 (reverse)
  const ix1 = cx + rInner * Math.cos(a2)
  const iy1 = cy - rInner * Math.sin(a2)
  const ix2 = cx + rInner * Math.cos(a1)
  const iy2 = cy - rInner * Math.sin(a1)

  return [
    `M ${ox1} ${oy1}`,
    `A ${rOuter} ${rOuter} 0 ${large} 0 ${ox2} ${oy2}`,
    `L ${ix1} ${iy1}`,
    `A ${rInner} ${rInner} 0 ${large} 1 ${ix2} ${iy2}`,
    "Z",
  ].join(" ")
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
  const cy = s.height - 2
  const baseR = Math.min(cx, cy) - 2
  const rOuter = baseR * s.outerR
  const rInner = baseR * s.innerR
  const rNeedle = baseR * s.needleR

  // Map [-100, +100] → [0, 1] for needle position (0=left/sell, 1=right/buy)
  const norm = value != null ? Math.max(0, Math.min(1, (value + 100) / 200)) : 0.5

  // Needle angle: 180° (left) to 0° (right)
  const needleAngleDeg = 180 - norm * 180
  const needleAngle = degToRad(needleAngleDeg)
  const nx = cx + rNeedle * Math.cos(needleAngle)
  const ny = cy - rNeedle * Math.sin(needleAngle)

  // Determine active zone for label
  const zoneIndex = value != null
    ? Math.max(0, Math.min(4, Math.floor(norm * 5 - 0.0001)))
    : 2
  const activeZone = ZONES[zoneIndex === 5 ? 4 : zoneIndex]

  return (
    <div className={cn("flex flex-col items-center", className)}>
      <svg width={s.width} height={s.height} viewBox={`0 0 ${s.width} ${s.height}`}>
        {/* Filled wedge segments */}
        {ZONES.map((zone, i) => {
          // Angles: segment 0 starts at 180° (left), goes right
          const startDeg = 180 - i * (SEGMENT_SPAN + GAP_DEG)
          const endDeg = startDeg - SEGMENT_SPAN
          return (
            <path
              key={i}
              d={wedgePath(cx, cy, rInner, rOuter, endDeg, startDeg)}
              fill={zone.color}
            />
          )
        })}

        {/* Needle */}
        {value != null && (
          <>
            {/* Needle triangle for a sharper look */}
            <line
              x1={cx}
              y1={cy}
              x2={nx}
              y2={ny}
              stroke="#374151"
              strokeWidth={s.needleW}
              strokeLinecap="round"
            />
            <circle cx={cx} cy={cy} r={s.pivotR} fill="#374151" />
          </>
        )}

        {/* Zone label below needle */}
        <text
          x={cx}
          y={cy - rInner * 0.55}
          textAnchor="middle"
          fontSize={s.labelSize}
          fontWeight="700"
          fill={activeZone.color}
        >
          {value != null ? activeZone.label : ""}
        </text>

        {/* Edge labels (md/lg only) */}
        {s.edgeSize > 0 && (
          <>
            <text
              x={cx - rOuter + 4}
              y={cy + s.edgeSize + 4}
              textAnchor="start"
              fontSize={s.edgeSize}
              fill="#9ca3af"
            >
              Vente forte
            </text>
            <text
              x={cx + rOuter - 4}
              y={cy + s.edgeSize + 4}
              textAnchor="end"
              fontSize={s.edgeSize}
              fill="#9ca3af"
            >
              Achat fort
            </text>
          </>
        )}
      </svg>
      {label && (
        <span className="text-xs text-muted-foreground mt-1 text-center">{label}</span>
      )}
    </div>
  )
}
