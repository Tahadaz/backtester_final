"use client"

import {
  type FundamentalStockDetail,
  type FundamentalUniverseRow,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import { SCENARIOS } from "../lib/constants"
import { asNumber, fmtMoney, fmtPct } from "../lib/formatters"
import { FundCard } from "../shared/cards"
import { Scenario } from "../lib/types"
import { rowUpside, screenRecord, screensFor } from "../lib/view-models"

function scenarioProbability(detail: FundamentalStockDetail, scenario: Scenario): number {
  const fromPayload = asNumber(detail.scenario_probabilities?.[scenario])
  if (fromPayload != null) return fromPayload
  const fromAssumptions = asNumber(detail.assumptions[`scenario_probability_${scenario}`])
  if (fromAssumptions != null) return fromAssumptions
  return 1 / SCENARIOS.length
}


function buildScenarios(detail: FundamentalStockDetail, targetOverride?: number | null) {
  const ensembleFor = (key: Scenario) => detail.ensembles?.[key]
  const current =
    detail.ensemble?.current_price ??
    ensembleFor("base")?.current_price ??
    ensembleFor("bear")?.current_price ??
    ensembleFor("bull")?.current_price ??
    asNumber(detail.metrics.Current_Price)
  const hasOverride = targetOverride !== undefined
  const selectedFairValue = detail.ensemble?.fair_value_base ?? detail.target_price ?? null
  const base = hasOverride
    ? targetOverride
    : ensembleFor("base")?.fair_value_base ?? (detail.ensemble?.scenario === "base" ? selectedFairValue : null) ?? detail.target_price ?? null
  const bear = hasOverride
    ? (base != null ? base * 0.85 : null)
    : ensembleFor("bear")?.fair_value_base ??
      (detail.ensemble?.scenario === "bear" ? selectedFairValue : null) ??
      detail.ensemble?.fair_value_low ??
      detail.ensemble?.monte_carlo_low ??
      (base != null ? base * 0.85 : null)
  const bull = hasOverride
    ? (base != null ? base * 1.15 : null)
    : ensembleFor("bull")?.fair_value_base ??
      (detail.ensemble?.scenario === "bull" ? selectedFairValue : null) ??
      detail.ensemble?.fair_value_high ??
      detail.ensemble?.monte_carlo_high ??
      (base != null ? base * 1.15 : null)
  return [
    {
      key: "bear",
      label: "Bear - downside",
      probability: scenarioProbability(detail, "bear"),
      price: bear,
      tone: "bear",
      drivers: ["Marge sous pression", "Multiples sectoriels en contraction", "Hausse du cout du capital"],
    },
    {
      key: "base",
      label: "Base - central",
      probability: scenarioProbability(detail, "base"),
      price: base,
      tone: "base",
      drivers: ["Execution conforme aux tendances historiques", "Ponderation multi-modeles active", "Qualite des donnees integree"],
    },
    {
      key: "bull",
      label: "Bull - upside",
      probability: scenarioProbability(detail, "bull"),
      price: bull,
      tone: "bull",
      drivers: ["Expansion des marges", "Re-rating de multiples", "Conversion cash meilleure que prevu"],
    },
  ].map((scenario) => ({
    ...scenario,
    upside: scenario.price != null && current != null && current > 0 ? scenario.price / current - 1 : null,
  }))
}


export function ThesisTab({
  detail,
  row,
}: {
  detail: FundamentalStockDetail
  row: FundamentalUniverseRow | null
}) {
  const scenarios = buildScenarios(detail)
  const expected = scenarios.some((scenario) => scenario.price != null) ? scenarios.reduce((sum, scenario) => sum + (scenario.price ?? 0) * scenario.probability, 0) : null
  const recommendation = detail.recommendation ?? row?.recommendation ?? null
  const fairValue = detail.target_price ?? (recommendation !== "NR" ? detail.ensemble?.fair_value_base : null)
  const upside = detail.ensemble?.upside_pct ?? rowUpside(row)
  const screens = screensFor(detail, row)
  const altman = screenRecord(screens, "altman_z")
  const evaScreen = screenRecord(screens, "eva")

  const risks = [
    ["Valorisation", "Le prix de marche peut rester decorele de la juste valeur si la liquidite se contracte.", 2, "Baissier"],
    ["Bilan", altman.zone ? `Zone Altman: ${String(altman.zone)}.` : "Risque de bilan non qualifie par manque de donnees.", altman.zone === "distress" ? 3 : 2, "Baissier"],
    ["Capital", evaScreen.applicable === false ? "EVA non applicable au secteur financier." : "ROIC/WACC sensible aux hypotheses de marge et de capital employe.", 2, "Baissier"],
  ] as const

  return (
    <div className="fund-gap">
      <div className="fund-thesis">
        <div className="fund-eyebrow">These d'investissement</div>
        {recommendation ? (
          <p>
            {detail.symbol} ressort a <strong>{recommendation}</strong> avec un objectif 12 mois de <strong>{fmtMoney(fairValue, 2)} {detail.ensemble?.currency ?? "MAD"}</strong>, soit un potentiel de{" "}
            <strong className={(upside ?? 0) >= 0 ? "t-pos" : "t-neg"}>{fmtPct(upside)}</strong>. La recommandation combine la juste valeur issue des modeles, la confiance de l'ensemble et l'etendue des modeles utilisables.
          </p>
        ) : (
          <p>
            {detail.symbol} n'a pas de recommandation valorisation exploitable. Les scores fondamentaux restent disponibles, mais l'objectif 12 mois attend un ensemble de modeles avec prix cible et confiance calcules.
          </p>
        )}
        <p>
          La lecture fondamentale est completee par les scores transversaux, les diagnostics comptables et les ecrans institutionnels. Les risques principaux restent la qualite des donnees publiees, la dispersion entre modeles et la sensibilite aux hypotheses de cout du capital.
        </p>
      </div>

      <div data-capture="scenarios">
        <div className="fund-section-label">Scenarios a 12 mois - fourchette bear/base/bull</div>
        <div className="scn-grid">
          {scenarios.map((scenario) => (
            <div key={scenario.key} className={cn("scn-card", scenario.tone)}>
              <div className="scn-hdr">
                <span className={cn("scn-lbl", scenario.tone)}>{scenario.label} - {(scenario.probability * 100).toFixed(0)}%</span>
                <span className="scn-prob">P={scenario.probability.toFixed(2)}</span>
              </div>
              <span className={cn("scn-price", scenario.key === "bear" ? "t-neg" : scenario.key === "bull" ? "t-pos" : "text-[oklch(0.30_0.14_260)]")}>{fmtMoney(scenario.price, 1)} MAD</span>
              <span className={cn("scn-up", (scenario.upside ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(scenario.upside)}</span>
              <ul className="scn-drivers">
                {scenario.drivers.map((driver) => (
                  <li key={driver}>{driver}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="mt-2 text-right text-[11px] text-muted-foreground">
          Valeur ponderee par scenario (probabilites maison) = <strong className="text-foreground">{fmtMoney(expected, 1)} MAD</strong>
        </div>
      </div>

      <FundCard title="Catalyseurs a venir" aside="Prochains 6 mois">
        <div className="cat-list">
          {[
            ["T+30j", "Publication financiere", "Mise a jour des derniers agregats annuels et periode intermediaire.", "high"],
            ["T+60j", "Revision hypotheses", "Revue du WACC, croissance terminale et payout apres donnees de marche.", "medium"],
            ["T+90j", "Rebalancement universe", "Reclassement relatif apres recompute des scores sectoriels.", "medium"],
          ].map(([date, title, desc, impact]) => (
            <div key={title} className="cat-item">
              <span className="cat-date">{date}</span>
              <span>
                <span className="cat-title">{title}</span>
                <span className="cat-desc">{desc}</span>
              </span>
              <span className={cn("cat-imp", impact)}>{impact === "high" ? "Eleve" : "Modere"}</span>
            </div>
          ))}
        </div>
      </FundCard>

      <FundCard title="Principaux risques">
        {risks.map(([category, text, severity, direction]) => (
          <div key={category} className="risk-row">
            <span className="risk-cat">{category}</span>
            <span className="risk-text">{text}</span>
            <span className="risk-meter">
              {[1, 2, 3].map((bar) => (
                <span key={bar} className={cn("risk-bar", bar <= severity && "on", severity === 3 ? "h" : severity === 2 ? "m" : "l")} />
              ))}
            </span>
            <span className={String(direction) === "Haussier" ? "t-pos" : "t-neg"}>{direction}</span>
          </div>
        ))}
      </FundCard>
    </div>
  )
}

