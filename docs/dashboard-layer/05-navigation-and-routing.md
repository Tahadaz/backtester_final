# 05 — Navigation and Routing

## Overview

Two small modifications to existing files:
1. Add dashboard to the navigation header
2. Update root redirect from `/data` to `/dashboard`

---

## File: `frontend/components/signals-header.tsx` (MODIFY)

### Current state (for reference)

```typescript
// line 7
import { ChevronColumnIncreasing, Database, Gauge, Target } from "lucide-react"

// lines 9-14
const navItems = [
  { href: "/data", label: "Data", icon: Database },
  { href: "/signals", label: "Signals", icon: Gauge },
  { href: "/strategy", label: "Strategy", icon: Target },
  { href: "/backtest", label: "Backtest", icon: ChartColumnIncreasing },
]

// line 22
<Link href="/data" className="flex items-center gap-2.5">
```

### Change 1: Add `LayoutDashboard` import (line 7)

**Before**:
```typescript
import { ChartColumnIncreasing, Database, Gauge, Target } from "lucide-react"
```

**After**:
```typescript
import { ChartColumnIncreasing, Database, Gauge, LayoutDashboard, Target } from "lucide-react"
```

### Change 2: Add dashboard nav item as FIRST entry (line 10)

**Before**:
```typescript
const navItems = [
  { href: "/data", label: "Data", icon: Database },
```

**After**:
```typescript
const navItems = [
  { href: "/dashboard", label: "Tableau de Bord", icon: LayoutDashboard },
  { href: "/data", label: "Data", icon: Database },
```

### Change 3: Update logo link (line 22)

**Before**:
```typescript
<Link href="/data" className="flex items-center gap-2.5">
```

**After**:
```typescript
<Link href="/dashboard" className="flex items-center gap-2.5">
```

### What NOT to change

- Do NOT modify the `isActive` logic (`pathname.startsWith(item.href)`) — it works correctly because `/dashboard` doesn't collide with any existing route prefix
- Do NOT modify button styling, sizes, or the responsive layout
- Do NOT remove any existing nav items
- Do NOT rename the component or change its exports

---

## File: `frontend/app/page.tsx` (MODIFY)

### Current state

```typescript
import { redirect } from "next/navigation"

export default function HomePage() {
  redirect("/data")
}
```

### Change: Update redirect target

**Before**:
```typescript
  redirect("/data")
```

**After**:
```typescript
  redirect("/dashboard")
```

### What NOT to change

- Do NOT add `"use client"` — this is a server component and `redirect()` works in server components
- Do NOT change the function name or export
- Do NOT add any other logic

---

## Verification

After these changes:
1. Navigate to `/` → should redirect to `/dashboard`
2. The navigation bar shows 5 items: Tableau de Bord, Data, Signals, Strategy, Backtest
3. "Tableau de Bord" is highlighted when on `/dashboard`
4. Clicking the "BT" logo goes to `/dashboard`
5. All other nav items still work and highlight correctly on their respective pages
