"use client"

import { useEffect, useMemo, useState, type ReactNode } from "react"
import { Calculator, ChevronDown, CircleHelp, ShieldCheck, TrendingUp } from "lucide-react"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { GlossaryTerm } from "@/components/ui/glossary-term"
import { cn } from "@/lib/utils"
import { fmtMoney, fmtNumber, fmtPct } from "../lib/formatters"
import type { IpoBaseRateRow } from "../lib/ipo-data"
import {
  combinedExpectedEconomics,
  expectedMixturePop,
  normalizeJointScenarios,
  optimalSubscriptionAcrossScenarios,
  type IpoBaseParams,
  type IpoJointScenario,
  type IpoOptimalPoint,
  type IpoOptimalSubscription,
  type IpoPopScenario,
} from "../lib/ipo-subscription"
import type { IpoSubscriptionSettings } from "../lib/ipo-store"
import { StatTile } from "../shared/cards"

type Props = {
  settings: IpoSubscriptionSettings
  offerPrice: number
  retailTrancheShares: number
  institutionalTrancheShares: number
  institutionalMinShares: number
  retailBlockSize: number
  subscriptionCapShares: number
  baseRateRows: IpoBaseRateRow[]
  onChange: (next: IpoSubscriptionSettings) => void
}

// Draft-on-focus number input: keeps a local string while focused so clearing
// the field (or typing an intermediate invalid value) never commits 0 to the
// parent - only finite parsed values are committed, and the display reverts
// to the last committed value on blur.
function NumberInput({ value, onChange, step = 1, min = 0 }: { value: number; onChange: (value: number) => void; step?: number; min?: number }) {
  const display = Number.isFinite(value) ? String(value) : "0"
  const [draft, setDraft] = useState(display)
  const [focused, setFocused] = useState(false)

  useEffect(() => {
    if (!focused) setDraft(display)
  }, [display, focused])

  return (
    <input
      type="number"
      className="h-8 w-full rounded-md border border-line bg-card px-2 text-right text-[11px] font-mono outline-none focus-visible:ring-1 focus-visible:ring-ring"
      value={focused ? draft : display}
      min={min}
      step={step}
      onFocus={() => {
        setFocused(true)
        setDraft(display)
      }}
      onChange={(event) => {
        const next = event.target.value
        setDraft(next)
        if (next.trim() === "") return
        const n = Number(next)
        if (Number.isFinite(n)) onChange(n)
      }}
      onBlur={() => {
        setFocused(false)
        setDraft(display)
      }}
    />
  )
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value))
}

function sampleGrid<T>(rows: T[]): T[] {
  if (rows.length <= 6) return rows
  const indices = [0, Math.floor(rows.length * 0.2), Math.floor(rows.length * 0.4), Math.floor(rows.length * 0.6), Math.floor(rows.length * 0.8), rows.length - 1]
  return indices.map((index) => rows[Math.min(rows.length - 1, index)])
}

function popOf(scenario: IpoJointScenario, key: "bear" | "base" | "bull"): IpoPopScenario {
  return scenario.pops.find((p) => p.key === key) ?? scenario.pops[0]
}

function verdictFor(optimizer: IpoOptimalSubscription): { label: string; tone: string } {
  if (optimizer.reason === "below_institutional_minimum") return { label: "Inéligible (< 3 MMAD)", tone: "text-muted-foreground" }
  if (optimizer.shouldSubscribe) return { label: "Souscrire", tone: "text-emerald-600" }
  return { label: "Ne pas souscrire", tone: "text-red-600" }
}

function perCapitaHintShares(settings: IpoSubscriptionSettings, trancheShares: number): number {
  if (!settings.scenarios.length) return 0
  const totalWeight = settings.scenarios.reduce((sum, s) => sum + (s.probability || 1), 0)
  return Math.round(settings.scenarios.reduce((sum, s) => sum + (trancheShares / Math.max(1, s.retailSubscribers)) * (s.probability || 1), 0) / totalWeight)
}

