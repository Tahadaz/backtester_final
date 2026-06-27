# UI design language — fundamentals layer

> Design tokens, typographic system, color palette, density rules, and motion language. **Aligned with the Claude Design handoff** (see [20-claude-design-handoff.md](20-claude-design-handoff.md)). This is the implementation contract for the visual system; Codex applies these directly in Tailwind config + CSS modules + component styles.

## 1. Typography

### Type families

```css
--font-sans:  'DM Sans', system-ui, sans-serif;
--font-mono:  'DM Mono', 'Courier New', monospace;
--font-display: 'DM Sans', system-ui, sans-serif;
```

Self-host via `next/font/google`:

```typescript
// frontend/lib/fonts.ts
import { DM_Sans, DM_Mono } from "next/font/google"

export const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
  weight: ["400", "500", "600", "700"],
})

export const dmMono = DM_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
  weight: ["400", "500"],
})
```

Wrap the root layout (`frontend/app/layout.tsx`) with both font variables.

### Type scale

| Token | Size | Line height | Weight | Use |
|---|---|---|---|---|
| `text-xs` | 9–10px | 12–14px | 400 | Microcopy, label chips, footnotes, status chips |
| `text-sm` | 11px | 15px | 400 | Table cell body, secondary labels, sub-text |
| `text-base` | 12px | 16px | 400 | **Default body** — analyst's primary reading size |
| `text-md` | 13px | 18px | 500 | Tab labels, card titles, KPI labels |
| `text-lg` | 14px | 20px | 600 | Section headings inside tabs |
| `text-xl` | 18px | 22px | 700 | Big numbers (research ticket prices, scenario prices) |
| `text-2xl` | 22px | 26px | 700 | Hero numbers (research ticket symbol; DuPont values; recommendation) |
| `text-display` | 28–36px | 32–40px | 700 | Reserved — currently unused on fundamentals page |

### Numerical typography rules

1. **All numbers use the monospace family** (DM Mono via `font-mono` class). No exceptions.
2. **Tabular figures**: `font-variant-numeric: tabular-nums` set globally on `html, body, #root`.
3. **Right-align** numeric columns in tables. Always.
4. **Decimals:**
   - Percentages: 1 decimal (e.g. `+14.7%`, `-22.5%`).
   - Ratios with `x` suffix: 1 decimal (`13.6x`, `1.85×`).
   - Absolute MAD amounts ≥ 1000: 0 decimals (`MAD 24,500`).
   - Absolute MAD amounts < 1000: 1–2 decimals (`MAD 211.11`).
   - Score values (0–100): 0 decimals (`72`).
5. **Thousand separators**: French locale → `value.toLocaleString("fr-FR")`. Space separator (e.g. `24 500`).
6. **Negative numbers**: prefix minus sign, NO parentheses. `−12.4%` not `(12.4%)`.
7. **Percentages with sign for deltas**: `+14.7%` for upside, `−22.5%` for downside. Bare `15.3%` for absolute readings (e.g. ROE).
8. **Currency**: `MAD 312` (3-letter ISO before the number). For Bn: `132.0 Bn` (suffix).

### Heading rules

- Section headings inside tabs: sentence case, `text-lg` weight 600.
- Small section labels (above tables, above charts): UPPERCASE + `text-xs` + `tracking-wider` (`letter-spacing: .08em` to `.12em`) + muted color (`var(--fg3)`).
- Card titles: 13px weight 600, sentence case. No uppercase.

## 2. Color system

Per Claude Design — all colors in **oklch space** (not hex). Light + dark themes both specified.

### Light theme (default)

```css
:root {
  --background: oklch(0.975 0.002 250);
  --foreground: oklch(0.145 0.015 250);
  --card:       oklch(1 0 0);
  --bg2:        oklch(0.975 0.003 250);
  --bg3:        oklch(0.945 0.006 250);
  --fg1:        oklch(0.145 0.015 250);
  --fg2:        oklch(0.43 0.01 250);
  --fg3:        oklch(0.60 0.01 250);
  --muted-fg:   oklch(0.50 0.01 250);
  --primary:    oklch(0.42 0.14 260);
  --primary-fg: oklch(0.985 0 0);
  --pri-dim:    oklch(0.30 0.14 260);
  --pos:        oklch(0.50 0.13 165);
  --neg:        oklch(0.52 0.20 25);
  --success:    oklch(0.60 0.15 165);
  --border:     oklch(0.91 0.005 250);
  --line:       oklch(0.91 0.005 250);
  --radius:     0.625rem;
  --sidebar-w:  240px;
}
```

