"use client"

import { CalendarDays, Loader2 } from "lucide-react"
import {
  type FundamentalStockDetail,
  type FundamentalUniverseRow,
} from "@/lib/api"
import { financialPeriodLabel } from "@/lib/fundamental-statement-utils.js"
import { cn } from "@/lib/utils"
import { FUNDAMENTAL_HORIZONS } from "./lib/constants"
import { asNumber, fmtCap, fmtCompactMad, fmtMoney, fmtPct, formatDate, recommendationClass, recommendationLabel } from "./lib/formatters"
import { recommendationTooltip, revisionArrow } from "./shared/cards"
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
  const officialTargetPrice = ratable ? (detail?.ensemble?.fair_value_base ?? row?.ensemble?.fair_value_base ?? null) : null
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
  const revisionLabel = revision === "up" ? "révision haussière" : revision === "down" ? "révision baissière" : "révision inchangée"

  return (
    <div className="research-ticket-v2" data-capture="tearsheet">
      <div className="rtv2-identity-row">
        <div className="rtv2-identity">
          <span className="rtv2-sym">{symbol}</span>
          {isRefreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" /> : null}
          <span className="rtv2-coname">{companyName}</span>
          <span className="rtv2-chip">{sector}</span>
          <span className="rtv2-chip">{row?.market_region ?? "Maroc"}</span>
          <span className="rtv2-chip">{currency}</span>
        </div>
        <div className="rtv2-date-caption">
          <CalendarDays className="rtv2-date-icon" aria-hidden="true" />
          <span>Données au <strong>{formatDate(asOf)}</strong></span>
          <span>Valorisé le <strong>{formatDate(valuationDate)}</strong></span>
          <span>Cible <strong>{formatDate(targetDate)}</strong></span>
        </div>
      </div>

      <div className="rtv2-kpi-strip">
        <div className="rtv2-tile">
          <span className="lbl">Cours actuel</span>
          <span className="val">{fmtMoney(currentPrice, 2)}</span>
          <span className="sub">au {formatDate(asOf)}</span>
        </div>

        <div className="rtv2-tile">
          <div className="rtv2-tile-head">
            <span className="lbl">Objectif {activeHorizon === "year" ? "12M" : financialPeriodLabel(activeHorizonMeta.periodType)}</span>
            <div className="rtv2-horizon-buttons" role="group" aria-label="Horizon cible">
              {FUNDAMENTAL_HORIZONS.map((item) => {
                const available = availableHorizonValues.has(item.value)
                return (
                  <button
                    key={item.value}
                    type="button"
                    className={cn("rtv2-horizon-btn", activeHorizon === item.value && "active")}
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
          <span className="val text-[oklch(0.30_0.14_260)]">{fmtMoney(targetPrice, 2)}</span>
          <span className="sub">{revisionArrow(revision)} {revisionLabel}</span>
        </div>

        <div className="rtv2-tile">
          <span className="lbl">Upside / Downside</span>
          <span className={cn("val", (upside ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(upside)}</span>
          <span className="sub">vs cours actuel</span>
        </div>

        <div className="rtv2-tile">
          <span className="lbl">Capitalisation</span>
          <span className="val">{fmtCap(marketCap)}</span>
          <span className="sub">Free float {freeFloat == null ? "-" : fmtPct(freeFloat, 0, false)} · ADV20 {fmtCompactMad(adv20)} MAD</span>
        </div>

        <div className={cn("rtv2-rec-card", recommendationClass(recommendation))}>
          <div className="rtv2-rec-lbl">Recommandation {headlineScenario}</div>
          <div className={cn("rtv2-rec-val", recommendationClass(recommendation))} title={recommendationTooltip(detail?.assumptions)}>
            {recommendationLabel(recommendation)}
          </div>
          <div className="rtv2-conviction">
            <span>Conviction</span>
            {[1, 2, 3, 4, 5].map((item) => (
              <span key={item} className={cn("rtv2-conv-dot", item <= conviction && "on")} />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