export function IpoSubscriptionPanel({
  settings,
  offerPrice,
  retailTrancheShares,
  institutionalTrancheShares,
  institutionalMinShares,
  retailBlockSize,
  subscriptionCapShares,
  baseRateRows,
  onChange,
}: Props) {
  const [open, setOpen] = useState(false)

  const retailBaseParams = useMemo<IpoBaseParams>(
    () => ({
      tranche: "retail",
      trancheShares: retailTrancheShares,
      offerPrice,
      blockedDays: settings.blockedDays,
      financingRate: settings.financingRate,
      coverageRate: settings.retailCoverageRate,
      exitDays: settings.exitDays,
      feesMad: 0,
      institutionalMinShares,
      retailBlockSize,
      subscriptionCapShares,
    }),
    [institutionalMinShares, offerPrice, retailBlockSize, retailTrancheShares, settings.blockedDays, settings.exitDays, settings.financingRate, settings.retailCoverageRate, subscriptionCapShares],
  )
  const institBaseParams = useMemo<IpoBaseParams>(
    () => ({
      tranche: "institutional",
      trancheShares: institutionalTrancheShares,
      offerPrice,
      blockedDays: settings.blockedDays,
      financingRate: settings.financingRate,
      coverageRate: settings.institCoverageRate,
      exitDays: settings.exitDays,
      feesMad: 0,
      institutionalMinShares,
      retailBlockSize,
      subscriptionCapShares,
    }),
    [institutionalMinShares, institutionalTrancheShares, offerPrice, retailBlockSize, settings.blockedDays, settings.exitDays, settings.financingRate, settings.institCoverageRate, subscriptionCapShares],
  )

  const retailOptimizer = useMemo(() => optimalSubscriptionAcrossScenarios(retailBaseParams, settings.scenarios, settings.capitalMad, settings.capitalMad), [retailBaseParams, settings.capitalMad, settings.scenarios])
  const institOptimizer = useMemo(() => optimalSubscriptionAcrossScenarios(institBaseParams, settings.scenarios, settings.capitalMad, settings.capitalMad), [institBaseParams, settings.capitalMad, settings.scenarios])

  // Tranche is user-chosen (settings.tranche) - no auto-selection.
  const institMinMad = institutionalMinShares * offerPrice
  const hasCapital = settings.capitalMad > 0
  const primaryTranche = settings.tranche

  const primaryBaseParams = primaryTranche === "retail" ? retailBaseParams : institBaseParams
  const primaryOptimizer = primaryTranche === "retail" ? retailOptimizer : institOptimizer
  const primaryLabel = primaryTranche === "retail" ? "Type II retail" : "Type I institutionnel"

  const otherTranche = primaryTranche === "retail" ? "institutional" : "retail"
  const otherOptimizer = otherTranche === "retail" ? retailOptimizer : institOptimizer
  const otherLabel = otherTranche === "retail" ? "Type II" : "Type I"
  const selectedIneligible = primaryOptimizer.reason === "below_institutional_minimum"

  const expectedAtRecommendation = useMemo(
    () => combinedExpectedEconomics(primaryOptimizer.recommendedMad, primaryBaseParams, settings.scenarios),
    [primaryBaseParams, primaryOptimizer.recommendedMad, settings.scenarios],
  )

  const retailMarginal = useMemo(() => {
    const atQ = combinedExpectedEconomics(retailOptimizer.recommendedMad, retailBaseParams, settings.scenarios)
    const plus100Mad = retailOptimizer.recommendedMad + 100 * offerPrice
    const atQPlus100 = combinedExpectedEconomics(plus100Mad, retailBaseParams, settings.scenarios)
    return atQPlus100.expectedProfitMad - atQ.expectedProfitMad
  }, [offerPrice, retailBaseParams, retailOptimizer.recommendedMad, settings.scenarios])

  const scenarioMatrix = useMemo(
    () =>
      settings.scenarios.map((scenario) => ({
        scenario,
        cells: (["bear", "base", "bull"] as const).map((popKey) => {
          const pop = popOf(scenario, popKey)
          const singleScenario: IpoJointScenario = { ...scenario, probability: 1, pops: [{ ...pop, probability: 1 }] }
          const combined = combinedExpectedEconomics(primaryOptimizer.recommendedMad, primaryBaseParams, [singleScenario])
          return { key: `${scenario.key}-${popKey}`, popKey, profitMad: combined.expectedProfitMad, annualizedReturn: combined.expectedAnnualizedReturn }
        }),
      })),
    [primaryBaseParams, primaryOptimizer.recommendedMad, settings.scenarios],
  )

  const qGrid = useMemo(() => sampleGrid(primaryOptimizer.grid), [primaryOptimizer.grid])
  const decision = verdictFor(primaryOptimizer)
  const perCapitaHint = useMemo(() => perCapitaHintShares(settings, retailTrancheShares), [settings, retailTrancheShares])

  const crossHintLine =
    otherTranche === "institutional" && otherOptimizer.reason === "below_institutional_minimum"
      ? `En ${otherLabel}, capital insuffisant (minimum ≈ ${fmtMoney(institMinMad, 0)} MAD).`
      : `En ${otherLabel}, même capital : profit espéré ≈ ${fmtMoney(otherOptimizer.expectedProfitMad, 0)} MAD (${
          otherTranche === "institutional" ? "allocation pro-rata sans couverture bloquée" : "allocation par tête, couverture 100% bloquée"
        }).`

  const normalizedScenarios = useMemo(() => normalizeJointScenarios(settings.scenarios), [settings.scenarios])
  const mixturePop = useMemo(() => expectedMixturePop(settings.scenarios), [settings.scenarios])
  const popRange = useMemo(() => {
    const pops = settings.scenarios.flatMap((s) => s.pops.map((p) => p.pop))
    return pops.length ? { min: Math.min(...pops), max: Math.max(...pops) } : { min: 0, max: 0 }
  }, [settings.scenarios])

  function updateScenario(index: number, patch: Partial<IpoJointScenario>) {
    onChange({ ...settings, scenarios: settings.scenarios.map((scenario, currentIndex) => (currentIndex === index ? { ...scenario, ...patch } : scenario)) })
  }
  function updateScenarioPop(index: number, popKey: "bear" | "base" | "bull", patch: Partial<IpoPopScenario>) {
    onChange({
      ...settings,
      scenarios: settings.scenarios.map((scenario, currentIndex) =>
        currentIndex === index ? { ...scenario, pops: scenario.pops.map((pop) => (pop.key === popKey ? { ...pop, ...patch } : pop)) } : scenario,
      ),
    })
  }

  const whyLine =
    primaryTranche === "retail"
      ? `au-delà du plafond par tête (~${fmtNumber(perCapitaHint, 0)} actions), demander plus ne rapporte rien et bloque du capital`
      : "allocation proportionnelle ≈ 1/sursouscription, profit ≈ +0,5% du montant souscrit par opération, sans couverture bloquée"

  return (
    <Collapsible id="ipo-subscription" open={open} onOpenChange={setOpen} className="fund-card border-primary/30">
      <div className="fund-card-hdr p-0">
        <CollapsibleTrigger className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left outline-none focus-visible:ring-1 focus-visible:ring-ring">
          <span className="flex min-w-0 items-center gap-2"><Calculator className="h-4 w-4 shrink-0 text-primary" /><span><span className="fund-card-title block">Souscription IPO</span><span className="block text-[10px] font-normal text-muted-foreground">Allocation attendue, coût du capital et plafond Kelly - Type I &amp; Type II</span></span></span>
          <span className="flex shrink-0 items-center gap-3">
            <span className="hidden text-right sm:block">
              {hasCapital ? (
                <span className={cn("block text-xs font-semibold", decision.tone)}>
                  {primaryOptimizer.shouldSubscribe ? `Souscrire ≈ ${fmtMoney(primaryOptimizer.recommendedMad, 0)} MAD` : "Ne pas souscrire"} ({primaryLabel})
                </span>
              ) : (
                <span className="block text-xs font-semibold text-amber-600 dark:text-amber-400">Capital non renseigné</span>
              )}
            </span>
            <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", open && "rotate-180")} />
          </span>
        </CollapsibleTrigger>
      </div>

      <CollapsibleContent>
        <div className="fund-card-body">
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="text-[10px] text-muted-foreground">Capital disponible (MAD)<NumberInput value={settings.capitalMad} onChange={(value) => onChange({ ...settings, capitalMad: Math.max(0, value) })} step={1_000} /></label>
            <label className="text-[10px] text-muted-foreground">Tranche
              <select
                className="h-8 w-full rounded-md border border-line bg-card px-2 text-[11px] outline-none focus-visible:ring-1 focus-visible:ring-ring"
                value={settings.tranche}
                onChange={(event) => onChange({ ...settings, tranche: event.target.value as IpoSubscriptionSettings["tranche"] })}
              >
                <option value="retail">Type II — Retail</option>
                <option value="institutional">Type I — Institutionnel</option>
              </select>
            </label>
            <label className="text-[10px] text-muted-foreground">Coût du capital annuel (%)<NumberInput value={settings.financingRate * 100} onChange={(value) => onChange({ ...settings, financingRate: value / 100 })} step={0.25} /></label>
          </div>

          {!hasCapital ? (
            <div className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/[0.08] px-3 py-2.5 text-xs text-amber-700 dark:text-amber-400">
              Renseignez votre capital disponible pour obtenir une recommandation.
            </div>
          ) : (
            <div className="mt-3 rounded-md border border-primary/30 bg-primary/[0.05] p-3.5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-semibold">
                  {selectedIneligible ? (
                    <>Inéligible — {primaryLabel}</>
                  ) : primaryOptimizer.shouldSubscribe ? (
                    <>Recommandation : souscrire ≈ {fmtMoney(primaryOptimizer.recommendedMad, 0)} MAD ({fmtNumber(primaryOptimizer.recommendedShares, 0)} actions) — {primaryLabel}</>
                  ) : (
                    <>Recommandation : ne pas souscrire — {primaryLabel}</>
                  )}
                </span>
                <span className={cn("text-xs font-semibold", decision.tone)}>{decision.label}</span>
              </div>
              {selectedIneligible ? (
                <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                  Minimum institutionnel ≈ {fmtMoney(institMinMad, 0)} MAD ({fmtNumber(institutionalMinShares, 0)} actions) : capital insuffisant. Passez sur la tranche Type II — Retail ci-dessus.
                </p>
              ) : (
                <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                  Actions allouées attendues ≈ {fmtNumber(expectedAtRecommendation.expectedAllocatedShares, 1)} · profit attendu ≈{" "}
                  <span className={expectedAtRecommendation.expectedProfitMad >= 0 ? "t-pos" : "t-neg"}>{fmtMoney(expectedAtRecommendation.expectedProfitMad, 0)} MAD</span>. Pourquoi&nbsp;: {whyLine}.
                </p>
              )}
              <p className="mt-1.5 text-[10px] text-muted-foreground">{crossHintLine}</p>
            </div>
          )}

          <div className="mt-4 rounded-md border border-line bg-card p-3.5">
            <div className="flex items-center gap-2"><TrendingUp className="h-4 w-4 shrink-0 text-primary" /><span className="text-sm font-semibold">Variation attendue du titre</span></div>
            <p className="mt-1 text-[10px] text-muted-foreground">Scénarios estimés, éditables dans Hypothèses (avancé) — ancrés sur J5 : Bear = pire trajectoire observée, Base = 50% de l&apos;ancre historique, Bull = ancre complète.</p>
            <p className="mt-2 text-sm">
              Pop espéré (pondéré) ≈ <span className={cn("font-mono font-semibold", mixturePop >= 0 ? "t-pos" : "t-neg")}>{fmtPct(mixturePop, 1)}</span>
              <span className="ml-2 text-[11px] font-normal text-muted-foreground">plage {fmtPct(popRange.min, 0)} … {fmtPct(popRange.max, 0)}</span>
            </p>
            <div className="mt-3 overflow-x-auto">
              <table className="claude-table">
                <thead>
                  <tr>
                    <th>Scénario</th>
                    <th className="r">Bear</th>
                    <th className="r">Base</th>
                    <th className="r">Bull</th>
                    <th className="r">Variation espérée</th>
                  </tr>
                </thead>
                <tbody>
                  {normalizedScenarios.map((scenario) => {
                    const variation = scenario.pops.reduce((sum, p) => sum + p.probability * p.pop, 0)
                    return (
                      <tr key={scenario.key}>
                        <td>
                          {scenario.label}
                          <div className="text-[10px] text-muted-foreground">prob. {fmtPct(scenario.probability, 0, false)}</div>
                        </td>
                        {(["bear", "base", "bull"] as const).map((popKey) => {
                          const pop = popOf(scenario, popKey)
                          return (
                            <td key={popKey} className="r font-mono">
                              {fmtPct(pop.pop, 0)}
                              <div className="text-[10px] text-muted-foreground">prob. {fmtPct(pop.probability, 0, false)}</div>
                            </td>
                          )
                        })}
                        <td className={`r font-mono ${variation >= 0 ? "t-pos" : "t-neg"}`}>≈{fmtPct(variation, 1)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div className="mt-4 rounded-md border border-line bg-card p-3.5">
            <span className="text-sm font-semibold">IPO passées à Casablanca (base rates)</span>
            <p className="mt-1 text-[10px] text-muted-foreground">Historique utilisé comme prior pour calibrer les scénarios ci-dessus.</p>
            <div className="mt-3"><BaseRateTable rows={baseRateRows} /></div>
          </div>

          <Accordion type="single" collapsible className="mt-4 rounded-md border border-line bg-card px-3">
            <AccordionItem value="advanced" className="border-none">
              <AccordionTrigger className="py-3 text-xs font-semibold no-underline hover:no-underline">
                <span className="flex items-center gap-2"><CircleHelp className="h-3.5 w-3.5 text-primary" />Hypothèses &amp; diagnostics (avancé)</span>
              </AccordionTrigger>
              <AccordionContent className="pb-3">
                <div className="rounded-md border border-primary/20 bg-primary/[0.04] px-3 py-2.5 text-xs leading-relaxed text-muted-foreground">
                  <span className="font-semibold text-foreground">Le principe :</span> le pop affiché n&apos;est pas le rendement réellement capté. Le modèle estime d&apos;abord votre <GlossaryTerm id="ipo-allocation">allocation</GlossaryTerm> par tranche, pondère des scénarios joints (sursouscription et pop corrélés - winner&apos;s curse), retire le coût du capital bloqué, puis retient le montant qui maximise le profit attendu sans dépasser le <GlossaryTerm id="kelly-fraction">plafond Kelly prudent</GlossaryTerm>.
                </div>

                <p className="mt-3 text-[11px] text-muted-foreground">
                  <GlossaryTerm id="kelly-fraction">Plafond half-Kelly</GlossaryTerm> (tranche recommandée) : <span className="font-mono font-semibold text-foreground">{fmtMoney(primaryOptimizer.kelly.maxAllocatedExposureMad, 0)} MAD</span> d&apos;exposition allouée — {primaryOptimizer.binding ? "contraignant" : "non contraignant"}.
                </p>

                <div className="mt-3 grid gap-3 md:grid-cols-3">
                  <label className="text-[10px] text-muted-foreground">Jours bloqués (dépôt → allocation)<NumberInput value={settings.blockedDays} onChange={(value) => onChange({ ...settings, blockedDays: Math.max(1, value) })} step={1} min={1} /></label>
                  <label className="text-[10px] text-muted-foreground" title="Nombre de séances après la cotation nécessaires pour réaliser le pop et sortir (les 5 premières séances sont plafonnées à ±20%, ensuite ±10% - réglementation AMMC du 23/06/2026).">Séances de sortie<NumberInput value={settings.exitDays} onChange={(value) => onChange({ ...settings, exitDays: Math.max(0, value) })} step={1} min={0} /></label>
                  <label className="text-[10px] text-muted-foreground" title="Part du montant demandé bloquée pendant la souscription (espèces = 100% ; collatéral actions ≈ 20% de coût effectif car valorisé à 80%). Institutionnel qualifié = 0% (prospectus).">Couverture retail (%)<NumberInput value={settings.retailCoverageRate * 100} onChange={(value) => onChange({ ...settings, retailCoverageRate: clamp01(value / 100) })} step={5} min={0} /></label>
                  <label className="text-[10px] text-muted-foreground" title="Investisseurs institutionnels qualifiés : aucune couverture exigée au dépôt (prospectus) - ils paient le montant alloué au règlement.">Couverture institutionnel (%)<NumberInput value={settings.institCoverageRate * 100} onChange={(value) => onChange({ ...settings, institCoverageRate: clamp01(value / 100) })} step={5} min={0} /></label>
                </div>
                <p className="mt-1.5 text-[10px] text-muted-foreground">Couverture bloquée (espèces=100%, collatéral actions≈20% de coût effectif car valorisé à 80% de sa valeur) ; institutionnel qualifié = 0% (aucune couverture au dépôt, prospectus p.15-16, p.53).</p>
                <p className="mt-2 text-xs text-muted-foreground"><TrendingUp className="mr-1 inline h-3.5 w-3.5" />Rendement pondéré par l&apos;allocation ≠ pop affiché : c&apos;est l&apos;effet winner&apos;s curse.</p>

                <div className="mt-4 grid gap-3 md:grid-cols-3">
                  <StatTile label="Montant demandé (reco.)" value={`${fmtMoney(primaryOptimizer.recommendedMad, 0)} MAD`} /><StatTile label="Actions demandées" value={fmtNumber(primaryOptimizer.recommendedShares, 0)} /><StatTile label="Satisfaction (esp.)" value={fmtPct(expectedAtRecommendation.expectedSatisfactionRate, 2, false)} />
                </div>
                <p className="mt-2 text-[10px] text-muted-foreground">Le montant recommandé est la demande brute déposée, pas le montant finalement investi. Seules les actions allouées sont achetées ; le solde non servi est restitué après l&apos;allocation.</p>

                <Accordion type="multiple" className="mt-4 space-y-2">
                  <AccordionItem value="assumptions" className="rounded-md border border-line px-3"><AccordionTrigger className="py-3 text-xs font-semibold no-underline hover:no-underline"><span className="flex items-center gap-2"><ShieldCheck className="h-3.5 w-3.5 text-primary" />Scénarios joints (ESTIMATIONS éditables — calibrées sur les IPO 2021-2025, aucun de ces chiffres n&apos;est connu d&apos;avance)</span></AccordionTrigger><AccordionContent className="pb-3">
                    <ScenarioInputs settings={settings} updateScenario={updateScenario} updateScenarioPop={updateScenarioPop} />
                  </AccordionContent></AccordionItem>
                  <AccordionItem value="diagnostics" className="rounded-md border border-line px-3"><AccordionTrigger className="py-3 text-xs font-semibold no-underline hover:no-underline">Diagnostic du montant recommandé (tranche recommandée)</AccordionTrigger><AccordionContent className="pb-3"><DiagnosticTables qGrid={qGrid} scenarioMatrix={scenarioMatrix} financingRate={settings.financingRate} /></AccordionContent></AccordionItem>
                  <AccordionItem value="methodology" className="rounded-md border border-line px-3"><AccordionTrigger className="py-3 text-xs font-semibold no-underline hover:no-underline"><span className="flex items-center gap-2"><CircleHelp className="h-3.5 w-3.5 text-primary" />Comment la taille est-elle choisie ?</span></AccordionTrigger><AccordionContent className="pb-3"><div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                    <MethodStep title="1 · Allocation">Type II (retail) : itération d&apos;1 action / souscripteur jusqu&apos;à 100 max. Les petites demandes sont servies en totalité jusqu&apos;au plafond par tête (tranche / N) si ce premier tour ne peut pas se terminer ; sinon un 2e tour distribue le reliquat au prorata de la demande excédentaire. Type I (institutionnel) : prorata pur (1 / <GlossaryTerm id="ipo-oversubscription">sursouscription</GlossaryTerm>).</MethodStep>
                    <MethodStep title="2 · Scénarios joints">Chaque scénario (faible / moyenne / frénésie) fixe ensemble la sursouscription des deux tranches ET la distribution de pop conditionnelle : corrélation winner&apos;s curse - plus la demande est forte, plus le pop attendu est élevé, mais moins vous êtes servi.</MethodStep>
                    <MethodStep title="3 · Coût réel">Retail : le montant demandé est <GlossaryTerm id="ipo-blocked-capital">bloqué à 100%</GlossaryTerm> (cash ou collatéral) du dépôt jusqu&apos;à l&apos;allocation, même sur les actions non allouées. Institutionnel : aucune couverture au dépôt (prospectus) - seul le montant réellement alloué est financé, du règlement à la sortie.</MethodStep>
                    <MethodStep title="4 · Taille prudente">Le moteur balaie les montants possibles par tranche et retient le meilleur profit attendu sous le plafond half-Kelly (recherche étendue jusqu&apos;à 5x l&apos;exposition). Décision = profit net attendu &gt; 0 (le coût de financement est déjà déduit).</MethodStep>
                    <MethodStep title="5 · Limites de séance">Depuis le 23/06/2026 (AMMC), les 5 premières séances sont limitées à ±20% (ensuite ±10%). Vicenne et SGTM ont été réservées à la hausse (+10%, ancien régime) dès la 1ère séance : un pop supérieur au seuil se réalise sur plusieurs séances, d&apos;où le paramètre &laquo;&nbsp;séances de sortie&nbsp;&raquo;.</MethodStep>
                    <MethodStep title="6 · Références académiques">Rock (1986) : winner&apos;s curse. Keloharju (1993) : rendements pondérés par l&apos;allocation souvent négatifs. Agarwal-Liu-Rhee (2008) : sursouscription corrélée au rendement initial mais sous-performance long terme des IPO &laquo;&nbsp;chaudes&nbsp;&raquo; - d&apos;où : vendre dans le pop, pas de conservation par défaut.</MethodStep>
                  </div><div className="mt-2 rounded bg-muted/50 px-2.5 py-2 font-mono text-[10px] text-muted-foreground">coût de financement = couverture × souscription × taux annuel × jours bloqués/360 + actions allouées × prix IPO × taux annuel × séances de sortie/360</div></AccordionContent></AccordionItem>
                </Accordion>
                <p className="mt-1.5 text-[10px] text-muted-foreground">Valeurs espérées sous scénarios estimés — seuls les mécanismes d&apos;allocation, tranches, plafonds et dates sont des faits du prospectus.</p>
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

function buildRetailJustification(optimizer: IpoOptimalSubscription, baseParams: IpoBaseParams, settings: IpoSubscriptionSettings, marginalProfit: number): string {
  if (optimizer.reason === "kelly_cap_zero" || optimizer.recommendedShares <= 0) {
    return "Le profit attendu pondéré sur les scénarios joints ne couvre pas le coût de blocage du capital : aucune souscription n'est recommandée sur cette tranche."
  }
  const perCapitaHint = perCapitaHintShares(settings, baseParams.trancheShares)
  const financingPct = fmtPct(settings.financingRate, 1, false)
  return `Au-delà d'environ ${fmtNumber(perCapitaHint, 0)} actions (moyenne pondérée des scénarios), chaque action supplémentaire n'ajoute quasiment aucune allocation dans les scénarios où le premier tour ne se termine pas, mais continue de bloquer du capital (${financingPct} × ${settings.blockedDays}j). Le montant optimal est donc proche du plafond par tête, pas du capital disponible. Marginal +100 actions au Q recommandé : ${fmtMoney(marginalProfit, 0)} MAD.`
}

function buildInstitutionalJustification(optimizer: IpoOptimalSubscription, settings: IpoSubscriptionSettings): string {
  if (optimizer.reason === "below_institutional_minimum") {
    return "Capital disponible insuffisant pour le minimum institutionnel (13 452 actions, ≈ 3,0 MMAD) : cette tranche n'est pas accessible avec le capital renseigné."
  }
  return `Les investisseurs qualifiés ne déposent aucune couverture à la souscription (prospectus) : seul le montant ALLOUÉ est financé, du règlement (31/07) à la sortie (${settings.exitDays}j) — coût quasi nul comparé au retail. L'allocation est strictement proportionnelle (1 / sursouscription) : le profit attendu (≈ Σ p·pop / sursouscription par action, avec presque aucun frottement) croît linéairement avec le montant jusqu'au plafond réglementaire de 493 273 actions ou au plafond Kelly (${optimizer.binding ? "actuellement contraignant" : "non contraignant ici"}). Les contraintes pratiques restent le minimum de 3 MMAD, le plafond de 493 273 actions et l'appétit au risque (Kelly).`
}

function TrancheBlock({
  title,
  optimizer,
  financingRate,
  justification,
  marginal,
  showMarginal,
}: {
  title: string
  optimizer: IpoOptimalSubscription
  financingRate: number
  justification: string
  marginal?: number
  showMarginal?: boolean
}) {
  const decision = verdictFor(optimizer)
  return (
    <div className="rounded-md border border-line p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold">{title}</span>
        <span className={cn("text-xs font-semibold", decision.tone)}>{decision.label}</span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
        <StatTile label="Montant demandé" value={`${fmtMoney(optimizer.recommendedMad, 0)} MAD`} />
        <StatTile label="Actions demandées" value={fmtNumber(optimizer.recommendedShares, 0)} />
        <StatTile label="Actions allouées (esp.)" value={fmtNumber(optimizer.expectedAllocatedShares, 1)} />
        <StatTile label="Satisfaction (esp.)" value={fmtPct(optimizer.expectedSatisfactionRate, 2, false)} />
        <StatTile label="Profit attendu" value={`≈ ${fmtMoney(optimizer.expectedProfitMad, 0)} MAD`} tone={optimizer.expectedProfitMad >= 0 ? "text-emerald-600" : "text-red-600"} />
        <StatTile label="Rdt annualisé" value={`≈ ${fmtPct(optimizer.expectedAnnualizedReturn, 1, false)}`} tone={optimizer.expectedAnnualizedReturn >= financingRate ? "text-emerald-600" : "text-red-600"} />
      </div>
      {showMarginal && marginal != null ? (
        <p className="mt-2 text-[10px] text-muted-foreground">Marginal +100 actions au Q recommandé : <span className={cn("font-mono font-semibold", marginal >= 0 ? "t-pos" : "t-neg")}>{fmtMoney(marginal, 0)} MAD</span></p>
      ) : null}
      <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">{justification}</p>
    </div>
  )
}

function MethodStep({ title, children }: { title: string; children: ReactNode }) { return <div className="rounded-md border border-line p-2.5"><span className="text-[10px] font-semibold text-primary">{title}</span><p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{children}</p></div> }

function ScenarioInputs({
  settings,
  updateScenario,
  updateScenarioPop,
}: {
  settings: IpoSubscriptionSettings
  updateScenario: (index: number, patch: Partial<IpoJointScenario>) => void
  updateScenarioPop: (index: number, popKey: "bear" | "base" | "bull", patch: Partial<IpoPopScenario>) => void
}) {
  return (
    <div className="overflow-x-auto">
      <div className="valuation-mini-title mb-1">Scénarios joints (sursouscription, N, pops conditionnels)</div>
      <table className="claude-table">
        <thead>
          <tr>
            <th>Scénario</th>
            <th className="r">Prob.</th>
            <th className="r">Oversub I</th>
            <th className="r">Oversub II</th>
            <th className="r">N retail</th>
            <th className="r">Bear pop</th>
            <th className="r">Bear prob</th>
            <th className="r">Base pop</th>
            <th className="r">Base prob</th>
            <th className="r">Bull pop</th>
            <th className="r">Bull prob</th>
          </tr>
        </thead>
        <tbody>
          {settings.scenarios.map((scenario, index) => (
            <tr key={scenario.key}>
              <td>{scenario.label}</td>
              <td className="r"><NumberInput value={scenario.probability * 100} onChange={(value) => updateScenario(index, { probability: Math.max(0, value) / 100 })} min={0} /></td>
              <td className="r"><NumberInput value={scenario.oversubInstit} onChange={(value) => updateScenario(index, { oversubInstit: Math.max(1, value) })} min={1} /></td>
              <td className="r"><NumberInput value={scenario.oversubRetail} onChange={(value) => updateScenario(index, { oversubRetail: Math.max(1, value) })} min={1} /></td>
              <td className="r"><NumberInput value={scenario.retailSubscribers} onChange={(value) => updateScenario(index, { retailSubscribers: Math.max(1, value) })} step={1_000} min={1} /></td>
              <td className="r"><NumberInput value={popOf(scenario, "bear").pop * 100} onChange={(value) => updateScenarioPop(index, "bear", { pop: value / 100 })} /></td>
              <td className="r"><NumberInput value={popOf(scenario, "bear").probability * 100} onChange={(value) => updateScenarioPop(index, "bear", { probability: Math.max(0, value) / 100 })} min={0} /></td>
              <td className="r"><NumberInput value={popOf(scenario, "base").pop * 100} onChange={(value) => updateScenarioPop(index, "base", { pop: value / 100 })} /></td>
              <td className="r"><NumberInput value={popOf(scenario, "base").probability * 100} onChange={(value) => updateScenarioPop(index, "base", { probability: Math.max(0, value) / 100 })} min={0} /></td>
              <td className="r"><NumberInput value={popOf(scenario, "bull").pop * 100} onChange={(value) => updateScenarioPop(index, "bull", { pop: value / 100 })} /></td>
              <td className="r"><NumberInput value={popOf(scenario, "bull").probability * 100} onChange={(value) => updateScenarioPop(index, "bull", { probability: Math.max(0, value) / 100 })} min={0} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DiagnosticTables({
  qGrid,
  scenarioMatrix,
  financingRate,
}: {
  qGrid: IpoOptimalPoint[]
  scenarioMatrix: { scenario: IpoJointScenario; cells: { key: string; popKey: string; profitMad: number; annualizedReturn: number }[] }[]
  financingRate: number
}) {
  return (
    <>
      <div className="overflow-x-auto">
        <div className="valuation-mini-title mb-1">Q-grid (profit attendu)</div>
        <table className="claude-table"><thead><tr><th className="r">Souscription MAD</th><th className="r">Actions</th><th className="r">Allocation esp.</th><th className="r">Satisfaction</th><th className="r">Profit esp.</th><th className="r">Rdt annualisé</th></tr></thead><tbody>{qGrid.map((row) => <tr key={row.requestedMad}><td className="r font-mono">{fmtMoney(row.requestedMad, 0)}</td><td className="r font-mono">{fmtNumber(row.requestedShares, 0)}</td><td className="r font-mono">{fmtNumber(row.allocatedShares, 1)}</td><td className="r font-mono">{fmtPct(row.satisfactionRate, 2, false)}</td><td className={`r font-mono ${row.expectedProfitMad >= 0 ? "t-pos" : "t-neg"}`}>{fmtMoney(row.expectedProfitMad, 0)}</td><td className={`r font-mono ${row.expectedAnnualizedReturn >= financingRate ? "t-pos" : "t-neg"}`}>{fmtPct(row.expectedAnnualizedReturn, 1, false)}</td></tr>)}</tbody></table>
      </div>
      <div className="mt-4 overflow-x-auto">
        <div className="valuation-mini-title mb-1">Matrice économie au Q recommandé (scénarios joints × pop conditionnel)</div>
        <table className="claude-table"><thead><tr><th>Scénario</th><th className="r">Bear</th><th className="r">Base</th><th className="r">Bull</th></tr></thead><tbody>{scenarioMatrix.map((row) => <tr key={row.scenario.key}><td>{row.scenario.label}</td>{row.cells.map((cell) => <td key={cell.key} className={`r font-mono ${cell.profitMad >= 0 ? "t-pos" : "t-neg"}`}>{fmtMoney(cell.profitMad, 0)}<div className="text-[10px] text-muted-foreground">{fmtPct(cell.annualizedReturn, 0, false)}</div></td>)}</tr>)}</tbody></table>
      </div>
    </>
  )
}

function BaseRateTable({ rows }: { rows: IpoBaseRateRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="claude-table">
        <thead>
          <tr>
            <th>IPO</th>
            <th className="r">Année</th>
            <th className="r">Oversub</th>
            <th className="r">Satisfaction</th>
            <th className="r">J1</th>
            <th className="r">J5</th>
            <th className="r">J10</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.ipo}-${row.year}`}>
              <td title={row.note}>
                {row.ipo}
                {row.estimated ? <span className="ml-1 rounded bg-amber-500/15 px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400">est.</span> : null}
              </td>
              <td className="r">{row.year}</td>
              <td className="r font-mono">{row.oversubscription}</td>
              <td className="r font-mono">{row.satisfaction}</td>
              <td className="r font-mono" title={row.performanceNote}>{formatIpoReturn(row.j1Return)}{row.j1Reserved ? "*" : ""}</td>
              <td className="r font-mono" title={row.performanceNote}>{formatIpoReturn(row.j5Return)}</td>
              <td className="r font-mono" title={row.performanceNote}>{formatIpoReturn(row.j10Return)}</td>
              <td className="text-[10px] text-muted-foreground">{row.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1.5 text-[10px] text-muted-foreground">J1/J5/J10 = performance cumulée vs prix d&apos;offre après 1, 5 et 10 séances dans l&apos;historique OHLC de l&apos;app ; * = cours réservé, pas nécessairement exécutable. n.d. = non disponible ; &laquo;&nbsp;dérivé&nbsp;&raquo; = calculé comme 1/sursouscription.</p>
    </div>
  )
}

function formatIpoReturn(value: number | null): string {
  return value == null ? "n.d." : fmtPct(value, 1)
}
