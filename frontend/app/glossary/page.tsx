"use client"

import Link from "next/link"
import type { ReactNode } from "react"
import { useMemo, useState } from "react"
import {
  Activity,
  ArrowRight,
  BarChart2,
  BookOpen,
  CheckCircle2,
  Database,
  Gauge,
  GitBranch,
  Hash,
  Languages,
  LayoutDashboard,
  LineChart,
  RefreshCw,
  Search,
  ShieldCheck,
  Target,
  TrendingUp,
  X,
} from "lucide-react"
import {
  glossaryCategories,
  glossaryEntries,
  quickGlossaryLinks,
  type GlossaryCategory,
  type GlossaryEntry,
  type GlossaryLanguage,
} from "@/lib/glossary"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

const languageOptions: Array<{ value: GlossaryLanguage; label: string; full: string }> = [
  { value: "fr", label: "FR", full: "Français" },
  { value: "en", label: "EN", full: "English" },
]

const appGuide = [
  { id: "dashboard", href: "/dashboard", icon: LayoutDashboard },
  { id: "data", href: "/data", icon: Database },
  { id: "signals", href: "/signals", icon: Activity },
  { id: "strategy", href: "/strategy", icon: Target },
  { id: "backtest", href: "/backtest", icon: Gauge },
  { id: "analytics", href: "/analytics", icon: BarChart2 },
]

const scoreBands = [
  {
    range: "+50 à +100",
    fr: "Achat fort",
    en: "Strong buy",
    className: "border-emerald-200 bg-emerald-50 text-emerald-800",
  },
  {
    range: "+15 à +50",
    fr: "Achat",
    en: "Buy",
    className: "border-emerald-100 bg-emerald-50/60 text-emerald-700",
  },
  {
    range: "-15 à +15",
    fr: "Neutre",
    en: "Neutral",
    className: "border-border bg-bg2 text-muted-foreground",
  },
  {
    range: "-50 à -15",
    fr: "Vente",
    en: "Sell",
    className: "border-red-100 bg-red-50/70 text-red-700",
  },
  {
    range: "-100 à -50",
    fr: "Vente forte",
    en: "Strong sell",
    className: "border-red-200 bg-red-50 text-red-800",
  },
]

const categoryTone: Record<string, string> = {
  app: "bg-[oklch(0.94_0.04_260_/_0.50)] text-[oklch(0.30_0.14_260)]",
  scores: "bg-emerald-500/10 text-emerald-700",
  indicators: "bg-sky-500/10 text-sky-700",
  edge: "bg-amber-500/10 text-amber-800",
  analytics: "bg-indigo-500/10 text-indigo-700",
  fundamentals: "bg-teal-500/10 text-teal-700",
  backtest: "bg-rose-500/10 text-rose-700",
  data: "bg-slate-500/10 text-slate-700",
}

const indicatorFamilies = [
  {
    href: "#tendance",
    label: { fr: "Tendance", en: "Trend" },
    example: "EMA, SMA, MACD",
    tone: "border-sky-200 bg-sky-50 text-sky-800",
  },
  {
    href: "#momentum",
    label: { fr: "Momentum", en: "Momentum" },
    example: "RSI, ROC, Stochastic",
    tone: "border-emerald-200 bg-emerald-50 text-emerald-800",
  },
  {
    href: "#oscillation",
    label: { fr: "Oscillation", en: "Oscillation" },
    example: "CCI, Williams %R",
    tone: "border-amber-200 bg-amber-50 text-amber-900",
  },
  {
    href: "#volume",
    label: { fr: "Volume", en: "Volume" },
    example: "OBV, VWAP, MFI",
    tone: "border-indigo-200 bg-indigo-50 text-indigo-800",
  },
]

const edgeGates = [
  {
    href: "#trades",
    value: ">= 30",
    label: { fr: "Trades", en: "Trades" },
    text: { fr: "assez d'observations", en: "enough observations" },
  },
  {
    href: "#mc-pvalue",
    value: "p <= 0.05",
    label: { fr: "Monte Carlo", en: "Monte Carlo" },
    text: { fr: "résultat difficile à obtenir par hasard", en: "hard to get by chance" },
  },
  {
    href: "#label-shuffle",
    value: "shuffle OK",
    label: { fr: "Label shuffle", en: "Label shuffle" },
    text: { fr: "le signal survit au test aléatoire", en: "signal survives randomization" },
  },
  {
    href: "#wilson-lower-bound",
    value: "borne OK",
    label: { fr: "Wilson", en: "Wilson" },
    text: { fr: "hit rate prudent encore utile", en: "conservative hit rate still useful" },
  },
]

const returnMethods = [
  {
    href: "#close-to-close-return",
    code: "C-C",
    from: "Close t",
    to: "Close t+h",
    text: { fr: "clôture vers clôture", en: "close to close" },
  },
  {
    href: "#close-to-open-return",
    code: "C-O",
    from: "Close t",
    to: "Open t+h",
    text: { fr: "clôture vers ouverture", en: "close to open" },
  },
  {
    href: "#open-to-open-return",
    code: "O-O",
    from: "Open t",
    to: "Open t+h",
    text: { fr: "ouverture vers ouverture", en: "open to open" },
  },
  {
    href: "#open-to-close-return",
    code: "O-C",
    from: "Open t",
    to: "Close t+h",
    text: { fr: "ouverture vers clôture", en: "open to close" },
  },
]

const globalScoreParts = [
  {
    href: "#tendance",
    label: { fr: "Tendance", en: "Trend" },
    score: 70,
    weight: "30%",
    contribution: "+21.0",
    tone: "bg-sky-500",
  },
  {
    href: "#momentum",
    label: { fr: "Momentum", en: "Momentum" },
    score: 40,
    weight: "25%",
    contribution: "+10.0",
    tone: "bg-emerald-500",
  },
  {
    href: "#oscillation",
    label: { fr: "Oscillation", en: "Oscillation" },
    score: -10,
    weight: "20%",
    contribution: "-2.0",
    tone: "bg-amber-500",
  },
  {
    href: "#volume",
    label: { fr: "Volume", en: "Volume" },
    score: 30,
    weight: "25%",
    contribution: "+7.5",
    tone: "bg-indigo-500",
  },
]

const edgeCandidateRows = [
  {
    href: "#signal-engine",
    method: "Signal Engine",
    er: "+0.42%",
    trades: "64",
    gates: { fr: "OK", en: "OK" },
    decision: { fr: "Candidat", en: "Candidate" },
    selected: false,
  },
  {
    href: "#wfo",
    method: "WFO",
    er: "+0.61%",
    trades: "41",
    gates: { fr: "OK", en: "OK" },
    decision: { fr: "Choisi", en: "Selected" },
    selected: true,
  },
  {
    href: "#mc-test",
    method: "Fast breakout",
    er: "+1.10%",
    trades: "9",
    gates: { fr: "Échec", en: "Fail" },
    decision: { fr: "Rejeté", en: "Rejected" },
    selected: false,
  },
]

const expectedReturnParts = [
  {
    href: "#hit-rate",
    label: { fr: "P(gain)", en: "P(win)" },
    value: "55%",
    text: { fr: "fréquence des trades gagnants", en: "winning trade frequency" },
  },
  {
    href: "#expectancy",
    label: { fr: "Gain moyen", en: "Avg win" },
    value: "+2.0%",
    text: { fr: "gain quand le signal marche", en: "gain when signal works" },
  },
  {
    href: "#expectancy",
    label: { fr: "Perte moyenne", en: "Avg loss" },
    value: "-1.2%",
    text: { fr: "perte quand le signal échoue", en: "loss when signal fails" },
  },
  {
    href: "#action-er",
    label: { fr: "Coûts", en: "Costs" },
    value: "-0.2%",
    text: { fr: "frais et friction", en: "fees and friction" },
  },
]

function normalizeText(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
}

function textForSearch(entry: GlossaryEntry) {
  return [
    entry.id,
    entry.categoryId,
    entry.title.fr,
    entry.title.en,
    entry.plain.fr,
    entry.plain.en,
    ...(entry.details ?? []).flatMap((detail) => [detail.fr, detail.en]),
    entry.example?.fr ?? "",
    entry.example?.en ?? "",
    entry.formula ?? "",
    ...(entry.aliases ?? []),
    ...(entry.tags ?? []),
  ].join(" ")
}

