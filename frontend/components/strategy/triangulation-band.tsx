"use client"

import type { FundamentalTriangulation, FundamentalTriangulationAnchor } from "@/lib/api"
import { cn } from "@/lib/utils"

const VERDICT_LABELS: Record<string, string> = {
  below_band: "Sous la fourchette",
  in_band_lower: "Fourchette — moitié basse",
  in_band_upper: "Fourchette — moitié haute",
  above_band: "Au-dessus de la fourchette",
  insufficient_anchors: "Ancrages insuffisants",
  no_price: "Prix indisponible",
}

const VERDICT_CHIP_CLASSES: Record<string, string> = {
  below_band: "border-emerald-300/60 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  in_band_lower: "border-sky-300/60 bg-sky-500/10 text-sky-700 dark:text-sky-400",
  in_band_upper: "border-sky-300/60 bg-sky-500/10 text-sky-700 dark:text-sky-400",
  above_band: "border-amber-300/60 bg-amber-500/10 text-amber-700 dark:text-amber-400",
  insufficient_anchors: "border-border bg-muted text-muted-foreground",
  no_price: "border-border bg-muted text-muted-foreground",
}

const WARNING_LABELS: Record<string, string> = {
  no_intrinsic_anchor: "Pas d'ancrage intrinsèque disponible",
  no_market_anchor: "Pas d'ancrage multiples de marché disponible",
  no_broker_anchor: "Pas d'objectif broker disponible",
  single_model_intrinsic_anchor: "Ancrage intrinsèque fondé sur un seul modèle",
}

const ANCHOR_LABELS: Record<string, string> = {
  intrinsic_median: "Intrinsèque (médiane)",
  market_median: "Multiples de marché",
  broker_target: "Objectif broker",
}

const ANCHOR_KIND_LABELS: Record<string, string> = {
  intrinsic: "Intrinsèque (médiane)",
  market: "Multiples de marché",
  broker: "Objectif broker",
}

const METHOD_FAMILY_LABELS: Record<string, string> = {
  intrinsic: "intrinsèque",
  multiples: "multiples",
  broker: "broker",
}


function anchorLabel(anchor: FundamentalTriangulationAnchor): string {
  return ANCHOR_LABELS[anchor.name] ?? ANCHOR_KIND_LABELS[anchor.kind] ?? anchor.name
}

