# Codex Task: Frontend Schema — Add indicator field to ZoneRepSchema

## Goal

Update the Zod schema for zone-chart representative entries to accept the new `indicator` field that the backend now returns per representative.

## File to modify

`quant-backtesting-frontend/lib/api.ts`

## What to find

Search for `ZoneRepSchema` or a schema that defines `variant_id`, `weight`, `label` inside the zone chart section. It will look something like:

```typescript
const ZoneRepSchema = z.object({
  variant_id: z.string(),
  weight: z.number(),
  label: z.string(),
})
```

Or it might be inline within a larger schema.

## What to change

Add an `indicator` field that accepts any object (the indicator shape varies by family):

```typescript
const ZoneRepSchema = z.object({
  variant_id: z.string(),
  weight: z.number(),
  label: z.string(),
  indicator: z.record(z.string(), z.any()).nullable().optional(),
})
```

If `ZoneRepSchema` is not a named const but is inline, add the `indicator` field inline in the same way.

## Also update the TypeScript type

If there is a corresponding TypeScript type `SignalZoneChart` or a type inferred from the schema, ensure it includes:

```typescript
indicator?: Record<string, any> | null
```

on the representative entries.

## Do NOT modify

- Any other schema
- Any hooks
- Any other file

## Verification

Run `npx tsc --noEmit` from the `quant-backtesting-frontend` directory. Zero type errors expected.