### Dark theme

```css
.dark {
  --background: oklch(0.13 0.005 250);
  --foreground: oklch(0.97 0 0);
  --card:       oklch(0.17 0.005 250);
  --bg2:        oklch(0.155 0.005 250);
  --bg3:        oklch(0.20 0.005 250);
  --fg1:        oklch(0.97 0 0);
  --fg2:        oklch(0.75 0.01 250);
  --fg3:        oklch(0.58 0.01 250);
  --muted-fg:   oklch(0.62 0.01 250);
  --primary:    oklch(0.60 0.16 260);
  --primary-fg: oklch(0.97 0 0);
  --pri-dim:    oklch(0.72 0.14 260);
  --pos:        oklch(0.65 0.15 165);
  --neg:        oklch(0.68 0.18 25);
  --border:     oklch(0.25 0.005 250);
  --line:       oklch(0.25 0.005 250);
}
```

### Color usage rules

1. **Color = signal, not decoration.** Never use color for visual interest alone. If you remove the color, the information conveyed must remain.
2. **Positive (green, `--pos`) only for upside / BUY / safe / improving / "good" peer comparison.** Never for "this number is large" or "this row is active".
3. **Negative (red, `--neg`) only for downside / SELL / distress / declining / "bad" peer comparison.** Never for negative numbers themselves — a negative number is shown with the minus sign in default foreground color, not in red, unless the metric semantics are negative (e.g. upside, return).
4. **Primary (`--primary`, `--pri-dim`) for active states, accents, the ensemble row in valuation methods table, the base scenario card border, the base case sensitivity cell outline.** Not for general decoration.
5. **All chips carry both color AND text** for accessibility. Never color-only signaling.
6. **No gradients except the 3 scenario cards** (bull/base/bear) which use specifically:
   - bull: `linear-gradient(180deg, oklch(0.96 .07 165 / .22), var(--card) 60%)`
   - base: `linear-gradient(180deg, oklch(0.94 .04 260 / .25), var(--card) 60%)`
   - bear: `linear-gradient(180deg, oklch(0.95 .08 25 / .15), var(--card) 60%)`
7. **No shadows** except the floating Tweaks panel: `box-shadow: 0 8px 28px oklch(0.18 .01 250 / .14)`.
8. **The sensitivity heatmap uses oklch interpolation** per the formula in [20-claude-design-handoff.md](20-claude-design-handoff.md).

### Semantic color tokens for chips

```css
.conf-h { border: 1px solid oklch(0.75 .13 165); background: oklch(0.96 .07 165 / .2); color: oklch(0.36 .15 165); }
.conf-m { border: 1px solid oklch(0.70 .10 230); background: oklch(0.95 .06 230 / .2); color: oklch(0.35 .12 230); }
.conf-l { border: 1px solid oklch(0.75 .10 80);  background: oklch(0.96 .05 80 / .2);  color: oklch(0.40 .10 80); }

.rec-buy  { background: oklch(0.96 .07 165 / .25); color: oklch(0.34 .15 165); }
.rec-hold { background: oklch(0.55 .01 250 / .10); color: var(--fg2); }
.rec-sell { background: oklch(0.95 .08 25 / .18);  color: oklch(0.40 .20 25); }

.cat-imp-high   { background: oklch(0.96 .07 165 / .35); color: oklch(0.34 .15 165); }
.cat-imp-medium { background: oklch(0.55 .01 250 / .10); color: var(--fg2); }
.cat-imp-low    { background: oklch(0.55 .01 250 / .06); color: var(--fg3); }
```

## 3. Spacing system

Use Tailwind's default 4px scale, constrained to:

```
1  = 4px    →  gap between chip and label
2  = 8px    →  padding inside chips, table cell horizontal
3  = 12px   →  padding inside cards
4  = 16px   →  vertical gap between sections within a card
6  = 24px   →  gap between cards
8  = 32px   →  page-level gutters
```

Do not use 5, 7, 9, 10. The scale must feel disciplined.

### Density rules

- **Table row height: 24–32px.** Body padding `7px 10px` (matches `tbl td { padding: 7px 10px }` in the design).
- **KPI tile (`stat` class):** padding 10px 12px, gap 3px between lbl/val/sub.
- **Card padding:** header 10px 14px, body 12px 14px.
- **Button height: 28px** standard, 26px for compact (`ctrl-sel`).
- **Mode pill:** padding 6px 14px 6px 8px, icon size 28px.
- **Tab height:** 36px (`.sig-tab`, `.fund-tab`).
- **Sidebar item:** padding 7px 11px.