function fmtVal(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "-"
  return value.toLocaleString("fr-FR", { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function fmtPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-"
  return value.toLocaleString("fr-FR", { style: "percent", maximumFractionDigits: 0, minimumFractionDigits: 0 })
}

function methodMixLabel(mix: Record<string, number>): string | null {
  const parts = Object.entries(mix)
    .filter(([, weight]) => Number.isFinite(weight) && weight > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([family, weight]) => `${fmtPct(weight)} ${METHOD_FAMILY_LABELS[family] ?? family}`)
  return parts.length ? `Ancres : ${parts.join(" / ")}` : null
}

function TriangulationBandSvg({ triangulation }: { triangulation: FundamentalTriangulation }) {
  const bandLow = triangulation.band_low
  const bandHigh = triangulation.band_high
  if (bandLow == null || bandHigh == null) return null
  const currentPrice = triangulation.current_price ?? null
  const anchors = triangulation.anchors.filter((anchor) => anchor.value != null)
  const values = anchors.map((anchor) => anchor.value as number).concat([bandLow, bandHigh])
  if (currentPrice != null) values.push(currentPrice)
  const minValue = Math.min(...values) * 0.96
  const maxValue = Math.max(...values) * 1.04
  const width = 720
  const padLeft = 24
  const padRight = 24
  const bandY = 44
  const height = 96
  const x = (value: number) => padLeft + ((value - minValue) / Math.max(1e-9, maxValue - minValue)) * (width - padLeft - padRight)

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="xMidYMid meet">
      {/* full scale baseline */}
      <line x1={padLeft} x2={width - padRight} y1={bandY} y2={bandY} stroke="var(--line)" strokeWidth="1" />
      {/* [band_low, band_high] band */}
      <line x1={x(bandLow)} x2={x(bandHigh)} y1={bandY} y2={bandY} stroke="var(--primary)" strokeWidth="12" strokeLinecap="round" opacity="0.35" />
      <text x={x(bandLow)} y={bandY + 22} textAnchor="middle" fontSize="10" fill="var(--fg3)" fontFamily="var(--font-mono)">
        {fmtVal(bandLow, 1)}
      </text>
      <text x={x(bandHigh)} y={bandY + 22} textAnchor="middle" fontSize="10" fill="var(--fg3)" fontFamily="var(--font-mono)">
        {fmtVal(bandHigh, 1)}
      </text>
      {/* anchor ticks */}
      {anchors.map((anchor, index) => {
        const anchorX = x(anchor.value as number)
        const labelY = index % 2 === 0 ? bandY - 18 : bandY + 36
        return (
          <g key={anchor.name}>
            <line x1={anchorX} x2={anchorX} y1={bandY - 9} y2={bandY + 9} stroke="oklch(0.62 0.08 250)" strokeWidth="2" />
            <text x={anchorX} y={labelY} textAnchor="middle" fontSize="10" fill="var(--fg2)" fontWeight="500">
              {anchorLabel(anchor)}
            </text>
          </g>
        )
      })}
      {/* current price marker */}
      {currentPrice != null ? (
        <g>
          <line x1={x(currentPrice)} x2={x(currentPrice)} y1={10} y2={height - 24} stroke="var(--neg)" strokeWidth="1.5" strokeDasharray="4 3" opacity="0.85" />
          <text x={x(currentPrice)} y={height - 12} textAnchor="middle" fontSize="10" fill="var(--neg)" fontWeight="700">
            Cours — {fmtVal(currentPrice, 1)}
          </text>
        </g>
      ) : null}
    </svg>
  )
}

export function TriangulationBand({ triangulation }: { triangulation: FundamentalTriangulation | null | undefined }) {
  if (!triangulation) return null
  const showBand = triangulation.band_low != null && triangulation.band_high != null && triangulation.verdict !== "insufficient_anchors"
  const anchors = triangulation.anchors
  const broker = triangulation.broker
  const agreement = triangulation.agreement
  const mixLabel = methodMixLabel(triangulation.effective_method_mix ?? {})
  const singleFamily = triangulation.anchor_diversity === "single_family"

  return (
    <div className="fund-card">
      <div className="fund-card-hdr">
        <span className="fund-card-title">Fourchette de référence triangulée</span>
        <span
          className={cn(
            "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
            VERDICT_CHIP_CLASSES[triangulation.verdict] ?? "border-border bg-muted text-muted-foreground",
          )}
        >
          {VERDICT_LABELS[triangulation.verdict] ?? triangulation.verdict}
        </span>
      </div>
      <div className="fund-card-body">
        <p className="mb-2 text-[11px] text-muted-foreground">
          Position du prix vs trois ancrages indépendants — référence, pas une prévision.
        </p>

        {showBand ? <TriangulationBandSvg triangulation={triangulation} /> : null}

        {anchors.length ? (
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[11px]">
            {anchors.map((anchor) => (
              <span key={anchor.name} className="text-muted-foreground">
                {anchorLabel(anchor)}{" "}
                <span className="font-mono text-foreground">{fmtVal(anchor.value)}</span>
                {anchor.n_models > 0 ? <span> ({anchor.n_models} modèle{anchor.n_models > 1 ? "s" : ""})</span> : null}
              </span>
            ))}
          </div>
        ) : null}

        {mixLabel ? (
          <div className="mt-2 text-[11px] text-muted-foreground">
            {mixLabel}
          </div>
        ) : null}

        {agreement != null ? (
          <div className="mt-2 text-[11px] text-muted-foreground">
            {singleFamily ? (
              <span className="font-semibold text-foreground">Corroboration limitée — ancres non indépendantes</span>
            ) : (
              <>Cohérence des ancrages : <span className="font-mono text-foreground">{Math.round(agreement * 100)}%</span></>
            )}
          </div>
        ) : null}

        {broker?.value != null ? (
          <div className="mt-1 text-[11px] text-muted-foreground">
            Objectif {broker.source ?? "broker"} : <span className="font-mono text-foreground">{fmtVal(broker.value)} {broker.currency ?? "MAD"}</span>
            {broker.as_of_date ? <span> (au {broker.as_of_date})</span> : null}
          </div>
        ) : null}

        {triangulation.warnings.length ? (
          <div className="mt-2 space-y-0.5">
            {triangulation.warnings.map((warning) => (
              <p key={warning} className="text-[10px] text-muted-foreground/80">
                {WARNING_LABELS[warning] ?? warning}
              </p>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  )
}
