"use client"

import {
  type FundamentalStockDetail,
  type FundamentalValuationResult,
} from "@/lib/api"
import { asNumber, asRecord, fmtNumber, fmtPct, fmtRatio } from "../lib/formatters"
import { StatTile } from "../shared/cards"

export function costOfCapitalBuildUp(detail: FundamentalStockDetail, row?: FundamentalValuationResult): Record<string, unknown> {
  const liveBuild = asRecord(detail.assumptions.cost_of_capital_build_up)
  const fromRow = asRecord(row ? asRecord(row.inputs).cost_of_capital : undefined)
  if (Object.keys(fromRow).length === 0) return liveBuild
  if (
    String(fromRow.beta_source ?? "") === "default_beta" &&
    String(liveBuild.beta_source ?? "") !== "default_beta" &&
    Object.keys(liveBuild).length > 0
  ) {
    return liveBuild
  }
  return fromRow
}


export function CostOfCapitalBuildUp({ detail, row }: { detail: FundamentalStockDetail; row?: FundamentalValuationResult }) {
  const build = costOfCapitalBuildUp(detail, row)
  if (!Object.keys(build).length) return null
  const riskFree = asNumber(detail.assumptions.risk_free_rate)
  const baseErp = asNumber(build.base_equity_risk_premium) ?? asNumber(detail.assumptions.equity_risk_premium) ?? 0
  const countryRiskPremium = asNumber(build.country_risk_premium) ?? asNumber(detail.assumptions.country_risk_premium) ?? 0
  const scenarioErpAddon = asNumber(build.scenario_erp_addon) ?? asNumber(detail.assumptions.scenario_erp_addon) ?? 0
  const erp = asNumber(build.effective_equity_risk_premium) ?? baseErp + countryRiskPremium + scenarioErpAddon
  const beta = asNumber(build.beta)
  const keUnfloored = asNumber(build.cost_of_equity_unfloored)
  const keFloor = asNumber(build.cost_of_equity_floor) ?? asNumber(detail.assumptions.cost_of_equity_floor)
  const keFloorBound = build.cost_of_equity_floor_bound === true
  const ke = asNumber(build.cost_of_equity)
  const kd = asNumber(build.cost_of_debt)
  const scenarioDebtAddon = asNumber(build.scenario_cost_of_debt_addon) ?? asNumber(detail.assumptions.scenario_cost_of_debt_addon) ?? 0
  const debtSource = String(build.cost_of_debt_source ?? "-")
  const debtBucket = String(build.synthetic_bucket ?? "-")
  const tax = asNumber(build.tax_rate)
  const we = asNumber(build.equity_weight)
  const wd = asNumber(build.debt_weight)
  const wacc = asNumber(build.wacc)
  const betaSource = String(build.beta_source ?? "-")
  const betaMethod = String(build.beta_method ?? "-")
  const usesDefaultBeta = betaSource === "default_beta"
  const betaMeta = [
    `source=${betaSource}`,
    `method=${betaMethod}`,
    `proxy=${String(build.market_proxy ?? "MASI")}`,
    `freq=${String(build.beta_frequency ?? "weekly")}`,
    `window=${fmtNumber(asNumber(build.beta_window_years), 1)}y`,
    `n=${fmtNumber(asNumber(build.beta_n_obs), 0)}`,
    `r2=${fmtNumber(asNumber(build.beta_r2), 3)}`,
    `zero=${fmtPct(asNumber(build.beta_zero_week_frac), 1, false)}`,
  ].join(" | ")
  return (
    <div className="cost-build-panel" data-capture="wacc-buildup">
      <div className="valuation-formula-eyebrow">Construction cout du capital</div>
      {usesDefaultBeta ? (
        <div className="mb-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-[12px] font-medium text-amber-900">
          Beta non estime - serie proxy MASI absente ou beta history vide; WACC utilise beta=1.0 par defaut.
        </div>
      ) : betaMethod !== "ols" && betaMethod !== "-" ? (
        <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-900">
          Fallback beta actif: methode {betaMethod}, generalement declenchee par liquidite ou observations insuffisantes.
        </div>
      ) : null}
      <div className="cost-build-formulas">
        <code title={betaMeta}>
          Ke = max(rf {fmtPct(riskFree, 2, false)} + beta {fmtRatio(beta, 2)} x (ERP {fmtPct(baseErp, 2, false)} + pays {fmtPct(countryRiskPremium, 2, false)} + scenario {fmtPct(scenarioErpAddon, 2, false)}) = {fmtPct(keUnfloored, 2, false)}, floor {fmtPct(keFloor, 2, false)}) = {fmtPct(ke, 2, false)}
        </code>
        <code>
          WACC = We {fmtPct(we, 1, false)} x Ke {fmtPct(ke, 2, false)} + Wd {fmtPct(wd, 1, false)} x Kd {fmtPct(kd, 2, false)} x (1 - IS {fmtPct(tax, 1, false)}) = {fmtPct(wacc, 2, false)}
        </code>
      </div>
      <div className="cost-build-grid">
        <StatTile label="Beta" value={fmtRatio(beta, 2)} sub={betaSource} />
        <StatTile label="Ke brut" value={fmtPct(keUnfloored, 2, false)} sub="rf + beta x ERP" />
        <StatTile label="Plancher Ke" value={fmtPct(keFloor, 2, false)} sub={keFloorBound ? "actif" : "non lie"} tone={keFloorBound ? "t-neg" : undefined} />
        <StatTile label="ERP effective" value={fmtPct(erp, 2, false)} sub={`add-on ${fmtPct(scenarioErpAddon, 2, false)}`} />
        <StatTile label="Dette effective" value={fmtPct(kd, 2, false)} sub={`${debtSource} ${debtBucket !== "-" ? debtBucket : ""}`.trim() || `add-on ${fmtPct(scenarioDebtAddon, 2, false)}`} />
        <StatTile label="Coverage" value={fmtRatio(asNumber(build.interest_coverage), 2)} sub={`spread ${fmtPct(asNumber(build.synthetic_spread), 2, false)}`} />
        <StatTile label="Proxy marche" value={String(build.market_proxy ?? "MASI")} sub={String(build.beta_as_of ?? "non date")} />
        <StatTile label="Obs." value={fmtNumber(asNumber(build.beta_n_obs), 0)} sub={`R2 ${fmtNumber(asNumber(build.beta_r2), 3)}`} />
        <StatTile label="Structure" value={`${fmtPct(we, 0, false)} / ${fmtPct(wd, 0, false)}`} sub={String(build.weight_source ?? "default")} />
      </div>
    </div>
  )
}

