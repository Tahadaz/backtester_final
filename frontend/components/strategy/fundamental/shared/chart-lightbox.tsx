"use client"

import { type ReactNode, useEffect, useState } from "react"
import { Maximize2, X } from "lucide-react"

export function ChartLightbox({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false)
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [open])

  return (
    <div className="fund-chart-lightbox-host">
      <button type="button" className="fund-chart-expand" onClick={() => setOpen(true)} title={`Agrandir ${title}`} aria-label={`Agrandir ${title}`}>
        <Maximize2 className="h-3.5 w-3.5" />
      </button>
      {children}
      {open ? (
        <div className="fund-chart-modal" role="dialog" aria-modal="true" aria-label={title}>
          <div className="fund-chart-modal-panel">
            <div className="fund-chart-modal-head">
              <span>{title}</span>
              <button type="button" className="fund-chart-modal-close" onClick={() => setOpen(false)} title="Fermer" aria-label="Fermer">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="fund-chart-modal-body">{children}</div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
