import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { CrossAssetClass } from "@/lib/api"

export function StrategyOverview({ assetClass, strategy }: { assetClass: CrossAssetClass; strategy?: Record<string, unknown> | null }) {
  if (assetClass !== "fx") return <Empty assetClass={assetClass} />
  const fidelity = String(strategy?.replication_fidelity ?? "adapted")
  return (
    <Card><CardHeader><CardTitle>Thèse et source de recherche</CardTitle></CardHeader><CardContent className="space-y-3 text-sm">
      <div className="flex gap-2"><Badge>G10 vs USD</Badge><Badge variant="outline">{fidelity}</Badge><Badge variant="outline">Données réelles</Badge></div>
      <p>Deux réplications systématiques: Time-Series Momentum 12 mois et carry cross-sectionnel, ciblant 10% de volatilité annuelle.</p>
      <p className="text-muted-foreground">MOP / Koijen et al. — adaptation mensuelle avec taux directeurs FRED comme proxies. Les proxies ne sont pas des forwards tradables.</p>
    </CardContent></Card>
  )
}

function Empty({ assetClass }: { assetClass: CrossAssetClass }) {
  return <Card><CardContent className="py-12 text-center text-sm text-muted-foreground">{assetClass === "commodity" ? "Commodities" : "Rates & Bonds"}: activation prévue par le même composant, sans nouveau dossier UI.</CardContent></Card>
}
