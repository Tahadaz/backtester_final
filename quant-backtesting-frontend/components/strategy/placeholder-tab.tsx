"use client"

import { Card, CardContent } from "@/components/ui/card"
import { Lock } from "lucide-react"

export function PlaceholderTab({ title }: { title: string }) {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center justify-center py-16 gap-3">
        <Lock className="h-8 w-8 text-muted-foreground/40" />
        <div className="text-center">
          <h3 className="text-sm font-semibold text-muted-foreground">{title}</h3>
          <p className="text-xs text-muted-foreground/60 mt-1">Bientôt disponible</p>
        </div>
      </CardContent>
    </Card>
  )
}
