"use client"

import { Badge } from "@/components/ui/badge"

type Props = {
  engineScore: number | null    // A→G score
  wfoScore: number | null       // WFO score
  wfoGrade: string | null       // "A" | "B" | "C" | "D" | "F"
}

export function SignalAgreementBadge({ engineScore, wfoScore, wfoGrade }: Props) {
  if (engineScore == null || wfoScore == null) return null

  const sameDirection =
    (engineScore > 15 && wfoScore > 15) ||
    (engineScore < -15 && wfoScore < -15) ||
    (Math.abs(engineScore) <= 15 && Math.abs(wfoScore) <= 15)

  const highConfidence = sameDirection && (wfoGrade === "A" || wfoGrade === "B")

  if (highConfidence) {
    return <Badge variant="default" className="bg-green-600">Forte convergence</Badge>
  }
  if (sameDirection) {
    return <Badge variant="secondary">Convergent</Badge>
  }
  return <Badge variant="destructive">Divergent</Badge>
}