function linkLabel(href: string) {
  if (href.startsWith("#")) return href
  return href.replace(/^\//, "/")
}

function GlossaryLink({
  href,
  children,
  className,
}: {
  href: string
  children: ReactNode
  className?: string
}) {
  if (href.startsWith("#")) {
    return (
      <a href={href} className={className}>
        {children}
      </a>
    )
  }
  return (
    <Link href={href} className={className}>
      {children}
    </Link>
  )
}

function ScoreScale({ lang }: { lang: GlossaryLanguage }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-card">
      <div className="grid divide-y divide-line md:grid-cols-5 md:divide-x md:divide-y-0">
        {scoreBands.map((band) => (
          <div key={band.range} className={cn("min-h-[92px] border-b-0 p-3", band.className)}>
            <div className="font-mono text-xs font-semibold">{band.range}</div>
            <div className="mt-2 text-sm font-semibold">{band[lang]}</div>
            <div className="mt-1 text-[11px] leading-relaxed opacity-75">
              {lang === "fr" ? "Lecture rapide du signal final." : "Fast read of the final signal."}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function FigureCard({
  id,
  title,
  caption,
  icon: Icon,
  children,
}: {
  id: string
  title: string
  caption: string
  icon: typeof LayoutDashboard
  children: ReactNode
}) {
  return (
    <article id={id} className="scroll-mt-24 rounded-lg border border-line bg-card p-4 shadow-xs">
      <div className="mb-4 flex items-start gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[oklch(0.94_0.04_260_/_0.55)] text-[oklch(0.30_0.14_260)]">
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <a href={`#${id}`} className="text-sm font-semibold tracking-tight hover:underline">
            {title}
          </a>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{caption}</p>
        </div>
      </div>
      {children}
    </article>
  )
}

function GlobalScoreFigure({ lang }: { lang: GlossaryLanguage }) {
  return (
    <div className="space-y-3">
      <div className="grid gap-2">
        {globalScoreParts.map((part) => {
          const offset = 100 + part.score
          const width = Math.abs(part.score)
          const left = part.score >= 0 ? 50 : offset / 2

          return (
            <a key={part.href} href={part.href} className="rounded-lg border border-line bg-bg2 p-3 transition hover:bg-accent">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-semibold">{part.label[lang]}</span>
                <span className="font-mono text-[11px] text-muted-foreground">
                  {part.score > 0 ? "+" : ""}
                  {part.score} x {part.weight} = {part.contribution}
                </span>
              </div>
              <div className="relative mt-3 h-3 rounded-full bg-card">
                <div className="absolute left-1/2 top-0 h-3 w-px bg-border" />
                <div
                  className={cn("absolute top-0 h-3 rounded-full", part.tone)}
                  style={{ left: `${left}%`, width: `${width / 2}%` }}
                />
              </div>
            </a>
          )
        })}
      </div>

      <a
        href="#score-composite"
        className="flex flex-col gap-3 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-emerald-900 transition hover:shadow-sm sm:flex-row sm:items-center sm:justify-between"
      >
        <div>
          <div className="text-sm font-semibold">{lang === "fr" ? "Score global final" : "Final global score"}</div>
          <p className="mt-1 text-xs leading-relaxed opacity-80">
            {lang === "fr"
              ? "Somme des contributions, bornée entre -100 et +100."
              : "Sum of contributions, capped between -100 and +100."}
          </p>
        </div>
        <div className="font-mono text-2xl font-semibold">+36.5</div>
      </a>
    </div>
  )
}

function ScoringMethodologyFigure({ lang }: { lang: GlossaryLanguage }) {
  const steps = [
    {
      href: "#canonical-data",
      label: { fr: "Données marché", en: "Market data" },
      text: { fr: "OHLCV propre et liquide", en: "clean and liquid OHLCV" },
    },
    {
      href: "#familles-indicateurs",
      label: { fr: "Indicateurs", en: "Indicators" },
      text: { fr: "SMA, RSI, MACD, OBV...", en: "SMA, RSI, MACD, OBV..." },
    },
    {
      href: "#score-composite",
      label: { fr: "Score global", en: "Global score" },
      text: { fr: "direction et intensite", en: "direction and intensity" },
    },
    {
      href: "#edge-selection",
      label: { fr: "Validation edge", en: "Edge validation" },
      text: { fr: "preuves statistiques", en: "statistical evidence" },
    },
    {
      href: "#ticket",
      label: { fr: "Décision", en: "Decision" },
      text: { fr: "ticket ou watchlist", en: "ticket or watchlist" },
    },
  ]

  return (
    <div className="grid gap-2 md:grid-cols-5">
      {steps.map((step, index) => (
        <div key={step.href} className="relative">
          <a href={step.href} className="block h-full rounded-lg border border-line bg-bg2 p-3 transition hover:bg-accent">
            <div className="font-mono text-[10px] text-muted-foreground">STEP {index + 1}</div>
            <div className="mt-2 text-sm font-semibold">{step.label[lang]}</div>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{step.text[lang]}</p>
          </a>
          {index < steps.length - 1 ? (
            <ArrowRight className="absolute -right-3 top-1/2 z-10 hidden h-4 w-4 -translate-y-1/2 text-muted-foreground md:block" />
          ) : null}
        </div>
      ))}
    </div>
  )
}

function EdgeSelectionFigure({ lang }: { lang: GlossaryLanguage }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <div className="grid grid-cols-[1.2fr_0.8fr_0.7fr_0.8fr_0.9fr] gap-0 bg-bg2 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        <div>{lang === "fr" ? "Méthode" : "Method"}</div>
        <div>E[R]</div>
        <div>{lang === "fr" ? "Trades" : "Trades"}</div>
        <div>{lang === "fr" ? "Gates" : "Gates"}</div>
        <div>{lang === "fr" ? "Décision" : "Decision"}</div>
      </div>
      {edgeCandidateRows.map((row) => (
        <a
          key={row.method}
          href={row.href}
          className={cn(
            "grid grid-cols-[1.2fr_0.8fr_0.7fr_0.8fr_0.9fr] gap-0 border-t border-line px-3 py-2 text-xs transition hover:bg-accent",
            row.selected ? "bg-emerald-50 text-emerald-900" : "bg-card",
          )}
        >
          <div className="font-semibold">{row.method}</div>
          <div className="font-mono">{row.er}</div>
          <div className="font-mono">{row.trades}</div>
          <div>{row.gates[lang]}</div>
          <div className="font-semibold">{row.decision[lang]}</div>
        </a>
      ))}
      <div className="border-t border-line bg-bg2 px-3 py-2 text-xs leading-relaxed text-muted-foreground">
        {lang === "fr"
          ? "Le plus gros E[R] n'est pas choisi s'il échoue les gates ou manque d'observations."
          : "The largest E[R] is not selected if it fails gates or lacks observations."}
      </div>
    </div>
  )
}

function ExpectedReturnFigure({ lang }: { lang: GlossaryLanguage }) {
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2">
        {expectedReturnParts.map((part) => (
          <a key={part.label.en} href={part.href} className="rounded-lg border border-line bg-bg2 p-3 transition hover:bg-accent">
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm font-semibold">{part.label[lang]}</div>
              <div className="font-mono text-sm">{part.value}</div>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{part.text[lang]}</p>
          </a>
        ))}
      </div>
      <a href="#expected-return" className="block rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-emerald-900 transition hover:shadow-sm">
        <div className="text-sm font-semibold">{lang === "fr" ? "Formule nette" : "Net formula"}</div>
        <div className="mt-2 overflow-x-auto font-mono text-xs">
          E[R] = 0.55 x 2.0% - 0.45 x 1.2% - 0.2% = +0.36%
        </div>
        <p className="mt-2 text-xs leading-relaxed opacity-80">
          {lang === "fr"
            ? "Action E[R] remet ce résultat dans le sens de la position: long ou short."
            : "Action E[R] maps this result to the position side: long or short."}
        </p>
      </a>
    </div>
  )
}

function ScoreEdgeMatrixFigure({ lang }: { lang: GlossaryLanguage }) {
  const cells = [
    {
      href: "#proven-edge",
      title: { fr: "Priorité", en: "Priority" },
      text: { fr: "Score fort et edge robuste", en: "Strong score and robust edge" },
      className: "border-emerald-200 bg-emerald-50 text-emerald-900",
    },
    {
      href: "#edge",
      title: { fr: "À surveiller", en: "Watch" },
      text: { fr: "Score fort, preuve fragile", en: "Strong score, fragile proof" },
      className: "border-amber-200 bg-amber-50 text-amber-900",
    },
    {
      href: "#score-composite",
      title: { fr: "Pas d'urgence", en: "No rush" },
      text: { fr: "Edge present, signal faible", en: "Edge present, weak signal" },
      className: "border-sky-200 bg-sky-50 text-sky-900",
    },
    {
      href: "#signal-badge",
      title: { fr: "Ignorer", en: "Ignore" },
      text: { fr: "Score faible et pas d'edge", en: "Weak score and no edge" },
      className: "border-slate-200 bg-slate-50 text-slate-800",
    },
  ]

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[54px_1fr_1fr] gap-2 text-center text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        <div />
        <div>{lang === "fr" ? "Edge fort" : "Strong edge"}</div>
        <div>{lang === "fr" ? "Edge faible" : "Weak edge"}</div>
      </div>
      <div className="grid grid-cols-[54px_1fr_1fr] gap-2">
        <div className="grid place-items-center rounded-md bg-bg2 px-1 text-center text-[10px] font-semibold text-muted-foreground">
          {lang === "fr" ? "Score fort" : "Strong score"}
        </div>
        {cells.slice(0, 2).map((cell) => (
          <a key={cell.title.en} href={cell.href} className={cn("rounded-lg border p-3 transition hover:shadow-sm", cell.className)}>
            <div className="text-sm font-semibold">{cell.title[lang]}</div>
            <p className="mt-1 text-xs leading-relaxed opacity-80">{cell.text[lang]}</p>
          </a>
        ))}
        <div className="grid place-items-center rounded-md bg-bg2 px-1 text-center text-[10px] font-semibold text-muted-foreground">
          {lang === "fr" ? "Score faible" : "Weak score"}
        </div>
        {cells.slice(2).map((cell) => (
          <a key={cell.title.en} href={cell.href} className={cn("rounded-lg border p-3 transition hover:shadow-sm", cell.className)}>
            <div className="text-sm font-semibold">{cell.title[lang]}</div>
            <p className="mt-1 text-xs leading-relaxed opacity-80">{cell.text[lang]}</p>
          </a>
        ))}
      </div>
    </div>
  )
}

function WorkflowFigure({ lang }: { lang: GlossaryLanguage }) {
  const steps = [
    {
      href: "#canonical-data",
      icon: Database,
      title: { fr: "Données propres", en: "Clean data" },
      text: { fr: "OHLCV, prix, volume, liquidité.", en: "OHLCV, price, volume, liquidity." },
      tone: "border-slate-200 bg-slate-50 text-slate-800",
    },
    {
      href: "#signal-engine",
      icon: Activity,
      title: { fr: "Moteur de signaux", en: "Signal engine" },
      text: { fr: "Calcule indicateurs et régimes.", en: "Computes indicators and regimes." },
      tone: "border-sky-200 bg-sky-50 text-sky-800",
    },
    {
      href: "#score-composite",
      icon: TrendingUp,
      title: { fr: "Score composite", en: "Composite score" },
      text: { fr: "Resume la force directionnelle.", en: "Summarizes directional strength." },
      tone: "border-emerald-200 bg-emerald-50 text-emerald-800",
    },
    {
      href: "#proven-edge",
      icon: ShieldCheck,
      title: { fr: "Edge valide", en: "Validated edge" },
      text: { fr: "Vérifie que le signal a tenu aux tests.", en: "Checks the signal survived tests." },
      tone: "border-amber-200 bg-amber-50 text-amber-900",
    },
    {
      href: "#ticket",
      icon: Target,
      title: { fr: "Ticket", en: "Ticket" },
      text: { fr: "Action, taille, stop, take profit.", en: "Action, size, stop, take profit." },
      tone: "border-indigo-200 bg-indigo-50 text-indigo-800",
    },
  ]

  return (
    <div className="grid gap-2 lg:grid-cols-5">
      {steps.map((step, index) => (
        <div key={step.href} className="relative">
          <a
            href={step.href}
            className={cn(
              "block h-full rounded-lg border p-3 transition hover:-translate-y-0.5 hover:shadow-sm",
              step.tone,
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <step.icon className="h-4 w-4" />
              <span className="font-mono text-[10px]">{String(index + 1).padStart(2, "0")}</span>
            </div>
            <div className="mt-3 text-sm font-semibold">{step.title[lang]}</div>
            <p className="mt-1 min-h-[34px] text-xs leading-relaxed opacity-80">{step.text[lang]}</p>
          </a>
          {index < steps.length - 1 ? (
            <div className="hidden lg:block">
              <ArrowRight className="absolute -right-4 top-1/2 z-10 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            </div>
          ) : null}
        </div>
      ))}
    </div>
  )
}

function IndicatorFamiliesFigure({ lang }: { lang: GlossaryLanguage }) {
  return (
    <div className="grid gap-3 lg:grid-cols-[1fr_170px_1fr] lg:items-center">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
        {indicatorFamilies.slice(0, 2).map((family) => (
          <a key={family.href} href={family.href} className={cn("rounded-lg border p-3 transition hover:shadow-sm", family.tone)}>
            <div className="text-sm font-semibold">{family.label[lang]}</div>
            <div className="mt-1 font-mono text-[11px] opacity-75">{family.example}</div>
          </a>
        ))}
      </div>

      <a
        href="#score-composite"
        className="grid min-h-[150px] place-items-center rounded-lg border border-line bg-bg2 p-4 text-center transition hover:bg-accent"
      >
        <div>
          <div className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-card shadow-xs">
            <BarChart2 className="h-5 w-5 text-[oklch(0.30_0.14_260)]" />
          </div>
          <div className="mt-3 text-sm font-semibold">
            {lang === "fr" ? "Score final" : "Final score"}
          </div>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {lang === "fr" ? "Moyenne pondérée des familles." : "Weighted family average."}
          </p>
        </div>
      </a>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
        {indicatorFamilies.slice(2).map((family) => (
          <a key={family.href} href={family.href} className={cn("rounded-lg border p-3 transition hover:shadow-sm", family.tone)}>
            <div className="text-sm font-semibold">{family.label[lang]}</div>
            <div className="mt-1 font-mono text-[11px] opacity-75">{family.example}</div>
          </a>
        ))}
      </div>
    </div>
  )
}

function WfoTimelineFigure({ lang }: { lang: GlossaryLanguage }) {
  const rows = [
    { label: "W1", trainLeft: "0%", trainWidth: "45%", testLeft: "45%", testWidth: "14%" },
    { label: "W2", trainLeft: "13%", trainWidth: "45%", testLeft: "58%", testWidth: "14%" },
    { label: "W3", trainLeft: "26%", trainWidth: "45%", testLeft: "71%", testWidth: "14%" },
  ]

  return (
    <div className="space-y-3">
      {rows.map((row) => (
        <div key={row.label} className="grid grid-cols-[38px_minmax(0,1fr)] items-center gap-3">
          <div className="font-mono text-xs font-semibold text-muted-foreground">{row.label}</div>
          <div className="relative h-10 rounded-lg border border-line bg-bg2">
            <a
              href="#wfo-window"
              className="absolute top-1 h-8 rounded-md bg-sky-100 px-2 py-1 text-[10px] font-semibold text-sky-800"
              style={{ left: row.trainLeft, width: row.trainWidth }}
            >
              {lang === "fr" ? "Apprendre" : "Train"}
            </a>
            <a
              href="#out-of-sample"
              className="absolute top-1 h-8 rounded-md bg-emerald-100 px-2 py-1 text-[10px] font-semibold text-emerald-800"
              style={{ left: row.testLeft, width: row.testWidth }}
            >
              OOS
            </a>
          </div>
        </div>
      ))}
      <div className="rounded-lg border border-line bg-card p-3 text-xs leading-relaxed text-muted-foreground">
        {lang === "fr"
          ? "Chaque fenêtre apprend sur le passé puis teste sur une période jamais vue. Si les résultats tiennent plusieurs fois, le signal est plus crédible."
          : "Each window learns on the past, then tests on unseen data. Repeated survival makes the signal more credible."}
      </div>
    </div>
  )
}

function EdgeGatesFigure({ lang }: { lang: GlossaryLanguage }) {
  return (
    <div className="grid gap-3 lg:grid-cols-[1fr_150px] lg:items-stretch">
      <div className="grid gap-2 sm:grid-cols-2">
        {edgeGates.map((gate) => (
          <a key={gate.href} href={gate.href} className="rounded-lg border border-line bg-bg2 p-3 transition hover:bg-accent">
            <div className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" />
              <div>
                <div className="text-sm font-semibold">{gate.label[lang]}</div>
                <div className="mt-0.5 font-mono text-[11px] text-foreground">{gate.value}</div>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{gate.text[lang]}</p>
              </div>
            </div>
          </a>
        ))}
      </div>
      <a
        href="#proven-edge"
        className="grid place-items-center rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-center text-emerald-800 transition hover:shadow-sm"
      >
        <div>
          <ShieldCheck className="mx-auto h-6 w-6" />
          <div className="mt-2 text-sm font-semibold">{lang === "fr" ? "Proven Edge" : "Proven Edge"}</div>
          <p className="mt-1 text-xs leading-relaxed opacity-80">
            {lang === "fr" ? "Signal utilisable avec prudence." : "Usable signal with caution."}
          </p>
        </div>
      </a>
    </div>
  )
}

function IcFigure({ lang }: { lang: GlossaryLanguage }) {
  const points = [
    [32, 118],
    [54, 98],
    [78, 105],
    [98, 82],
    [124, 70],
    [148, 62],
    [172, 45],
    [205, 36],
  ]

  return (
    <div className="grid gap-3 md:grid-cols-[1.2fr_0.8fr] md:items-center">
      <a href="#ic" className="rounded-lg border border-line bg-bg2 p-3 transition hover:bg-accent">
        <svg viewBox="0 0 240 150" className="h-[170px] w-full" role="img" aria-label="IC scatter diagram">
          <line x1="24" y1="126" x2="224" y2="126" stroke="currentColor" className="text-muted-foreground/40" />
          <line x1="24" y1="20" x2="24" y2="126" stroke="currentColor" className="text-muted-foreground/40" />
          <path d="M32 116 C70 103, 118 75, 210 34" fill="none" stroke="currentColor" strokeWidth="3" className="text-emerald-600" />
          {points.map(([cx, cy]) => (
            <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="4" fill="currentColor" className="text-[oklch(0.30_0.14_260)]" />
          ))}
          <text x="112" y="145" textAnchor="middle" className="fill-muted-foreground text-[10px]">
            {lang === "fr" ? "rang du signal" : "signal rank"}
          </text>
          <text x="5" y="78" transform="rotate(-90 5 78)" textAnchor="middle" className="fill-muted-foreground text-[10px]">
            {lang === "fr" ? "retour futur" : "future return"}
          </text>
        </svg>
      </a>
      <div className="space-y-2 text-sm">
        <a href="#ic" className="block rounded-lg border border-line bg-card p-3 transition hover:bg-accent">
          <div className="font-semibold">{lang === "fr" ? "IC positif" : "Positive IC"}</div>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {lang === "fr"
              ? "Les meilleurs rangs de signal tendent à avoir de meilleurs retours futurs."
              : "Higher signal ranks tend to map to better future returns."}
          </p>
        </a>
        <a href="#t-stat" className="block rounded-lg border border-line bg-card p-3 transition hover:bg-accent">
          <div className="font-semibold">t-stat</div>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {lang === "fr" ? "Indique si l'IC est stable ou trop fragile." : "Shows whether IC is stable or fragile."}
          </p>
        </a>
      </div>
    </div>
  )
}

function ReturnMethodFigure({ lang }: { lang: GlossaryLanguage }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {returnMethods.map((method) => (
        <a key={method.href} href={method.href} className="rounded-lg border border-line bg-bg2 p-3 transition hover:bg-accent">
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono text-sm font-semibold">{method.code}</span>
            <span className="rounded bg-card px-2 py-0.5 text-[10px] text-muted-foreground">{method.text[lang]}</span>
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs">
            <span className="rounded-md border border-line bg-card px-2 py-1 font-mono">{method.from}</span>
            <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="rounded-md border border-line bg-card px-2 py-1 font-mono">{method.to}</span>
          </div>
        </a>
      ))}
    </div>
  )
}

function BacktestFigure({ lang }: { lang: GlossaryLanguage }) {
  return (
    <div className="grid gap-3 md:grid-cols-[1.15fr_0.85fr] md:items-stretch">
      <a href="#equity-curve" className="rounded-lg border border-line bg-bg2 p-3 transition hover:bg-accent">
        <svg viewBox="0 0 260 150" className="h-[170px] w-full" role="img" aria-label="Equity curve and drawdown diagram">
          <path d="M20 120 L54 110 L82 88 L112 94 L146 68 L178 72 L212 48 L240 36" fill="none" stroke="currentColor" strokeWidth="4" className="text-emerald-600" />
          <path d="M82 88 C98 118, 126 118, 146 68" fill="none" stroke="currentColor" strokeWidth="3" strokeDasharray="5 5" className="text-red-500" />
          <line x1="20" y1="126" x2="240" y2="126" stroke="currentColor" className="text-muted-foreground/40" />
          <text x="128" y="145" textAnchor="middle" className="fill-muted-foreground text-[10px]">
            {lang === "fr" ? "courbe equity" : "equity curve"}
          </text>
          <text x="122" y="113" textAnchor="middle" className="fill-red-600 text-[10px]">
            {lang === "fr" ? "drawdown" : "drawdown"}
          </text>
        </svg>
      </a>
      <div className="grid gap-2">
        {[
          { href: "#cagr", label: "CAGR", text: lang === "fr" ? "vitesse de croissance" : "growth speed" },
          { href: "#sharpe", label: "Sharpe", text: lang === "fr" ? "rendement ajusté du risque" : "risk-adjusted return" },
          { href: "#max-drawdown", label: "Max DD", text: lang === "fr" ? "pire baisse depuis un sommet" : "worst drop from a peak" },
          { href: "#trade-ledger", label: lang === "fr" ? "Trades" : "Trades", text: lang === "fr" ? "détails transaction par transaction" : "transaction-by-transaction detail" },
        ].map((metric) => (
          <a key={metric.href} href={metric.href} className="rounded-lg border border-line bg-card px-3 py-2 transition hover:bg-accent">
            <div className="text-xs font-semibold">{metric.label}</div>
            <div className="mt-0.5 text-[11px] text-muted-foreground">{metric.text}</div>
          </a>
        ))}
      </div>
    </div>
  )
}

function DcfDiscountingFigure({ lang }: { lang: GlossaryLanguage }) {
  const rate = 0.1
  const years = [1, 2, 3, 4, 5]
  const nominalHeight = 92
  const baseline = 132
  const columnWidth = 50
  const barWidth = 30
  const startX = 30

  return (
    <div className="space-y-3">
      <a href="#dcf" className="block rounded-lg border border-line bg-bg2 p-3 transition hover:bg-accent">
        <svg viewBox="0 0 300 170" className="h-[190px] w-full" role="img" aria-label="DCF discounting diagram">
          <line x1="24" y1={baseline} x2="288" y2={baseline} stroke="currentColor" className="text-muted-foreground/40" />
          {years.map((t, index) => {
            const factor = 1 / (1 + rate) ** t
            const pvHeight = nominalHeight * factor
            const x = startX + index * columnWidth
            return (
              <g key={t}>
                <rect x={x} y={baseline - nominalHeight} width={barWidth} height={nominalHeight} rx="3" className="fill-muted-foreground/15" />
                <rect x={x} y={baseline - pvHeight} width={barWidth} height={pvHeight} rx="3" className="fill-teal-500/70" />
                <text x={x + barWidth / 2} y={baseline - pvHeight - 4} textAnchor="middle" className="fill-teal-700 text-[8px] font-semibold">
                  {factor.toFixed(2)}
                </text>
                <text x={x + barWidth / 2} y={baseline + 12} textAnchor="middle" className="fill-muted-foreground text-[9px]">
                  t={t}
                </text>
              </g>
            )
          })}
          <text x="156" y="158" textAnchor="middle" className="fill-muted-foreground text-[9px]">
            {lang === "fr" ? "flux nominal (clair) -> valeur actuelle (foncé)" : "nominal flow (light) -> present value (dark)"}
          </text>
        </svg>
      </a>
      <div className="grid gap-2 sm:grid-cols-3">
        <a href="#discount-period" className="rounded-lg border border-line bg-card p-3 transition hover:bg-accent">
          <div className="text-sm font-semibold">t</div>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {lang === "fr" ? "années avant le flux" : "years until the flow"}
          </p>
        </a>
        <a href="#discount-factor" className="rounded-lg border border-line bg-card p-3 transition hover:bg-accent">
          <div className="text-sm font-semibold">{lang === "fr" ? "Facteur" : "Factor"}</div>
          <p className="mt-1 font-mono text-[11px] text-muted-foreground">1/(1+r)^t</p>
        </a>
        <a href="#present-value" className="rounded-lg border border-line bg-card p-3 transition hover:bg-accent">
          <div className="text-sm font-semibold">PV</div>
          <p className="mt-1 font-mono text-[11px] text-muted-foreground">{lang === "fr" ? "flux x facteur" : "flow x factor"}</p>
        </a>
      </div>
    </div>
  )
}

function ValuationEnsembleFigure({ lang }: { lang: GlossaryLanguage }) {
  const models = [
    { href: "#fcff", label: "DCF FCFF", low: 18, high: 62 },
    { href: "#fcfe", label: "DCF FCFE", low: 24, high: 58 },
    { href: "#ddm", label: "DDM", low: 30, high: 66 },
    { href: "#relative-multiples", label: lang === "fr" ? "Multiples" : "Multiples", low: 22, high: 70 },
  ]
  const target = 45

  return (
    <div className="space-y-3">
      <div className="space-y-2 rounded-lg border border-line bg-bg2 p-3">
        {models.map((model) => (
          <a key={model.href} href={model.href} className="grid grid-cols-[88px_minmax(0,1fr)] items-center gap-3 rounded-md p-1 transition hover:bg-accent">
            <span className="truncate text-xs font-semibold">{model.label}</span>
            <div className="relative h-4 rounded-full bg-card">
              <div
                className="absolute top-0 h-4 rounded-full bg-teal-500/40"
                style={{ left: `${model.low}%`, width: `${model.high - model.low}%` }}
              />
            </div>
          </a>
        ))}
        <div className="relative h-4">
          <div className="absolute top-0 h-4 w-px bg-emerald-600" style={{ left: `${target}%` }} />
          <span className="absolute -top-0.5 text-[10px] font-semibold text-emerald-700" style={{ left: `${target}%`, transform: "translateX(-50%)" }}>
            {lang === "fr" ? "cible" : "target"}
          </span>
        </div>
      </div>
      <a href="#ic-weighting" className="block rounded-lg border border-teal-200 bg-teal-50 p-3 text-teal-900 transition hover:shadow-sm">
        <div className="text-sm font-semibold">{lang === "fr" ? "Pondération: égale ou par IC" : "Weighting: equal or IC-based"}</div>
        <p className="mt-1 text-xs leading-relaxed opacity-80">
          {lang === "fr"
            ? "La cible combine les modèles inclus. En égale chacun compte 1/N; par IC les méthodes les plus prédictives pèsent plus."
            : "The target blends the included models. Equal counts each 1/N; IC gives more weight to the most predictive methods."}
        </p>
      </a>
    </div>
  )
}

function FundamentalsFigures({ lang }: { lang: GlossaryLanguage }) {
  return (
    <section id="figures-fondamental" className="scroll-mt-24 space-y-3">
      <div>
        <h2 className="text-base font-semibold tracking-tight">
          {lang === "fr" ? "Figures - valorisation fondamentale" : "Figures - fundamental valuation"}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {lang === "fr"
            ? "Comment le mode fondamental transforme des flux futurs en une juste valeur, puis combine plusieurs modèles."
            : "How fundamental mode turns future flows into a fair value, then blends several models."}
        </p>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <FigureCard
          id="figure-dcf"
          title={lang === "fr" ? "DCF: actualiser les flux futurs" : "DCF: discounting future flows"}
          caption={
            lang === "fr"
              ? "Chaque flux futur est multiplié par un facteur inférieur à 1: plus il est lointain, moins il vaut aujourd'hui."
              : "Each future flow is multiplied by a factor below 1: the further away, the less it is worth today."
          }
          icon={LineChart}
        >
          <DcfDiscountingFigure lang={lang} />
        </FigureCard>
        <FigureCard
          id="figure-ensemble"
          title={lang === "fr" ? "Combiner les modèles" : "Blending the models"}
          caption={
            lang === "fr"
              ? "La cible finale est une combinaison de plusieurs modèles, pondérés également ou par leur IC."
              : "The final target blends several models, weighted equally or by their IC."
          }
          icon={Target}
        >
          <ValuationEnsembleFigure lang={lang} />
        </FigureCard>
      </div>
    </section>
  )
}

function ExplanationFigures({ lang }: { lang: GlossaryLanguage }) {
  return (
    <section id="figures-explication" className="scroll-mt-24 space-y-3">
      <div>
        <h2 className="text-base font-semibold tracking-tight">
          {lang === "fr" ? "Figures d'explication" : "Explanation figures"}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {lang === "fr"
            ? "Ces diagrammes donnent une lecture visuelle des concepts les plus importants. Chaque bloc est aussi un lien vers la définition précise."
            : "These diagrams give a visual reading of the most important concepts. Each block also links to the exact definition."}
        </p>
      </div>

      <FigureCard
        id="figure-global-score"
        title={lang === "fr" ? "Score global: comment il est construit" : "Global score: how it is built"}
        caption={
          lang === "fr"
            ? "Les familles d'indicateurs contribuent chacune au score final selon leur poids."
            : "Indicator families each contribute to the final score according to their weight."
        }
        icon={Gauge}
      >
        <GlobalScoreFigure lang={lang} />
      </FigureCard>

      <div className="grid gap-4 xl:grid-cols-2">
        <FigureCard
          id="figure-scoring-methodology"
          title={lang === "fr" ? "Méthode de scoring" : "Scoring methodology"}
          caption={
            lang === "fr"
              ? "Le score est une lecture technique; l'edge est la vérification statistique de cette lecture."
              : "The score is a technical read; edge is the statistical check behind that read."
          }
          icon={BarChart2}
        >
          <ScoringMethodologyFigure lang={lang} />
        </FigureCard>

        <FigureCard
          id="figure-score-edge-matrix"
          title={lang === "fr" ? "Score vs edge: comment décider" : "Score vs edge: how to decide"}
          caption={
            lang === "fr"
              ? "Un score fort n'est pas suffisant. L'app préfère les cas où score et edge racontent la même histoire."
              : "A strong score is not enough. The app prefers cases where score and edge tell the same story."
          }
          icon={ShieldCheck}
        >
          <ScoreEdgeMatrixFigure lang={lang} />
        </FigureCard>

        <FigureCard
          id="figure-edge-selection"
          title={lang === "fr" ? "Choix de l'edge" : "Choosing the edge"}
          caption={
            lang === "fr"
              ? "La meilleure méthode auto combine expected return, taille d'échantillon et gates de robustesse."
              : "The best automatic method combines expected return, sample size, and robustness gates."
          }
          icon={Target}
        >
          <EdgeSelectionFigure lang={lang} />
        </FigureCard>

        <FigureCard
          id="figure-expected-return"
          title={lang === "fr" ? "Expected return net" : "Net expected return"}
          caption={
            lang === "fr"
              ? "E[R] explique combien le signal peut rapporter en moyenne après probabilités, pertes et coûts."
              : "E[R] explains how much the signal can return on average after probabilities, losses, and costs."
          }
          icon={TrendingUp}
        >
          <ExpectedReturnFigure lang={lang} />
        </FigureCard>
      </div>

      <FigureCard
        id="figure-workflow"
        title={lang === "fr" ? "Parcours complet: données -> décision" : "Full path: data -> decision"}
        caption={
          lang === "fr"
            ? "La logique de l'app en cinq étapes, depuis les données propres jusqu'au ticket d'exécution."
            : "The app logic in five steps, from clean data to the execution ticket."
        }
        icon={GitBranch}
      >
        <WorkflowFigure lang={lang} />
      </FigureCard>

      <div className="grid gap-4 xl:grid-cols-2">
        <FigureCard
          id="figure-families"
          title={lang === "fr" ? "Familles d'indicateurs" : "Indicator families"}
          caption={
            lang === "fr"
              ? "Les indicateurs ne sont pas lus seuls: ils contribuent à des familles, puis au score final."
              : "Indicators are not read alone: they feed families, then the final score."
          }
          icon={BarChart2}
        >
          <IndicatorFamiliesFigure lang={lang} />
        </FigureCard>

        <FigureCard
          id="figure-wfo"
          title={lang === "fr" ? "Walk-forward optimization" : "Walk-forward optimization"}
          caption={
            lang === "fr"
              ? "On optimise sur une fenêtre passée, puis on teste sur une zone future séparée."
              : "Optimize on a past window, then test on a separate future slice."
          }
          icon={RefreshCw}
        >
          <WfoTimelineFigure lang={lang} />
        </FigureCard>

        <FigureCard
          id="figure-edge-gates"
          title={lang === "fr" ? "Validation d'edge" : "Edge validation"}
          caption={
            lang === "fr"
              ? "Un signal n'est pas seulement bon parce que son rendement est positif: il doit passer plusieurs portes de contrôle."
              : "A signal is not good only because return is positive: it has to pass several control gates."
          }
          icon={ShieldCheck}
        >
          <EdgeGatesFigure lang={lang} />
        </FigureCard>

        <FigureCard
          id="figure-ic"
          title={lang === "fr" ? "IC: signal vs retour futur" : "IC: signal vs future return"}
          caption={
            lang === "fr"
              ? "L'IC regarde si les meilleurs scores correspondent vraiment aux meilleurs retours futurs."
              : "IC checks whether higher scores really map to better future returns."
          }
          icon={Activity}
        >
          <IcFigure lang={lang} />
        </FigureCard>

        <FigureCard
          id="figure-return-methods"
          title={lang === "fr" ? "Méthodes de retour" : "Return methods"}
          caption={
            lang === "fr"
              ? "Le point d'entrée et le point de sortie changent le rendement mesuré."
              : "Entry and exit points change the measured return."
          }
          icon={ArrowRight}
        >
          <ReturnMethodFigure lang={lang} />
        </FigureCard>

        <FigureCard
          id="figure-backtest-risk"
          title={lang === "fr" ? "Lire un backtest" : "Reading a backtest"}
          caption={
            lang === "fr"
              ? "La courbe equity donne le trajet, mais les métriques expliquent le risque pris pour y arriver."
              : "The equity curve gives the path, while metrics explain the risk taken to get there."
          }
          icon={LineChart}
        >
          <BacktestFigure lang={lang} />
        </FigureCard>
      </div>
    </section>
  )
}

type BloombergStep = {
  title: LocalizedCopy
  body: LocalizedCopy
  hint?: LocalizedCopy
}

type LocalizedCopy = { fr: string; en: string }

const bloombergSteps: BloombergStep[] = [
  {
    title: {
      fr: "Asseyez-vous devant le poste qui a le Terminal Bloomberg",
      en: "Sit at the computer that has the Bloomberg Terminal",
    },
    body: {
      fr: "C'est la seule contrainte de toute la procédure. Bloomberg ne répond qu'en local, sur la machine où le Terminal tourne : aucun serveur distant, aucun onglet de navigateur seul ne peut lire ses données. Ouvrez Bloomberg et connectez-vous normalement (biométrie / B-Unit) avant de commencer.",
      en: "This is the only real constraint. Bloomberg only answers locally, on the machine where the Terminal runs: no remote server and no browser tab on its own can read its data. Open Bloomberg and log in as usual (biometrics / B-Unit) before you start.",
    },
  },
  {
    title: {
      fr: "Ouvrez l'application déployée dans le navigateur de ce poste",
      en: "Open the deployed app in that computer's browser",
    },
    body: {
      fr: "Connectez-vous à l'application comme d'habitude, puis allez sur Données → onglet Bloomberg. Tout le reste se fait depuis cette page : rien à transporter sur clé USB, rien à installer à l'avance.",
      en: "Sign in to the app as usual, then go to Data → Bloomberg tab. Everything else happens from that page: nothing to carry on a USB stick, nothing to install ahead of time.",
    },
    hint: { fr: "Données → Bloomberg", en: "Data → Bloomberg" },
  },
  {
    title: {
      fr: "Générez un code de connexion",
      en: "Generate a connection code",
    },
    body: {
      fr: "Dans la carte « Connexion d'un poste Bloomberg », donnez un nom au poste (par exemple « Salle des marchés ») et cliquez sur Générer un code de connexion. L'application crée un code à usage unique, valable une heure, et l'insère automatiquement dans une commande prête à coller — l'URL de l'application et le nom du poste y sont déjà.",
      en: "In the “Connect a Bloomberg terminal” card, name the machine (for example “Trading floor”) and click Generate a connection code. The app mints a single-use code, valid for one hour, and drops it into a ready-to-paste command that already carries the app URL and the terminal name.",
    },
  },
  {
    title: {
      fr: "Collez la commande sur le poste Bloomberg",
      en: "Paste the command on the Bloomberg computer",
    },
    body: {
      fr: "Choisissez l'onglet PowerShell ou Jupyter selon ce que le poste autorise, cliquez sur Copier la commande, puis collez-la dans une fenêtre PowerShell (menu Démarrer → PowerShell) ou dans une cellule Jupyter, et exécutez. Si le copier-coller est bloqué, utilisez Télécharger le script et lancez le fichier obtenu.",
      en: "Pick the PowerShell or Jupyter tab depending on what the machine allows, click Copy command, then paste it into a PowerShell window (Start menu → PowerShell) or a Jupyter cell and run it. If copy-paste is blocked, use Download script and run the downloaded file instead.",
    },
    hint: {
      fr: "PowerShell si autorisé, sinon Jupyter",
      en: "PowerShell if allowed, otherwise Jupyter",
    },
  },
  {
    title: {
      fr: "Laissez le script travailler",
      en: "Let the script do the work",
    },
    body: {
      fr: "Il trouve Python, installe ce qui manque (requests, pandas, pyarrow, xbbg), télécharge le connecteur depuis l'application, échange le code contre une clé propre à ce poste, et se met à écouter. Vous n'avez ni clé à taper ni fichier à modifier. Comptez une à trois minutes la première fois.",
      en: "It locates Python, installs what is missing (requests, pandas, pyarrow, xbbg), downloads the connector from the app, exchanges the code for a key specific to this machine, and starts listening. No key to type, no file to edit. Allow one to three minutes on the first run.",
    },
  },
  {
    title: {
      fr: "Vérifiez que le poste apparaît comme connecté",
      en: "Check that the terminal shows as connected",
    },
    body: {
      fr: "La carte passe de « En attente du poste Bloomberg » à « connecté » toute seule, et le poste apparaît dans la liste des postes enregistrés. À partir de là, tout se pilote depuis l'application : Discovery, Backfill, Refresh.",
      en: "The card flips from “Waiting for the Bloomberg computer” to “connected” on its own, and the machine appears in the registered-terminals list. From then on everything is driven from the app: Discovery, Backfill, Refresh.",
    },
  },
  {
    title: {
      fr: "Gardez la fenêtre ouverte",
      en: "Keep the window open",
    },
    body: {
      fr: "La fenêtre PowerShell (ou la cellule Jupyter) doit rester ouverte tant que vous lancez des jobs. La fermer déconnecte simplement le poste ; il se reconnecte en relançant la même commande, sans nouveau code, tant que la clé locale est en place.",
      en: "The PowerShell window (or Jupyter cell) must stay open while you run jobs. Closing it simply disconnects the terminal; re-running the same command reconnects it without a new code, as long as the local key is still there.",
    },
  },
]

const bloombergTroubleshooting: Array<{ symptom: LocalizedCopy; fix: LocalizedCopy }> = [
  {
    symptom: { fr: "« No usable Python found »", en: "“No usable Python found”" },
    fix: {
      fr: "Le poste n'a pas de Python accessible en ligne de commande. Utilisez l'onglet Jupyter : la même connexion se fait depuis une cellule du notebook Bloomberg.",
      en: "The machine has no Python on the command line. Use the Jupyter tab: the same connection runs from a notebook cell instead.",
    },
  },
  {
    symptom: { fr: "« No module named xbbg »", en: "“No module named xbbg”" },
    fix: {
      fr: "L'environnement Python n'a pas l'accès Bloomberg. L'installation a été bloquée par la politique du poste : demandez à l'IT d'activer l'API Python Bloomberg pour cet environnement.",
      en: "That Python environment has no Bloomberg access. The install was blocked by machine policy: ask IT to enable the Bloomberg Python API for that environment.",
    },
  },
  {
    symptom: { fr: "Erreur blpapi ou « session failed »", en: "blpapi error or “session failed”" },
    fix: {
      fr: "Le Terminal Bloomberg est fermé ou déconnecté. Ouvrez-le, connectez-vous, puis relancez la commande.",
      en: "The Bloomberg Terminal is closed or logged out. Open it, log in, then re-run the command.",
    },
  },
  {
    symptom: { fr: "« Enrollment token has expired »", en: "“Enrollment token has expired”" },
    fix: {
      fr: "Le code dure une heure. Regénérez-en un dans l'application et recollez la nouvelle commande.",
      en: "Codes last one hour. Generate a new one in the app and paste the new command.",
    },
  },
  {
    symptom: { fr: "Le poste reste « En attente »", en: "The terminal stays “Waiting”" },
    fix: {
      fr: "La commande n'a pas encore fini, ou le réseau de la banque bloque le domaine de l'application. Vérifiez que la page s'ouvre bien dans le navigateur de ce poste.",
      en: "The command has not finished yet, or the bank network blocks the app domain. Check that the page itself opens in that machine's browser.",
    },
  },
  {
    symptom: { fr: "Les jobs restent en file d'attente", en: "Jobs stay queued" },
    fix: {
      fr: "La fenêtre du connecteur a été fermée. Relancez la même commande sur le poste Bloomberg.",
      en: "The connector window was closed. Re-run the same command on the Bloomberg computer.",
    },
  },
]

function BloombergConnectionGuide({ lang }: { lang: GlossaryLanguage }) {
  return (
    <section id="bloomberg-connexion" className="scroll-mt-24 space-y-3">
      <div>
        <h2 className="text-base font-semibold tracking-tight">
          {lang === "fr" ? "Connecter un poste Bloomberg" : "Connect a Bloomberg terminal"}
        </h2>
        <p className="mt-1 max-w-3xl text-sm leading-relaxed text-muted-foreground">
          {lang === "fr"
            ? "Procédure complète, à faire une seule fois par poste, entièrement depuis l'application déployée."
            : "Full procedure, done once per machine, entirely from the deployed app."}
        </p>
      </div>

      <div className="rounded-lg border border-line bg-bg2 p-4 text-sm leading-relaxed text-muted-foreground">
        <p>
          <strong className="text-foreground">
            {lang === "fr" ? "Ce qu'il faut comprendre d'abord : " : "What to understand first: "}
          </strong>
          {lang === "fr"
            ? "Bloomberg n'expose ses données qu'en local, sur la machine où tourne le Terminal. Un onglet de navigateur ne peut donc pas les lire, et le serveur de l'application non plus. Un petit programme doit tourner sur ce poste — mais c'est l'application qui le fabrique, le configure et le distribue. Vous ne transportez ni fichier, ni clé, ni configuration."
            : "Bloomberg only exposes its data locally, on the machine running the Terminal. A browser tab therefore cannot read it, and neither can the app server. One small program has to run on that machine — but the app builds, configures and hands it out. You carry no file, no key, no configuration."}
        </p>
      </div>

      <ol className="space-y-2.5">
        {bloombergSteps.map((step, index) => (
          <li
            key={step.title.en}
            className="flex gap-3 rounded-lg border border-line bg-card p-4 shadow-xs"
          >
            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[oklch(0.94_0.04_260_/_0.55)] text-xs font-semibold text-[oklch(0.30_0.14_260)]">
              {index + 1}
            </span>
            <div className="min-w-0 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-semibold tracking-tight">{step.title[lang]}</h3>
                {step.hint ? (
                  <Badge variant="outline" className="text-[10px] font-medium">
                    {step.hint[lang]}
                  </Badge>
                ) : null}
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">{step.body[lang]}</p>
            </div>
          </li>
        ))}
      </ol>

      <div className="flex flex-wrap items-center gap-2">
        <Link
          href="/data"
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line bg-background px-3 text-xs font-medium text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
        >
          <Database className="h-3.5 w-3.5" />
          {lang === "fr" ? "Ouvrir Données → Bloomberg" : "Open Data → Bloomberg"}
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      <div className="rounded-lg border border-line bg-card p-4 shadow-xs">
        <h3 className="text-sm font-semibold tracking-tight">
          {lang === "fr" ? "Si quelque chose bloque" : "If something goes wrong"}
        </h3>
        <dl className="mt-3 space-y-2.5">
          {bloombergTroubleshooting.map((row) => (
            <div key={row.symptom.en} className="grid gap-1 sm:grid-cols-[minmax(0,15rem)_minmax(0,1fr)] sm:gap-3">
              <dt className="font-mono text-xs text-foreground">{row.symptom[lang]}</dt>
              <dd className="text-sm leading-relaxed text-muted-foreground">{row.fix[lang]}</dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="rounded-lg border border-line bg-bg2 p-4 text-xs leading-relaxed text-muted-foreground">
        <strong className="text-foreground">{lang === "fr" ? "Sécurité. " : "Security. "}</strong>
        {lang === "fr"
          ? "Le connecteur ne fait que des appels sortants en HTTPS vers l'application : rien n'est ouvert en entrée sur le poste. L'application ne reçoit jamais l'identifiant Bloomberg du poste, seulement les données demandées. Chaque poste a sa propre clé, révocable à tout moment depuis la liste des postes enregistrés, et le code de connexion expire au bout d'une heure. La redistribution des données Bloomberg reste soumise au contrat de licence du Terminal : vérifiez la portée autorisée avant tout usage en production."
          : "The connector only makes outbound HTTPS calls to the app: nothing is opened inbound on the machine. The app never receives the Bloomberg login, only the requested data. Each machine gets its own key, revocable at any time from the registered-terminals list, and the connection code expires after one hour. Redistributing Bloomberg data remains governed by the Terminal licence agreement: confirm the permitted scope before any production use."}
      </div>
    </section>
  )
}

function AppGuideCard({
  entry,
  icon: Icon,
  href,
  lang,
}: {
  entry: GlossaryEntry
  icon: typeof LayoutDashboard
  href: string
  lang: GlossaryLanguage
}) {
  return (
    <div id={`guide-${entry.id}`} className="rounded-lg border border-line bg-card p-4 shadow-xs">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-[oklch(0.94_0.04_260_/_0.55)] text-[oklch(0.30_0.14_260)]">
            <Icon className="h-4 w-4" />
          </span>
          <div>
            <a href={`#${entry.id}`} className="text-sm font-semibold hover:underline">
              {entry.title[lang]}
            </a>
            <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">{href}</div>
          </div>
        </div>
        <Button asChild variant="ghost" size="icon-sm" className="h-7 w-7 text-muted-foreground">
          <Link href={href} aria-label={lang === "fr" ? `Ouvrir ${entry.title.fr}` : `Open ${entry.title.en}`}>
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </Button>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{entry.plain[lang]}</p>
    </div>
  )
}

function TermCard({
  entry,
  category,
  lang,
}: {
  entry: GlossaryEntry
  category: GlossaryCategory
  lang: GlossaryLanguage
}) {
  const aliases = entry.aliases?.slice(0, 6) ?? []

  return (
    <article id={entry.id} className="scroll-mt-24 rounded-lg border border-line bg-card p-4 shadow-xs">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold tracking-tight">{entry.title[lang]}</h3>
            <Badge variant="secondary" className={cn("border-transparent", categoryTone[category.id])}>
              {category.label[lang]}
            </Badge>
          </div>
          <a
            href={`#${entry.id}`}
            className="mt-1 inline-flex items-center gap-1 font-mono text-[11px] text-muted-foreground hover:text-foreground"
          >
            <Hash className="h-3 w-3" />
            {entry.id}
          </a>
        </div>
      </div>

      <p className="mt-3 text-sm leading-relaxed text-foreground">{entry.plain[lang]}</p>

      {entry.details?.length ? (
        <div className="mt-3 space-y-2">
          {entry.details.map((detail, index) => (
            <p key={index} className="text-sm leading-relaxed text-muted-foreground">
              {detail[lang]}
            </p>
          ))}
        </div>
      ) : null}

      {entry.formula ? (
        <div className="mt-3 rounded-md border border-line bg-bg2 px-3 py-2">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            {lang === "fr" ? "Formule" : "Formula"}
          </div>
          <div className="mt-1 font-mono text-xs text-foreground">{entry.formula}</div>
        </div>
      ) : null}

      {entry.example ? (
        <div className="mt-3 rounded-md border border-dashed border-line bg-[oklch(0.98_0.003_250)] px-3 py-2 text-sm text-muted-foreground">
          <span className="font-semibold text-foreground">{lang === "fr" ? "Exemple: " : "Example: "}</span>
          {entry.example[lang]}
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {entry.appLinks?.map((link) => (
          <GlossaryLink
            key={`${entry.id}-${link.href}`}
            href={link.href}
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-line bg-background px-2 text-xs font-medium text-foreground transition hover:bg-accent hover:text-accent-foreground"
          >
            {link.label[lang]}
            <ArrowRight className="h-3 w-3" />
          </GlossaryLink>
        ))}
        {aliases.map((alias) => (
          <span key={alias} className="rounded-md bg-bg2 px-2 py-1 font-mono text-[10px] text-muted-foreground">
            {alias}
          </span>
        ))}
      </div>
    </article>
  )
}

export default function GlossaryPage() {
  const [lang, setLang] = useState<GlossaryLanguage>("fr")
  const [query, setQuery] = useState("")
  const [activeCategory, setActiveCategory] = useState<string>("all")

  const normalizedQuery = normalizeText(query.trim())

  const entriesWithSearch = useMemo(
    () =>
      glossaryEntries.map((entry) => ({
        entry,
        haystack: normalizeText(textForSearch(entry)),
      })),
    [],
  )

  const filteredEntries = useMemo(() => {
    return entriesWithSearch
      .filter(({ entry }) => activeCategory === "all" || entry.categoryId === activeCategory)
      .filter(({ haystack }) => !normalizedQuery || haystack.includes(normalizedQuery))
      .map(({ entry }) => entry)
  }, [activeCategory, entriesWithSearch, normalizedQuery])

  const groupedEntries = useMemo(() => {
    return glossaryCategories
      .map((category) => ({
        category,
        entries: filteredEntries.filter((entry) => entry.categoryId === category.id),
      }))
      .filter((group) => group.entries.length > 0)
  }, [filteredEntries])

  const categoryCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const { entry, haystack } of entriesWithSearch) {
      if (normalizedQuery && !haystack.includes(normalizedQuery)) continue
      counts.set(entry.categoryId, (counts.get(entry.categoryId) ?? 0) + 1)
    }
    return counts
  }, [entriesWithSearch, normalizedQuery])

  const appEntries = appGuide
    .map((item) => ({
      ...item,
      entry: glossaryEntries.find((entry) => entry.id === item.id),
    }))
    .filter((item): item is (typeof appGuide)[number] & { entry: GlossaryEntry } => Boolean(item.entry))

  return (
    <div className="claude-page space-y-5">
      <section className="rounded-lg border border-line bg-card p-5 shadow-xs">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-3xl">
            <div className="flex flex-wrap items-center gap-2">
              <span className="grid h-9 w-9 place-items-center rounded-lg bg-[oklch(0.94_0.04_260_/_0.55)] text-[oklch(0.30_0.14_260)]">
                <BookOpen className="h-4 w-4" />
              </span>
              <div>
                <h1 className="text-2xl font-semibold tracking-tight">
                  {lang === "fr" ? "Glossaire de la plateforme" : "Platform glossary"}
                </h1>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                  {lang === "fr"
                    ? "Définitions simples avec liens directs vers chaque concept, résultat et partie de l'app."
                    : "Plain-language definitions with direct links to each concept, result, and app area."}
                </p>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <Languages className="h-3.5 w-3.5" />
              {lang === "fr" ? "Langue" : "Language"}
            </span>
            <div className="inline-flex rounded-md border border-line bg-bg2 p-0.5">
              {languageOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setLang(option.value)}
                  className={cn(
                    "h-7 rounded px-2.5 text-xs font-semibold transition-colors",
                    lang === option.value ? "bg-card text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground",
                  )}
                  title={option.full}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-5 flex flex-wrap gap-2">
          {quickGlossaryLinks.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="inline-flex h-8 items-center rounded-md border border-line bg-background px-3 text-xs font-medium text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
            >
              {link.label[lang]}
            </a>
          ))}
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-[270px_minmax(0,1fr)]">
        <aside className="space-y-3 lg:sticky lg:top-20 lg:self-start">
          <Card className="claude-card">
            <CardHeader>
              <CardTitle>{lang === "fr" ? "Rechercher" : "Search"}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={lang === "fr" ? "Score, WFO, ADV20..." : "Score, WFO, ADV20..."}
                  className="h-9 pl-8 pr-8 text-sm"
                />
                {query ? (
                  <button
                    type="button"
                    onClick={() => setQuery("")}
                    className="absolute right-2 top-1/2 grid h-5 w-5 -translate-y-1/2 place-items-center rounded text-muted-foreground hover:bg-bg3 hover:text-foreground"
                    aria-label={lang === "fr" ? "Effacer la recherche" : "Clear search"}
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                ) : null}
              </div>

              <div className="space-y-1">
                <button
                  type="button"
                  onClick={() => setActiveCategory("all")}
                  className={cn(
                    "flex w-full items-center justify-between rounded-md px-2.5 py-2 text-left text-xs transition-colors",
                    activeCategory === "all" ? "bg-bg3 font-semibold text-foreground" : "text-muted-foreground hover:bg-bg2 hover:text-foreground",
                  )}
                >
                  <span>{lang === "fr" ? "Tous les termes" : "All terms"}</span>
                  <span className="font-mono">{normalizedQuery ? filteredEntries.length : glossaryEntries.length}</span>
                </button>
                {glossaryCategories.map((category) => (
                  <button
                    key={category.id}
                    type="button"
                    onClick={() => setActiveCategory(category.id)}
                    className={cn(
                      "flex w-full items-center justify-between rounded-md px-2.5 py-2 text-left text-xs transition-colors",
                      activeCategory === category.id ? "bg-bg3 font-semibold text-foreground" : "text-muted-foreground hover:bg-bg2 hover:text-foreground",
                    )}
                  >
                    <span>{category.label[lang]}</span>
                    <span className="font-mono">{categoryCounts.get(category.id) ?? 0}</span>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card className="claude-card">
            <CardHeader>
              <CardTitle>{lang === "fr" ? "Liens directs" : "Direct links"}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5">
              {quickGlossaryLinks.slice(0, 8).map((link) => (
                <a
                  key={`side-${link.href}`}
                  href={link.href}
                  className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-bg2 hover:text-foreground"
                >
                  <span>{link.label[lang]}</span>
                  <span className="font-mono text-[10px]">{linkLabel(link.href)}</span>
                </a>
              ))}
            </CardContent>
          </Card>
        </aside>

        <main className="min-w-0 space-y-5">
          <section className="space-y-3">
            <div className="flex items-end justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold tracking-tight">
                  {lang === "fr" ? "Parcours rapides" : "Fast paths"}
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {lang === "fr"
                    ? "Chaque carte explique une page et renvoie vers sa définition détaillée."
                    : "Each card explains one page and links to its detailed definition."}
                </p>
              </div>
              <span className="hidden text-xs text-muted-foreground sm:block">/{appEntries.length}</span>
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {appEntries.map((item) => (
                <AppGuideCard key={item.id} entry={item.entry} icon={item.icon} href={item.href} lang={lang} />
              ))}
            </div>
          </section>

          <section id="score-scale" className="scroll-mt-24 space-y-3">
            <div>
              <h2 className="text-base font-semibold tracking-tight">
                {lang === "fr" ? "Échelle rapide des scores" : "Quick score scale"}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {lang === "fr"
                  ? "Cette échelle est le repère principal pour lire les badges du Tableau de Bord."
                  : "This scale is the main reference for reading Dashboard badges."}
              </p>
            </div>
            <ScoreScale lang={lang} />
          </section>

          <BloombergConnectionGuide lang={lang} />

          <ExplanationFigures lang={lang} />

          <FundamentalsFigures lang={lang} />

          <section className="space-y-5">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3">
              <div>
                <h2 className="text-base font-semibold tracking-tight">
                  {lang === "fr" ? "Définitions" : "Definitions"}
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {filteredEntries.length} {lang === "fr" ? "termes affichés" : "terms shown"}
                </p>
              </div>
              {activeCategory !== "all" || query ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-8 gap-1.5 rounded-md text-xs"
                  onClick={() => {
                    setActiveCategory("all")
                    setQuery("")
                  }}
                >
                  <X className="h-3.5 w-3.5" />
                  {lang === "fr" ? "Réinitialiser" : "Reset"}
                </Button>
              ) : null}
            </div>

            {groupedEntries.length === 0 ? (
              <div className="rounded-lg border border-dashed border-line bg-card px-4 py-12 text-center text-sm text-muted-foreground">
                {lang === "fr" ? "Aucun terme ne correspond à cette recherche." : "No term matches this search."}
              </div>
            ) : (
              groupedEntries.map(({ category, entries }) => (
                <div key={category.id} id={`category-${category.id}`} className="scroll-mt-24 space-y-3">
                  <div className="flex flex-wrap items-end justify-between gap-3">
                    <div>
                      <h2 className="text-lg font-semibold tracking-tight">{category.label[lang]}</h2>
                      <p className="mt-1 max-w-3xl text-sm leading-relaxed text-muted-foreground">{category.description[lang]}</p>
                    </div>
                    <Badge variant="outline">{entries.length}</Badge>
                  </div>
                  <div className="space-y-3">
                    {entries.map((entry) => (
                      <TermCard key={entry.id} entry={entry} category={category} lang={lang} />
                    ))}
                  </div>
                </div>
              ))
            )}
          </section>
        </main>
      </div>
    </div>
  )
}