## 4. Table grammar

### CSS reference

```css
.tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
.tbl th { padding: 6px 10px; text-align: left; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: var(--fg3); border-bottom: 1px solid var(--line); background: var(--bg2); white-space: nowrap; }
.tbl td { padding: 7px 10px; border-bottom: 1px solid var(--line); }
.tbl tr:last-child td { border-bottom: none; }
.tbl tr:hover td { background: var(--bg2); }
.tbl tr.sel td { background: oklch(0.94 .04 260 / .22); }
.tbl .r    { text-align: right; }
.tbl .mono { font-family: var(--font-mono); font-size: 11px; }
```

### Rules

1. **No vertical lines.** Ever.
2. **Horizontal hairline separator** between rows. None on the last row.
3. **Header row** — muted foreground, uppercase, tracking-wide, no bold (700 weight but uppercase + small size makes it readable, not heavy).
4. **Header background** subtle gray (`var(--bg2)`).
5. **Right-align numerics, left-align labels.** Mixed alignment in one column is forbidden.
6. **Sortable headers** show a small arrow when active.
7. **Hover on row**: subtle background (`var(--bg2)`).
8. **Active selection**: tinted `oklch(0.94 .04 260 / .22)` background, no border — `.sel` class.
9. **Zebra striping is forbidden.**

### Sparkline-in-cell

Reserved for cyclical metrics (e.g. financial trends row). 60–80px wide × 16–20px tall, single hairline path in `var(--fg2)`, no axes, no points.

## 5. Chip / badge grammar

```css
.badge {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 7px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 600;
}
.badge-out { border: 1px solid var(--line); color: var(--muted-fg); }

.spill {
  display: inline-flex;
  align-items: center;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 10px;
  font-weight: 600;
  line-height: 1.4;
  white-space: nowrap;
}
```

Rules:
- Height: 18–20px. Padding: 0 6–7px. Border-radius: 4px.
- Font: 10px weight 600. NOT uppercase by default (except specific cases like rec chips, cat-imp chips).
- For confidence (`high`/`medium`/`low`) and recommendation (`BUY`/`HOLD`/`SELL`): use the colored variants from §2.

## 6. Iconography

Use **lucide-react** exclusively (already in repo). Icon sizes:

- 10–11px inline with `text-xs` (sidebar search icon: 11px).
- 13–14px (`h-3.5 w-3.5`) inline with `text-base` / `text-md`.
- 16px (`h-4 w-4`) for standalone buttons.

Stroke width: 1.5 (lucide default).

Icon color: inherit from text.

## 7. Card grammar

```css
.card {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--card);
  overflow: hidden;
}
.card-hdr {
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.card-title { font-size: 13px; font-weight: 600; }
.card-body  { padding: 12px 14px; }
```

Card titles are sentence case, no uppercase. Right-aligned aside in the header (sub-text, 11px muted) is allowed.

## 8. Score bar grammar

```css
.sbar { display: flex; align-items: center; gap: 5px; }
.sbar-track { flex: 1; border-radius: 2px; background: var(--border); overflow: hidden; }
.sbar-fill  { height: 100%; border-radius: 2px; transition: width .3s; }
.sbar-val   { font-family: var(--font-mono); font-size: 10px; font-weight: 600; min-width: 20px; text-align: right; }
```

Track height: 4px standard, 6px for gauge rows (`.gauge-track`).

Color rules:
- `value >= 70` → `var(--pos)` fill.
- `value <= 35` → `var(--neg)` fill.
- otherwise → `var(--fg2)` (monochrome default).

## 9. Zone gauge / segmented bar

For Altman Z zones, GARP zones, confidence ladders. Reference structure:

```html
<div class="zone-gauge">
  <div class="zone-gauge-track">
    <div class="zone zone-negative" style="flex: 1.81;"></div>
    <div class="zone zone-warning" style="flex: 1.18;"></div>
    <div class="zone zone-positive" style="flex: 2.01;"></div>
  </div>
  <div class="zone-gauge-marker" style="left: 65.2%"></div>
  <div class="zone-gauge-labels">
    <span>1.81</span><span>2.99</span><span>5.0</span>
  </div>
</div>
```

Track: 6–8px tall. Marker: 2px wide vertical line in `var(--fg1)`. Boundaries: mono 10px below the track.

## 10. Sensitivity heatmap

Per-cell oklch interpolation (canonical formula from `20-claude-design-handoff.md`):

