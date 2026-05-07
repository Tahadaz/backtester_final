"use client"

import { useMacroCatalog } from "@/hooks/use-api"
import { enqueueMacroIngest } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { FreshnessBadge } from "@/components/data/freshness-badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { RefreshCw, Database } from "lucide-react"
import { toast } from "sonner"

export function MacroCatalogTable() {
  const { data: catalog, isLoading, mutate } = useMacroCatalog()

  async function handleRefreshOne(canonicalId: string) {
    try {
      await enqueueMacroIngest(canonicalId, "2010-01-01")
      toast.success(`Ingestion ${canonicalId} lancée`)
      setTimeout(() => mutate(), 8_000)
    } catch {
      toast.error(`Erreur pour ${canonicalId}`)
    }
  }

  return (
    <div className="space-y-3">
      {isLoading ? (
        <div className="space-y-2">
          {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow className="text-xs">
              <TableHead className="w-24">ID</TableHead>
              <TableHead>Description</TableHead>
              <TableHead className="w-32">Canaux</TableHead>
              <TableHead className="w-28 text-right">Dernière donnée</TableHead>
              <TableHead className="w-24 text-right">Lignes</TableHead>
              <TableHead className="w-28 text-right">Fraîcheur</TableHead>
              <TableHead className="w-16" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {(catalog ?? []).map((row) => (
              <TableRow key={row.canonical_id} className="text-xs">
                <TableCell className="font-mono font-semibold">{row.canonical_id}</TableCell>
                <TableCell className="text-muted-foreground">{row.description}</TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {row.channel_tags.slice(0, 3).map((t) => (
                      <Badge key={t} variant="outline" className="text-[9px] py-0">{t}</Badge>
                    ))}
                  </div>
                </TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">
                  {row.data_as_of ?? "—"}
                </TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">
                  {row.row_count != null ? row.row_count.toLocaleString() : "—"}
                </TableCell>
                <TableCell className="text-right">
                  {row.data_as_of ? (
                    <FreshnessBadge dataAsOf={row.data_as_of} />
                  ) : (
                    <Badge variant="outline" className="text-[10px] text-muted-foreground">
                      <Database className="h-2.5 w-2.5 mr-1" />
                      Vide
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-2 text-[10px]"
                    onClick={() => handleRefreshOne(row.canonical_id)}
                  >
                    <RefreshCw className="h-3 w-3" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
