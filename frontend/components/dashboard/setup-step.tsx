import type { ReactNode } from "react"
import { Eyebrow } from "@/components/ui/eyebrow"
import { Segmented, type SegmentedOption } from "@/components/ui/segmented"

interface SetupStepProps<T extends string> {
  index: number
  title: string
  hint?: string
  options: readonly SegmentedOption<T>[]
  value: T
  onChange: (value: T) => void
  inlineAfter?: ReactNode
}

export function SetupStep<T extends string>({
  index,
  title,
  hint,
  options,
  value,
  onChange,
  inlineAfter,
}: SetupStepProps<T>) {
  return (
    <div className="space-y-1.5 rounded-md border border-border bg-card px-3 py-2.5">
      <Eyebrow className="text-[10px]">
        <span className="text-primary">{index}.</span> {title}
      </Eyebrow>
      <div className="flex flex-wrap items-center gap-1.5">
        <Segmented value={value} options={options} onChange={onChange} className="flex-wrap" />
        {inlineAfter}
      </div>
      {hint ? <p className="text-[10px] text-muted-foreground">{hint}</p> : null}
    </div>
  )
}
