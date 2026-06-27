"use client"

import type { ReactNode } from "react"
import Link from "next/link"
import { HelpCircle } from "lucide-react"

import { glossaryEntries, type GlossaryLanguage } from "@/lib/glossary"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

const entryById = new Map(glossaryEntries.map((entry) => [entry.id, entry]))

/**
 * Inline term that links to its full glossary definition (`/glossary#<id>`) and
 * surfaces the plain-language summary on hover. Used to connect terminology on
 * the fundamental/valuation pages back to the glossary.
 */
export function GlossaryTerm({
  id,
  children,
  className,
  lang = "fr",
  iconOnly = false,
}: {
  id: string
  children?: ReactNode
  className?: string
  lang?: GlossaryLanguage
  iconOnly?: boolean
}) {
  const entry = entryById.get(id)

  const link = (
    <Link
      href={`/glossary#${id}`}
      target="_blank"
      rel="noreferrer"
      className={cn(
        "inline-flex items-center gap-0.5 align-baseline text-inherit transition-colors hover:text-foreground",
        !iconOnly && "underline decoration-dotted decoration-muted-foreground/50 underline-offset-2",
        className,
      )}
      aria-label={entry ? `${entry.title[lang]} - voir le glossaire` : "Voir le glossaire"}
      onClick={(event) => event.stopPropagation()}
    >
      {!iconOnly ? children : null}
      <HelpCircle className="h-3 w-3 shrink-0 opacity-60" aria-hidden />
    </Link>
  )

  if (!entry) return link

  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent className="max-w-xs whitespace-normal bg-card text-foreground shadow-md ring-1 ring-line">
        <span className="block text-xs font-semibold">{entry.title[lang]}</span>
        <span className="mt-1 block text-[11px] leading-relaxed text-muted-foreground">{entry.plain[lang]}</span>
        <span className="mt-1.5 block text-[10px] font-medium text-primary">
          {lang === "fr" ? "Ouvrir la définition →" : "Open definition →"}
        </span>
      </TooltipContent>
    </Tooltip>
  )
}
