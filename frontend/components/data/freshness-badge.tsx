"use client"

import { Badge } from "@/components/ui/badge"

function daysSince(dateStr: string): number {
  const d = new Date(dateStr)
  const now = new Date()
  return Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24))
}

export function FreshnessBadge({ dataAsOf }: { dataAsOf: string }) {
  const days = daysSince(dataAsOf)

  if (days <= 1) {
    return (
      <Badge variant="outline" className="text-[10px] text-green-700 border-green-300 bg-green-50">
        À jour
      </Badge>
    )
  }
  if (days <= 7) {
    return (
      <Badge variant="outline" className="text-[10px] text-yellow-700 border-yellow-300 bg-yellow-50">
        {days}j
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="text-[10px] text-red-700 border-red-300 bg-red-50">
      {days}j — obsolète
    </Badge>
  )
}