```javascript
const pct = (v - min) / (max - min);
const isBase = (rowG === baseG && colIdx === baseWaccIdx);
const bg = isBase
  ? "oklch(0.94 .04 260 / .55)"
  : `oklch(${0.55 + pct*0.18} ${0.04 + pct*0.14} ${pct >= 0.5 ? 165 : 25} / ${0.08 + pct*0.30})`;
```

Base case cell: primary outline (`1.5px solid var(--primary)`), weight 700, color `var(--pri-dim)`.
Cell padding: `7px 10px` (same as standard table).

## 11. Motion / animation

**Default: minimal animations.** The page must feel like a Bloomberg terminal — live, responsive, no decoration.

Allowed:
- Score bar fill width: 300ms (`transition: width .3s` in `.sbar-fill`).
- Mode pill / sidebar item hover: 100–150ms (`transition: all .15s` in `.mode-pill`, `transition: background .1s` in `.stock-item`).
- Tab change: instant (no fade). Tab underline change is instant.
- Button hover: 100ms (`transition: all .1s`).
- Universe row hover: 100ms.

Forbidden:
- Bounce, spring, parallax, page transitions.
- Number animation (counting up). Numbers appear instantly.
- Toast slide-ins (use plain banner replacement).

## 12. Focus / accessibility

- Focus ring: 2px outline, `var(--primary)`, offset 2px. Visible on all interactive elements.
- Keyboard navigation: `Tab` cycles through universe rows then tab nav then card actions.
- All chips, badges, and color-only signals also carry text or icons.
- All interactive elements have `aria-label` when not text-only.
- Tables use `<th scope="col">`.
- Numeric values use `tabular-nums` font-variant.

## 13. Scrollbar styling

```css
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: oklch(0.78 .01 250); border-radius: 3px; }
.dark ::-webkit-scrollbar-thumb { background: oklch(0.32 .01 250); }
```

## 14. Tailwind config additions

```javascript
// frontend/tailwind.config.js (additions)
module.exports = {
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      fontSize: {
        "xs":   ["10px", { lineHeight: "14px" }],
        "sm":   ["11px", { lineHeight: "15px" }],
        "base": ["12px", { lineHeight: "16px" }],
        "md":   ["13px", { lineHeight: "18px" }],
        "lg":   ["14px", { lineHeight: "20px" }],
        "xl":   ["18px", { lineHeight: "22px" }],
        "2xl":  ["22px", { lineHeight: "26px" }],
      },
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        card: "var(--card)",
        primary: "var(--primary)",
        "primary-fg": "var(--primary-fg)",
        "pri-dim": "var(--pri-dim)",
        "muted-fg": "var(--muted-fg)",
        bg2: "var(--bg2)",
        bg3: "var(--bg3)",
        fg1: "var(--fg1)",
        fg2: "var(--fg2)",
        fg3: "var(--fg3)",
        border: "var(--border)",
        line: "var(--line)",
        pos: "var(--pos)",
        neg: "var(--neg)",
        success: "var(--success)",
      },
      borderRadius: {
        DEFAULT: "var(--radius)",
      },
    },
  },
}
```

## 15. Migration from legacy CSS

The existing `signal-fund-*` and related classes in `frontend/components/strategy/signal-fundamental-view.tsx` and elsewhere must be replaced. Plan:

1. Add tokens above to global CSS / Tailwind config.
2. Build new components per `18-ui-component-library.md` using the new tokens.
3. Replace `signal-fund-*` usages.
4. Delete legacy classes after all replacements land.

This is coordinated through phases in `14-implementation-roadmap.md`. Each phase ships behind `NEXT_PUBLIC_FUNDAMENTALS_V2_UI=true`.

## 16. Verification

After implementation:
- Visual diff: render the prototype `Signals Redesign.html` in a browser (one time, for reference), screenshot the fundamental view tabs, then compare against the React implementation. Should be pixel-equivalent at desktop 1280×800 viewport.
- Page renders cleanly at 12px body without horizontal scroll on a 1280×800 laptop.
- Accessibility audit (Lighthouse): ≥ 95 on `/signals?mode=fundamental`.
- Switching between light/dark themes (via Tweaks panel) flips all oklch variables consistently.
- All numeric values use `tabular-nums` (no jitter when values update).

## See also

- [20-claude-design-handoff.md](20-claude-design-handoff.md) — canonical UI spec extracted from the Claude Design prototype.
- [15-ui-goals-and-design.md](15-ui-goals-and-design.md) — page layout + tab content.
- [18-ui-component-library.md](18-ui-component-library.md) — per-component implementation specs.
- [19-ui-tear-sheet-spec.md](19-ui-tear-sheet-spec.md) — print stylesheet rules.
