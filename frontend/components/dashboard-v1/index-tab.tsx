"use client"

import { useMemo, useState } from "react"
import { ChevronDown, ChevronRight, Pencil, Plus, Trash2 } from "lucide-react"
import type { DashboardIndex, DashboardStock } from "@/lib/dashboard-types"
import { FAMILY_LABELS, FAMILY_ORDER, aggregateScoreLabel, familyScoreLabel } from "@/lib/dashboard-constants"
import { FamilyCell } from "./family-cell"
import { SignalBadge } from "./signal-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible"

interface IndexTabProps {
  baseIndex: DashboardIndex
  stocks: DashboardStock[]
  customDefinitions: Array<{ id: string; name: string; symbols: string[] }>
  readOnly: boolean
  actionError?: string | null
  onCreate?: (payload: { name: string; symbols: string[] }) => Promise<void>
  onUpdate?: (id: string, payload: { name: string; symbols: string[] }) => Promise<void>
  onDelete?: (id: string) => Promise<void>
}

interface IndexMember {
  symbol: string
  display_name: string | null
  signal_label: string | null
  aggregate_score_pct: number | null
  per_family: DashboardStock["per_family"]
}

interface ComputedIndex {
  id: string
  name: string
  stock_count: number
  aggregate_signal_label: string | null
  aggregate_score_pct: number | null
  per_family: DashboardIndex["per_family"]
  breadth: DashboardIndex["breadth"]
  members: IndexMember[]
  editable: boolean
}

const MASI_KEY = "__masi__"

function normalizeSymbols(symbols: string[]): string[] {
  const seen = new Set<string>()
  const normalized: string[] = []
  for (const raw of symbols) {
    const token = String(raw ?? "").trim().toUpperCase()
    if (!token || seen.has(token)) continue
    seen.add(token)
    normalized.push(token)
  }
  return normalized
}

function average(values: number[]): number | null {
  if (values.length === 0) return null
  const sum = values.reduce((acc, value) => acc + value, 0)
  return sum / values.length
}

function round2(value: number): number {
  return Math.round(value * 100) / 100
}

function breadthFromMembers(members: IndexMember[]) {
  let achat = 0
  let neutre = 0
  let vente = 0
  let indisponible = 0

  for (const member of members) {
    if (!member.signal_label) {
      indisponible += 1
      continue
    }
    if (member.signal_label.includes("Achat")) {
      achat += 1
      continue
    }
    if (member.signal_label.includes("Vente")) {
      vente += 1
      continue
    }
    neutre += 1
  }

  return { achat, neutre, vente, indisponible }
}

function BreadthBar({
  breadth,
  total,
}: {
  breadth: DashboardIndex["breadth"]
  total: number
}) {
  const pctAchat = total > 0 ? (breadth.achat / total) * 100 : 0
  const pctNeutre = total > 0 ? (breadth.neutre / total) * 100 : 0
  const pctVente = total > 0 ? (breadth.vente / total) * 100 : 0
  const pctIndisponible = total > 0 ? (breadth.indisponible / total) * 100 : 0

  return (
    <div className="space-y-1">
      <div className="flex h-3 w-full overflow-hidden rounded-full">
        {pctAchat > 0 && <div className="bg-emerald-500" style={{ width: `${pctAchat}%` }} />}
        {pctNeutre > 0 && <div className="bg-zinc-400" style={{ width: `${pctNeutre}%` }} />}
        {pctVente > 0 && <div className="bg-red-500" style={{ width: `${pctVente}%` }} />}
        {pctIndisponible > 0 && <div className="bg-slate-300" style={{ width: `${pctIndisponible}%` }} />}
      </div>
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span>{breadth.achat} Achat</span>
        <span>{breadth.neutre} Neutre</span>
        <span>{breadth.vente} Vente</span>
        {breadth.indisponible > 0 && <span>{breadth.indisponible} Indisponible</span>}
      </div>
    </div>
  )
}

