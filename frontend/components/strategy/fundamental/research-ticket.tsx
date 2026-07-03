"use client"

import { useEffect, useRef, useState } from "react"
import type { CSSProperties } from "react"
import { CalendarDays, Loader2 } from "lucide-react"
import {
  type FundamentalStockDetail,
  type FundamentalUniverseRow,
} from "@/lib/api"
import { financialPeriodLabel } from "@/lib/fundamental-statement-utils.js"
import { cn } from "@/lib/utils"
import { FUNDAMENTAL_HORIZONS } from "./lib/constants"
import { asNumber, clampValue, fmtCap, fmtCompactMad, fmtMoney, fmtPct, formatDate, recommendationClass, recommendationLabel } from "./lib/formatters"
import { revisionArrow } from "./shared/cards"
import { FundamentalHorizon } from "./lib/types"
import { effectiveHorizonPrediction, horizonPredictionsFor, predictionForHorizon, rowAdv20, rowUpside } from "./lib/view-models"

export function ResearchTicket({
  row,
  detail,
  isRefreshing,
  selectedHorizon,
  onHorizonChange,
}: {
  row: FundamentalUniverseRow | null
  detail: FundamentalStockDetail | null
  isRefreshing: boolean
  selectedHorizon: FundamentalHorizon
  onHorizonChange: (horizon: FundamentalHorizon) => void
}) {
  const symbol = detail?.symbol ?? row?.symbol ?? "-"
  const companyName = detail?.display_name ?? detail?.company_name ?? row?.display_name ?? row?.company_name ?? "-"
  const sector = detail?.sector ?? row?.sector ?? "No sector"
  const currency = detail?.ensemble?.currency ?? row?.ensemble?.currency ?? "MAD"
  const currentPrice = detail?.ensemble?.current_price ?? asNumber(detail?.metrics?.Current_Price) ?? row?.current_price ?? null
  const { horizon: activeHorizon, prediction: activePrediction } = effectiveHorizonPrediction(detail, row, selectedHorizon)
  const ratable = (detail?.recommendation ?? row?.recommendation) !== "NR"
  const officialTargetPrice = detail?.target_price ?? row?.target_price ?? (ratable ? (detail?.ensemble?.fair_value_base ?? row?.ensemble?.fair_value_base ?? null) : null)
  const officialUpside = detail?.ensemble?.upside_pct ?? rowUpside(row)
  const targetPrice = activeHorizon === "year" ? officialTargetPrice : activePrediction?.forward_target ?? officialTargetPrice
  const upside = activeHorizon === "year" ? officialUpside : activePrediction?.upside ?? officialUpside
  const marketCap = asNumber(detail?.metrics?.MarketCap_Calc) ?? row?.market_cap ?? null
  const recommendation = detail?.recommendation ?? row?.recommendation ?? null
  const conviction = detail?.conviction ?? row?.conviction ?? 0
  const headlineScenario = detail?.headline_scenario ?? row?.headline_scenario ?? "base"
  const asOf = detail?.as_of_date ?? row?.as_of_date ?? detail?.imported_at ?? row?.imported_at
  const valuationDate = detail?.valuation_date ?? row?.valuation_date ?? null
  const targetDate = activeHorizon === "year" ? detail?.target_date ?? row?.target_date ?? activePrediction?.target_date ?? null : activePrediction?.target_date ?? detail?.target_date ?? row?.target_date ?? null
  const revision = detail?.revision_direction ?? row?.revision_direction ?? "="
  const freeFloat = detail?.free_float_pct ?? row?.free_float_pct ?? null
  const adv20 = asNumber(detail?.metrics?.ADV20) ?? rowAdv20(row)
  const availableHorizonValues = new Set<FundamentalHorizon>(
    FUNDAMENTAL_HORIZONS
      .map((item) => item.value)
      .filter((horizon) => predictionForHorizon(detail, row, horizon)),
  )
  if (!horizonPredictionsFor(detail, row).length && targetPrice != null) availableHorizonValues.add("year")
  const activeHorizonMeta = FUNDAMENTAL_HORIZONS.find((item) => item.value === activeHorizon) ?? FUNDAMENTAL_HORIZONS[2]
  const ticketRef = useRef<HTMLDivElement | null>(null)
  const [ticketLayout, setTicketLayout] = useState<{ scale: number; density: "compact" | "comfortable" | "expanded" }>({
    scale: 1,
    density: "comfortable",
  })

  useEffect(() => {
    const element = ticketRef.current
    if (!element || typeof ResizeObserver === "undefined") return

    let frame = 0
    const updateLayout = (width: number, height: number) => {
      if (width <= 0 || height <= 0) return
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(() => {
        const widthScale = clampValue(width / 900, 0.78, 1.12)
        const heightScale = clampValue(height / 155, 0.72, 1.16)
        const scale = Number(clampValue(Math.min(widthScale, heightScale), 0.72, 1.12).toFixed(3))
        const density = height < 118 || width < 720 ? "compact" : height > 205 && width > 880 ? "expanded" : "comfortable"
        setTicketLayout((current) =>
          Math.abs(current.scale - scale) > 0.01 || current.density !== density
            ? { scale, density }
            : current,
        )
      })
    }

    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect
      if (rect) updateLayout(rect.width, rect.height)
    })
    const rect = element.getBoundingClientRect()
    updateLayout(rect.width, rect.height)
    observer.observe(element)

    return () => {
      window.cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [])

  return (
    <div
      ref={ticketRef}
      className="research-ticket"
      data-capture="tearsheet"
      data-density={ticketLayout.density}
      style={{ "--rt-scale": ticketLayout.scale } as CSSProperties}
    >
      <div className="rt-left">
        <div className="rt-header-row">
          <div className="rt-identity">
            <div className="rt-name-row">
              <span className="rt-sym">{symbol}</span>
              {isRefreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" /> : null}
              <span className="rt-coname">{companyName}</span>
              <span className="rt-meta">
                <strong>{sector}</strong> - {row?.market_region ?? "Maroc"} - {currency}
              </span>
            </div>
            <div className="rt-date-caption">
              <CalendarDays className="rt-date-icon" aria-hidden="true" />
              <span>Donnees au <strong>{formatDate(asOf)}</strong></span>
              <span>Valorise le <strong>{formatDate(valuationDate)}</strong></span>
              <span>Cible <strong>{formatDate(targetDate)}</strong></span>
            </div>
          </div>
          <div className="rt-horizon-control" role="group" aria-label="Horizon cible">
            <span className="rt-horizon-label">Horizon cible</span>
            <div className="rt-horizon-buttons">
              {FUNDAMENTAL_HORIZONS.map((item) => {
                const available = availableHorizonValues.has(item.value)
                return (
                  <button
                    key={item.value}
                    type="button"
                    className={cn("rt-horizon-btn", activeHorizon === item.value && "active")}
                    disabled={!available}
                    title={available ? item.label : "Historique sub-annuel insuffisant"}
                    onClick={() => onHorizonChange(item.value)}
                  >
                    {item.label}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
        <div className="rt-prices">
          <div className="rt-price-block">
            <span className="lbl">Cours actuel</span>
            <span className="val">{fmtMoney(currentPrice, 2)}</span>
            <span className="sub">au {formatDate(asOf)}</span>
          </div>
          <div className="rt-price-block">
            <span className="lbl">Objectif {activeHorizon === "year" ? "12M" : financialPeriodLabel(activeHorizonMeta.periodType)}</span>
            <span className="val text-[oklch(0.30_0.14_260)]">{fmtMoney(targetPrice, 2)}</span>
            <span className="sub">{revisionArrow(revision)} revision {revision === "up" ? "haussiere" : revision === "down" ? "baissiere" : "inchangee"}</span>
          </div>
          <div className="rt-price-block">
            <span className="lbl">Upside / Downside</span>
            <span className={cn("val", (upside ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(upside)}</span>
            <span className="sub">vs cours actuel</span>
          </div>
          <div className="rt-price-block">
            <span className="lbl">Capitalisation</span>
            <span className="val">{fmtCap(marketCap)}</span>
            <span className="sub">Free float {freeFloat == null ? "-" : fmtPct(freeFloat, 0, false)} - ADV20 {fmtCompactMad(adv20)} MAD</span>
          </div>
        </div>
      </div>
      <div className="rt-right">
        <div className={cn("rt-rec-card", recommendationClass(recommendation))}>
          <div className="rt-rec-lbl">Recommandation {headlineScenario}</div>
          <div className={cn("rt-rec-val", recommendationClass(recommendation))}>{recommendationLabel(recommendation)}</div>
          <div className="rt-conviction">
            <span>Conviction</span>
            {[1, 2, 3, 4, 5].map((item) => (
              <span key={item} className={cn("conv-dot", item <= conviction && "on")} />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

