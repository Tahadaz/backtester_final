"use client"

import type { SignalRepresentative } from "@/lib/api"
import { SignalBadge } from "@/components/signal-badge"
import { formatNumber } from "@/lib/format"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Badge } from "@/components/ui/badge"

export function VariantDetailSheet({
  variant,
  open,
  onClose,
}: {
  variant: SignalRepresentative | null
  open: boolean
  onClose: () => void
}) {
  if (!variant) return null

  return (
    <Sheet open={open} onOpenChange={(v) => !v && onClose()}>
      <SheetContent className="sm:max-w-md overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2 text-sm">
            {variant.variant_id}
            <SignalBadge value={variant.signal} size="sm" />
          </SheetTitle>
        </SheetHeader>

        <div className="mt-6 space-y-5">
          {/* Signal info */}
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-xs text-muted-foreground">Signal</span>
              <div className="font-semibold">{variant.signal_label}</div>
            </div>
            <div>
              <span className="text-xs text-muted-foreground">Contribution</span>
              <div className="font-semibold">
                {formatNumber(variant.contribution * 100, 1)}%
              </div>
            </div>
          </div>

          {/* Values */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Valeurs
            </h4>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div className="flex justify-between rounded-md border px-3 py-2">
                <span className="text-muted-foreground">Clôture</span>
                <span className="font-mono font-semibold">
                  {formatNumber(variant.current_close)}
                </span>
              </div>
              <div className="flex justify-between rounded-md border px-3 py-2">
                <span className="text-muted-foreground">Indicateur</span>
                <span className="font-mono font-semibold">
                  {variant.indicator_value != null
                    ? formatNumber(variant.indicator_value)
                    : "—"}
                </span>
              </div>
            </div>
          </div>

          {/* Weights */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Poids
            </h4>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div className="flex justify-between rounded-md border px-3 py-2">
                <span className="text-muted-foreground">Fiabilité</span>
                <Badge variant="outline" className="text-[10px]">
                  {formatNumber(variant.reliability_weight, 3)}
                </Badge>
              </div>
              <div className="flex justify-between rounded-md border px-3 py-2">
                <span className="text-muted-foreground">Normalisé</span>
                <Badge variant="outline" className="text-[10px]">
                  {formatNumber(variant.normalized_weight, 3)}
                </Badge>
              </div>
            </div>
          </div>

          {/* Explanation */}
          <div className="space-y-2">
            <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Explication
            </h4>
            <p className="text-sm text-muted-foreground leading-relaxed rounded-md border p-3 bg-muted/30">
              {variant.explanation}
            </p>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}