export function IndexTab({
  baseIndex,
  stocks,
  customDefinitions,
  readOnly,
  actionError,
  onCreate,
  onUpdate,
  onDelete,
}: IndexTabProps) {
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [createName, setCreateName] = useState("")
  const [createSearch, setCreateSearch] = useState("")
  const [createSymbols, setCreateSymbols] = useState<string[]>([])
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState("")
  const [editSearch, setEditSearch] = useState("")
  const [editSymbols, setEditSymbols] = useState<string[]>([])
  const [isSubmitting, setIsSubmitting] = useState(false)

  const stockCatalog = useMemo(
    () =>
      [...stocks]
        .map((stock) => ({
          symbol: stock.symbol,
          display_name: stock.display_name,
        }))
        .sort((left, right) => left.symbol.localeCompare(right.symbol)),
    [stocks],
  )

  const stockBySymbol = useMemo(
    () =>
      new Map(
        stocks.map((stock) => [
          stock.symbol.toUpperCase(),
          stock,
        ]),
      ),
    [stocks],
  )

  const computedIndices = useMemo<ComputedIndex[]>(() => {
    const masiMembers: IndexMember[] = stocks.map((stock) => ({
      symbol: stock.symbol,
      display_name: stock.display_name,
      signal_label: stock.aggregate_signal_label,
      aggregate_score_pct: stock.aggregate_score_pct,
      per_family: stock.per_family,
    }))

    const base: ComputedIndex = {
      id: MASI_KEY,
      name: baseIndex.name || "MASI",
      stock_count: baseIndex.stock_count,
      aggregate_signal_label: baseIndex.aggregate_signal_label,
      aggregate_score_pct: baseIndex.aggregate_score_pct,
      per_family: baseIndex.per_family,
      breadth: baseIndex.breadth,
      members: masiMembers,
      editable: false,
    }

    const custom = customDefinitions.map((definition) => {
      const symbols = normalizeSymbols(definition.symbols)
      const members: IndexMember[] = symbols.map((symbol) => {
        const stock = stockBySymbol.get(symbol)
        return {
          symbol,
          display_name: stock?.display_name ?? null,
          signal_label: stock?.aggregate_signal_label ?? null,
          aggregate_score_pct: stock?.aggregate_score_pct ?? null,
          per_family: stock?.per_family ?? {},
        }
      })

      const aggregateValues = members
        .map((member) => member.aggregate_score_pct)
        .filter((value): value is number => typeof value === "number")
      const aggregateScore = average(aggregateValues)

      const perFamily: DashboardIndex["per_family"] = {}
      for (const family of FAMILY_ORDER) {
        const familyValues = members
          .map((member) => member.per_family[family]?.score_pct)
          .filter((value): value is number => typeof value === "number")
        const familyAvg = average(familyValues)
        if (familyAvg == null) continue
        perFamily[family] = {
          score_pct: round2(familyAvg),
          label: familyScoreLabel(family, familyAvg),
        }
      }

      return {
        id: definition.id,
        name: definition.name,
        stock_count: symbols.length,
        aggregate_signal_label: aggregateScore == null ? null : aggregateScoreLabel(aggregateScore),
        aggregate_score_pct: aggregateScore == null ? null : round2(aggregateScore),
        per_family: perFamily,
        breadth: breadthFromMembers(members),
        members,
        editable: true,
      } satisfies ComputedIndex
    })

    return [base, ...custom]
  }, [baseIndex, customDefinitions, stockBySymbol, stocks])

  function symbolOptions(query: string) {
    const normalized = query.trim().toLowerCase()
    if (!normalized) return stockCatalog
    return stockCatalog.filter(
      (stock) =>
        stock.symbol.toLowerCase().includes(normalized) ||
        (stock.display_name ?? "").toLowerCase().includes(normalized),
    )
  }

  function toggleSymbol(symbols: string[], symbol: string, setSymbols: (next: string[]) => void) {
    if (symbols.includes(symbol)) {
      setSymbols(symbols.filter((item) => item !== symbol))
      return
    }
    setSymbols([...symbols, symbol].sort())
  }

  async function submitCreate() {
    if (!onCreate || isSubmitting) return
    setIsSubmitting(true)
    try {
      await onCreate({ name: createName, symbols: createSymbols })
      setCreateName("")
      setCreateSearch("")
      setCreateSymbols([])
      setShowCreate(false)
    } finally {
      setIsSubmitting(false)
    }
  }

  function startEdit(index: ComputedIndex) {
    setEditingId(index.id)
    setEditName(index.name)
    setEditSearch("")
    setEditSymbols(index.members.map((member) => member.symbol))
  }

  async function submitEdit() {
    if (!editingId || !onUpdate || isSubmitting) return
    setIsSubmitting(true)
    try {
      await onUpdate(editingId, { name: editName, symbols: editSymbols })
      setEditingId(null)
      setEditName("")
      setEditSearch("")
      setEditSymbols([])
    } finally {
      setIsSubmitting(false)
    }
  }

  async function submitDelete(index: ComputedIndex) {
    if (!onDelete || isSubmitting) return
    const confirmed = window.confirm(`Supprimer l'indice "${index.name}" ?`)
    if (!confirmed) return
    setIsSubmitting(true)
    try {
      await onDelete(index.id)
      if (openKey === index.id) {
        setOpenKey(null)
      }
      if (editingId === index.id) {
        setEditingId(null)
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="space-y-4">
      {!readOnly && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="text-base">Indices personnalisés</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Créez des indices à partir d&apos;une liste manuelle d&apos;actions.
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                variant={showCreate ? "secondary" : "default"}
                onClick={() => setShowCreate((prev) => !prev)}
              >
                <Plus className="h-4 w-4" />
                Nouvel indice
              </Button>
            </div>
          </CardHeader>
          {showCreate && (
            <CardContent className="space-y-3">
              <Input
                value={createName}
                onChange={(event) => setCreateName(event.target.value)}
                placeholder="Nom de l'indice"
              />
              <Input
                value={createSearch}
                onChange={(event) => setCreateSearch(event.target.value)}
                placeholder="Rechercher un symbole"
              />
              <div className="max-h-52 space-y-2 overflow-y-auto rounded-md border p-3">
                {symbolOptions(createSearch).map((stock) => (
                  <label key={`create-${stock.symbol}`} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={createSymbols.includes(stock.symbol)}
                      onChange={() => toggleSymbol(createSymbols, stock.symbol, setCreateSymbols)}
                    />
                    <span className="font-mono">{stock.symbol}</span>
                    <span className="text-muted-foreground">{stock.display_name ?? "-"}</span>
                  </label>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <Button type="button" size="sm" onClick={submitCreate} disabled={isSubmitting}>
                  Enregistrer
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setShowCreate(false)
                    setCreateName("")
                    setCreateSearch("")
                    setCreateSymbols([])
                  }}
                >
                  Annuler
                </Button>
                <span className="text-xs text-muted-foreground">{createSymbols.length} symbole(s) sélectionné(s)</span>
              </div>
            </CardContent>
          )}
        </Card>
      )}

      {actionError && (
        <Card className="border-destructive">
          <CardContent className="py-3 text-sm text-destructive">{actionError}</CardContent>
        </Card>
      )}

      {computedIndices.map((index) => {
        const isOpen = openKey === index.id
        const isEditing = editingId === index.id
        return (
          <Collapsible key={index.id} open={isOpen}>
            <Card>
              <CardHeader
                className="cursor-pointer pb-3"
                onClick={() => setOpenKey(isOpen ? null : index.id)}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-2">
                    {isOpen ? <ChevronDown className="mt-0.5 h-4 w-4" /> : <ChevronRight className="mt-0.5 h-4 w-4" />}
                    <div>
                      <CardTitle className="text-base">{index.name}</CardTitle>
                      <p className="text-sm text-muted-foreground">{index.stock_count} action(s)</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <SignalBadge label={index.aggregate_signal_label} />
                    {!readOnly && index.editable && !isEditing && (
                      <>
                        <Button
                          type="button"
                          size="icon-sm"
                          variant="outline"
                          onClick={(event) => {
                            event.stopPropagation()
                            startEdit(index)
                          }}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          type="button"
                          size="icon-sm"
                          variant="destructive"
                          onClick={(event) => {
                            event.stopPropagation()
                            void submitDelete(index)
                          }}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </>
                    )}
                  </div>
                </div>
              </CardHeader>

              <CardContent className="space-y-4">
                {isEditing && !readOnly && index.editable && (
                  <div className="space-y-3 rounded-md border p-3">
                    <Input
                      value={editName}
                      onChange={(event) => setEditName(event.target.value)}
                      placeholder="Nom de l'indice"
                    />
                    <Input
                      value={editSearch}
                      onChange={(event) => setEditSearch(event.target.value)}
                      placeholder="Rechercher un symbole"
                    />
                    <div className="max-h-52 space-y-2 overflow-y-auto rounded-md border p-3">
                      {symbolOptions(editSearch).map((stock) => (
                        <label key={`edit-${index.id}-${stock.symbol}`} className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={editSymbols.includes(stock.symbol)}
                            onChange={() => toggleSymbol(editSymbols, stock.symbol, setEditSymbols)}
                          />
                          <span className="font-mono">{stock.symbol}</span>
                          <span className="text-muted-foreground">{stock.display_name ?? "-"}</span>
                        </label>
                      ))}
                    </div>
                    <div className="flex items-center gap-2">
                      <Button type="button" size="sm" onClick={submitEdit} disabled={isSubmitting}>
                        Enregistrer
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setEditingId(null)
                          setEditName("")
                          setEditSearch("")
                          setEditSymbols([])
                        }}
                      >
                        Annuler
                      </Button>
                      <span className="text-xs text-muted-foreground">{editSymbols.length} symbole(s) sélectionné(s)</span>
                    </div>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  {FAMILY_ORDER.map((family) => (
                    <div key={`${index.id}-${family}`} className="space-y-1">
                      <p className="text-sm font-medium">{FAMILY_LABELS[family]}</p>
                      <FamilyCell score={index.per_family[family]} />
                    </div>
                  ))}
                </div>

                <div className="space-y-2">
                  <p className="text-sm font-medium">Largeur de marche</p>
                  <BreadthBar breadth={index.breadth} total={index.stock_count} />
                </div>
              </CardContent>

              <CollapsibleContent forceMount>
                {isOpen && (
                  <CardContent className="pt-0">
                    <div className="rounded-md border">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Symbole</TableHead>
                            <TableHead>Nom</TableHead>
                            <TableHead>Décision</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {index.members.length === 0 ? (
                            <TableRow>
                              <TableCell colSpan={3} className="text-center text-sm text-muted-foreground">
                                Aucune action dans cet indice.
                              </TableCell>
                            </TableRow>
                          ) : (
                            index.members.map((member) => (
                              <TableRow key={`${index.id}-${member.symbol}`}>
                                <TableCell className="font-mono font-medium">{member.symbol}</TableCell>
                                <TableCell className="text-muted-foreground">{member.display_name ?? "-"}</TableCell>
                                <TableCell>
                                  <SignalBadge label={member.signal_label} />
                                </TableCell>
                              </TableRow>
                            ))
                          )}
                        </TableBody>
                      </Table>
                    </div>
                  </CardContent>
                )}
              </CollapsibleContent>
            </Card>
          </Collapsible>
        )
      })}
    </div>
  )
}
