import { cn } from "@/lib/utils"

export type SegmentedOption<T extends string> = {
  value: T
  label: string
}

interface SegmentedProps<T extends string> {
  value: T
  options: readonly SegmentedOption<T>[]
  onChange: (value: T) => void
  className?: string
}

export function Segmented<T extends string>({ value, options, onChange, className }: SegmentedProps<T>) {
  return (
    <div className={cn("inline-flex rounded-md border border-border bg-bg2 p-0.5", className)}>
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={cn(
              "min-w-0 rounded-[5px] px-2 py-1 text-[11px] font-medium transition",
              active
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
