"use client"

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"

export function MethodologyModal({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-lg max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Méthodologie du Signal Engine</DialogTitle>
          <DialogDescription>
            Comment les signaux sont calculés et agrégés
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 text-sm leading-relaxed">
          <section>
            <h4 className="font-semibold mb-1">1. Univers de variantes</h4>
            <p className="text-muted-foreground">
              Pour chaque famille d&apos;indicateurs (ex: SMA), un grand nombre de
              variantes paramétriques sont testées via Walk-Forward Optimization
              (WFO) sur l&apos;historique complet du titre.
            </p>
          </section>

          <section>
            <h4 className="font-semibold mb-1">2. Filtrage en entonnoir</h4>
            <p className="text-muted-foreground">
              Les variantes passent par un entonnoir de sélection: testées →
              viables (rentables OOS) → compétitives (Sharpe &gt; seuil) →
              représentatives (top-N par diversité).
            </p>
          </section>

          <section>
            <h4 className="font-semibold mb-1">3. Score de fiabilité</h4>
            <p className="text-muted-foreground">
              Chaque variante représentative reçoit un poids de fiabilité basé sur
              ses métriques OOS (Sharpe, drawdown, nombre de trades, consistance).
            </p>
          </section>

          <section>
            <h4 className="font-semibold mb-1">4. Agrégation pondérée</h4>
            <p className="text-muted-foreground">
              Le signal final de la famille est la moyenne pondérée des signaux
              individuels (BUY=+1, SELL=−1, HOLD=0), exprimée en pourcentage de
              0% à 100%.
            </p>
          </section>

          <section>
            <h4 className="font-semibold mb-1">5. Consensus des signaux</h4>
            <p className="text-muted-foreground">
              Le speedomètre principal affiche le consensus des signaux en combinant
              les scores de toutes les familles actives. Actuellement, seule la
              famille SMA est opérationnelle.
            </p>
          </section>

          <section>
            <h4 className="font-semibold mb-1">6. Honnêteté méthodologique</h4>
            <p className="text-muted-foreground">
              Les familles non encore implémentées (RSI, MACD, OBV) sont
              clairement marquées &quot;N/A&quot;. Le score global reflète uniquement les
              données réelles disponibles.
            </p>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  )
}
