"use client"

export type PatternPrimitiveSlot = "context" | "setup" | "trigger" | "exit" | "risk"

export type PatternPrimitiveParameter = {
  id: string
  label: string
  value_type: "number" | "boolean" | "select" | "price_level" | "time_window"
  default_value?: unknown
  options?: Array<{ value: string; label: string }>
}

export type PatternPrimitiveDefinition = {
  id: string
  family: "ict" | "technical" | "custom"
  label: string
  slot: PatternPrimitiveSlot
  description: string
  parameters: PatternPrimitiveParameter[]
  emits_variables: string[]
  status: "available" | "planned"
}

export type StrategyRuleLibrary = {
  id: string
  label: string
  slots: PatternPrimitiveSlot[]
  primitives: PatternPrimitiveDefinition[]
}

export const ICT_RULE_LIBRARY: StrategyRuleLibrary = {
  id: "ict",
  label: "ICT",
  slots: ["context", "setup", "trigger", "exit", "risk"],
  primitives: [],
}
