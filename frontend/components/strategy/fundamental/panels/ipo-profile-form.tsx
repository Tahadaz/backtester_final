"use client"

import { useState } from "react"
import { FundCard } from "../shared/cards"
import { buildQuickStartInputs } from "../lib/ipo-model"
import { newCustomIpoId, type IpoProfile } from "../lib/ipo-store"

const inputClass =
  "h-8 w-full rounded-md border border-line bg-card px-2 text-[11px] font-mono outline-none focus-visible:ring-1 focus-visible:ring-ring"
const labelClass = "flex flex-col gap-1 text-[10px] text-muted-foreground"

const currentYear = new Date().getFullYear()

export function IpoProfileForm({ onSubmit, onCancel }: { onSubmit: (profile: IpoProfile) => void; onCancel: () => void }) {
  const [name, setName] = useState("")
  const [ticker, setTicker] = useState("")
  const [sector, setSector] = useState("")
  const [offerPrice, setOfferPrice] = useState("100")
  const [firstQuote, setFirstQuote] = useState("n.d.")
  const [lastActualYear, setLastActualYear] = useState(String(currentYear - 1))
  const [revenueBase, setRevenueBase] = useState("")
  const [flatRevenueGrowth, setFlatRevenueGrowth] = useState("15")
  const [flatEbeMargin, setFlatEbeMargin] = useState("20")
  const [flatTaxPctRev, setFlatTaxPctRev] = useState("5")
  const [flatBfrPctRev, setFlatBfrPctRev] = useState("3")
  const [flatCapexPctRev, setFlatCapexPctRev] = useState("3")
  const [wacc, setWacc] = useState("11")
  const [terminalGrowth, setTerminalGrowth] = useState("2.5")
  const [netDebt, setNetDebt] = useState("0")
  const [shares, setShares] = useState("")
  const [error, setError] = useState<string | null>(null)

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)

    if (!name.trim()) return setError("Le nom de la société est requis.")
    if (!ticker.trim()) return setError("Le ticker est requis.")

    const offerPriceNum = Number(offerPrice)
    const lastActualYearNum = Number(lastActualYear)
    const revenueBaseNum = Number(revenueBase)
    const sharesNum = Number(shares)
    const waccNum = Number(wacc)
    const terminalGrowthNum = Number(terminalGrowth)
    const netDebtNum = Number(netDebt)
    const flatRevenueGrowthNum = Number(flatRevenueGrowth)
    const flatEbeMarginNum = Number(flatEbeMargin)
    const flatTaxPctRevNum = Number(flatTaxPctRev)
    const flatBfrPctRevNum = Number(flatBfrPctRev)
    const flatCapexPctRevNum = Number(flatCapexPctRev)

    if (!Number.isFinite(offerPriceNum) || offerPriceNum <= 0) return setError("Le prix d'offre doit être un nombre positif.")
    if (!Number.isFinite(lastActualYearNum)) return setError("L'exercice de référence doit être une année valide.")
    if (!Number.isFinite(revenueBaseNum) || revenueBaseNum <= 0) return setError("Le CA de l'exercice de référence doit être un nombre positif.")
    if (!Number.isFinite(sharesNum) || sharesNum <= 0) return setError("Le nombre d'actions doit être un nombre positif.")
    if (!Number.isFinite(waccNum)) return setError("Le WACC doit être un nombre.")
    if (!Number.isFinite(terminalGrowthNum)) return setError("La croissance terminale doit être un nombre.")
    if (!Number.isFinite(netDebtNum)) return setError("La dette nette doit être un nombre.")

    const meta: IpoProfile["meta"] = {
      id: newCustomIpoId(),
      name: name.trim(),
      ticker: ticker.trim().toUpperCase(),
      sector: sector.trim(),
      offerPrice: offerPriceNum,
      firstQuote: firstQuote.trim() || "n.d.",
      isBuiltin: false,
      lastActualYear: lastActualYearNum,
      lastActualRevenue: revenueBaseNum,
      lastActualEbe: null,
      lastActualFcff: null,
      priorActualYears: [],
      hasProspectusContext: false,
      createdAt: new Date().toISOString(),
    }

    const inputs = buildQuickStartInputs({
      lastActualYear: lastActualYearNum,
      revenueBase: revenueBaseNum,
      flatRevenueGrowth: flatRevenueGrowthNum / 100,
      flatEbeMargin: flatEbeMarginNum / 100,
      flatTaxPctRev: flatTaxPctRevNum / 100,
      flatBfrPctRev: flatBfrPctRevNum / 100,
      flatCapexPctRev: flatCapexPctRevNum / 100,
      wacc: waccNum / 100,
      terminalGrowth: terminalGrowthNum / 100,
      netDebt: netDebtNum,
      shares: sharesNum,
      offerPrice: offerPriceNum,
    })

    onSubmit({ meta, inputs })
  }

  return (
    <FundCard title="Ajouter une IPO" aside="profil personnalisé - persisté localement">
      <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className={labelClass}>
            <span>Nom de la société</span>
            <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex: Ma Societe SA" />
          </label>
          <label className={labelClass}>
            <span>Ticker</span>
            <input
              className={inputClass}
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              onBlur={() => setTicker((t) => t.toUpperCase())}
              placeholder="Ex: MST"
            />
          </label>
          <label className={labelClass}>
            <span>Secteur</span>
            <input className={inputClass} value={sector} onChange={(e) => setSector(e.target.value)} placeholder="Optionnel" />
          </label>
          <label className={labelClass}>
            <span>Prix d&apos;offre indicatif (MAD/action)</span>
            <input className={inputClass} type="number" step="0.1" value={offerPrice} onChange={(e) => setOfferPrice(e.target.value)} />
          </label>
          <label className={labelClass}>
            <span>Première cotation</span>
            <input className={inputClass} value={firstQuote} onChange={(e) => setFirstQuote(e.target.value)} placeholder="Ex: T4 2026" />
          </label>
          <label className={labelClass}>
            <span>Dernier exercice réel (année)</span>
            <input className={inputClass} type="number" step="1" value={lastActualYear} onChange={(e) => setLastActualYear(e.target.value)} />
          </label>
          <label className={labelClass}>
            <span>CA de l&apos;exercice de référence (MMAD)</span>
            <input className={inputClass} type="number" step="1" value={revenueBase} onChange={(e) => setRevenueBase(e.target.value)} />
          </label>
          <label className={labelClass}>
            <span>Croissance CA prévisionnelle (%)</span>
            <input className={inputClass} type="number" step="0.5" value={flatRevenueGrowth} onChange={(e) => setFlatRevenueGrowth(e.target.value)} />
          </label>
          <label className={labelClass}>
            <span>Marge d&apos;EBE prévisionnelle (%)</span>
            <input className={inputClass} type="number" step="0.5" value={flatEbeMargin} onChange={(e) => setFlatEbeMargin(e.target.value)} />
          </label>
          <label className={labelClass}>
            <span>WACC (%)</span>
            <input className={inputClass} type="number" step="0.1" value={wacc} onChange={(e) => setWacc(e.target.value)} />
          </label>
          <label className={labelClass}>
            <span>Croissance terminale g (%)</span>
            <input className={inputClass} type="number" step="0.1" value={terminalGrowth} onChange={(e) => setTerminalGrowth(e.target.value)} />
          </label>
          <label className={labelClass}>
            <span>Dette nette (MMAD)</span>
            <input className={inputClass} type="number" step="1" value={netDebt} onChange={(e) => setNetDebt(e.target.value)} />
          </label>
          <label className={labelClass}>
            <span>Actions en circulation (M)</span>
            <input className={inputClass} type="number" step="0.1" value={shares} onChange={(e) => setShares(e.target.value)} />
          </label>
        </div>

        <details className="mt-1">
          <summary className="cursor-pointer text-xs font-semibold text-muted-foreground hover:text-foreground">Hypotheses avancees</summary>
          <div className="mt-2 grid gap-3 sm:grid-cols-3">
            <label className={labelClass}>
              <span>Impôt (% CA)</span>
              <input className={inputClass} type="number" step="0.5" value={flatTaxPctRev} onChange={(e) => setFlatTaxPctRev(e.target.value)} />
            </label>
            <label className={labelClass}>
              <span>ΔBFR (% CA)</span>
              <input className={inputClass} type="number" step="0.5" value={flatBfrPctRev} onChange={(e) => setFlatBfrPctRev(e.target.value)} />
            </label>
            <label className={labelClass}>
              <span>Capex (% CA)</span>
              <input className={inputClass} type="number" step="0.5" value={flatCapexPctRev} onChange={(e) => setFlatCapexPctRev(e.target.value)} />
            </label>
          </div>
        </details>

        {error ? <p className="rounded-md bg-red-500/10 px-2.5 py-1.5 text-[11px] text-red-600 dark:text-red-400">{error}</p> : null}

        <div className="flex gap-2">
          <button type="submit" className="rounded-md border border-primary/40 bg-primary/10 px-3 py-1.5 text-[11px] font-medium text-primary hover:bg-primary/20">
            Créer le profil
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-line px-3 py-1.5 text-[11px] font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            Annuler
          </button>
        </div>
      </form>
    </FundCard>
  )
}
