# Claude Design handoff — canonical UI specification

> **This document is the AUTHORITATIVE visual + topology spec for the Signals page rebuild.** It supersedes any earlier speculative UI doc where they diverge. Codex implements per this spec.

The user iterated this design with the Claude Design AI tool (claude.ai/design). The handoff bundle is preserved at `C:/tmp/sr-design/final-app/` and contains the prototype HTML/CSS/JSX, plus the design conversation transcript. The visual decisions in this file come directly from that handoff — do not re-derive or re-design them.

## Design intent (from the design conversation, verbatim)

1. **"The fact that there is a separate part for fundamental analysis is weird, it should be in the signal page, with a button switch or something like that to switch between technical and fundamental analysis."** → Unified `/signals` page with 3-mode switcher.

2. **"It should be largely improved... and there should be a switch for quantitative analysis too."** → Mode switcher carries 3 modes: Technical / Fundamental / Quantitative.

3. **"Improve only the analyse fondamental signal page to make it professional and better, and investment bank grade."** → The 5-tab fundamental view (Thèse / Valorisation / Qualité & ROE / Estimations / Comparables) is the deliverable.

4. **"I would really love to have even more details, like for example in the valorisation tab, I'd be able to click on the different valuation methods like DCF or DDM... to see details on how we got the results and a deep dive on each methodology used so that it can be easy to understand for anyone and for there to be a rigor and a high level details that are investment bank grade."** → The Valorisation tab combines a football-field chart with **per-method `<MethodologyCard>` drill-down** (the deep-dive component specified in `18-ui-component-library.md`).

## Page topology

```
/signals route
├── Header (top, persistent across all modes)
├── ModeSwitcher (just below header — 3 mode pills)
└── Active view (based on mode)
    ├── TechnicalView (existing flow, minor refactor)
    ├── FundamentalView ← THIS IS WHAT WE'RE BUILDING
    │   ├── UniverseScreen (left, 380px)
    │   └── DetailArea (flex 1)
    │       ├── ResearchTicket (header)
    │       └── Tabs: Thèse | Valorisation | Qualité & ROE | Estimations | Comparables
    └── QuantitativeView (leaderboard sidebar + 4 tabs)
```

**Routing:**
- `/signals?mode=technical` → TechnicalView
- `/signals?mode=fundamental` → FundamentalView
- `/signals?mode=quantitative` → QuantitativeView
- `/fundamentals` (legacy) → 301 redirect to `/signals?mode=fundamental` (already done)

**Main nav (top of app, all routes):** `Tableau de Bord · Data · Signals · Strategy · Backtest · Analytics · Glossaire`. Note: no "Fundamentals" entry — it lives inside Signals.

## Design tokens

### Fonts

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous" />
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet" />
```

Self-host in Next.js via `next/font/google`:
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

### Color palette (oklch)

```css
:root {
  /* Background / Surface */
  --background: oklch(0.975 0.002 250);
  --foreground: oklch(0.145 0.015 250);
  --card:       oklch(1 0 0);
  --bg2:        oklch(0.975 0.003 250);   /* slightly darker than background */
  --bg3:        oklch(0.945 0.006 250);   /* even darker — used for chips, hover */

  /* Foreground tiers */
  --fg1:        oklch(0.145 0.015 250);   /* primary text */
  --fg2:        oklch(0.43 0.01 250);     /* secondary text */
  --fg3:        oklch(0.60 0.01 250);     /* tertiary / muted */
  --muted-fg:   oklch(0.50 0.01 250);

  /* Accent / Primary */
  --primary:    oklch(0.42 0.14 260);     /* main interactive color (blue-violet) */
  --primary-fg: oklch(0.985 0 0);
  --pri-dim:    oklch(0.30 0.14 260);     /* darker variant for hover, active text */

  /* Semantic */
  --pos:        oklch(0.50 0.13 165);     /* green — positive, BUY, safe */
  --neg:        oklch(0.52 0.20 25);      /* red — negative, SELL, distress */
  --success:    oklch(0.60 0.15 165);

  /* Lines */
  --border:     oklch(0.91 0.005 250);
  --line:       oklch(0.91 0.005 250);

  /* Misc */
  --radius:     0.625rem;
  --sidebar-w:  240px;
}

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

### Tailwind config additions

```js
// frontend/tailwind.config.js
module.exports = {
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        card: "var(--card)",
        primary: "var(--primary)",
        "primary-fg": "var(--primary-fg)",
        "pri-dim": "var(--pri-dim)",
        "muted-fg": "var(--muted-fg)",
        border: "var(--border)",
        line: "var(--line)",
        bg2: "var(--bg2)",
        bg3: "var(--bg3)",
        fg1: "var(--fg1)",
        fg2: "var(--fg2)",
        fg3: "var(--fg3)",
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

## Mode switcher

CSS reference (from `Signals Redesign.html`):

```css
.mode-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--line);
  background: var(--card);
  flex-shrink: 0;
}
.mode-bar-label {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .09em;
  color: var(--fg3);
  margin-right: 4px;
}
.mode-pill {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 6px 14px 6px 8px;
  border: 1.5px solid var(--line);
  border-radius: 10px;
  background: transparent;
  color: var(--muted-fg);
  transition: all .15s;
  white-space: nowrap;
}
.mode-pill:hover {
  background: var(--bg3);
  color: var(--fg1);
}
.mode-pill.active {
  border-color: oklch(0.72 0.09 260);
  background: oklch(0.94 0.04 260 / .45);
  color: var(--pri-dim);
}
.mode-pill-icon {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg2);
  flex-shrink: 0;
  transition: all .15s;
}
.mode-pill.active .mode-pill-icon {
  background: var(--primary);
  color: var(--primary-fg);
}
.mode-pill-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  text-align: left;
}
.mode-pill-title {
  font-size: 12px;
  font-weight: 600;
  line-height: 1.2;
}
.mode-pill-desc {
  font-size: 10px;
  color: var(--fg3);
  line-height: 1.2;
}
.mode-pill.active .mode-pill-desc {
  color: oklch(0.45 0.10 260);
}
```

Three pills:

| Pill | Icon (lucide-react) | Title | Description |
|---|---|---|---|
| Technical | `Zap` (or ⚡) | Analyse Technique | Indicateurs · WFO · Backtest |
| Fundamental | `BarChart3` (or 📊) | Analyse Fondamentale | DCF · Qualité · Comparables |
| Quantitative | `TrendingUp` (or 📈) | Analyse Quantitative | Stat-arb · Facteurs · Macro |

## Fundamental view layout

```css
.fund-layout {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.fund-univ {
  width: 380px;                       /* fixed width */
  flex-shrink: 0;
  border-right: 1px solid var(--line);
  background: var(--bg2);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.fund-detail {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.fund-tabs {
  display: flex;
  border-bottom: 1px solid var(--line);
  background: var(--bg2);
  flex-shrink: 0;
}
.fund-tab {
  display: inline-flex;
  align-items: center;
  height: 36px;
  padding: 0 14px;
  font-size: 12px;
  font-weight: 500;
  color: var(--muted-fg);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all .1s;
}
.fund-tab.active {
  color: var(--fg1);
  border-bottom-color: var(--primary);
  background: var(--card);
}
.fund-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px;
}
```

## Research Ticket header

Replaces the current `DetailStrip`. Anchor structure:

```css
.research-ticket {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 24px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--line);
  background: var(--card);
  flex-shrink: 0;
}
.rt-left   { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.rt-name-row { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.rt-sym    { font-size: 22px; font-weight: 700; letter-spacing: -.02em; }
.rt-coname { font-size: 14px; color: var(--fg2); font-weight: 500; }
.rt-meta   { font-size: 11px; color: var(--muted-fg); }
.rt-meta strong { color: var(--fg2); font-weight: 600; }
.rt-prices { display: flex; gap: 26px; }
.rt-price-block .lbl { display: block; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: var(--muted-fg); margin-bottom: 2px; }
.rt-price-block .val { display: block; font-family: var(--font-mono); font-size: 18px; font-weight: 700; color: var(--fg1); line-height: 1.2; }
.rt-price-block .sub { display: block; font-size: 11px; color: var(--muted-fg); margin-top: 2px; }

.rt-right { display: flex; flex-direction: column; gap: 8px; min-width: 200px; padding-left: 24px; border-left: 1px solid var(--line); }
.rt-rec-card { padding: 10px 14px; border-radius: 8px; text-align: center; }
.rt-rec-card.buy  { background: oklch(0.96 .07 165 / .35); border: 1px solid oklch(0.78 .12 165); }
.rt-rec-card.hold { background: oklch(0.96 .04 80  / .35); border: 1px solid oklch(0.78 .10 80); }
.rt-rec-card.sell { background: oklch(0.95 .08 25  / .25); border: 1px solid oklch(0.75 .15 25); }
.rt-rec-lbl { font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .12em; color: var(--fg3); }
.rt-rec-val { font-size: 22px; font-weight: 800; letter-spacing: .04em; line-height: 1.1; margin-top: 2px; }
.rt-rec-val.buy  { color: oklch(0.34 .15 165); }
.rt-rec-val.hold { color: oklch(0.38 .12 80); }
.rt-rec-val.sell { color: oklch(0.40 .20 25); }
.rt-conviction { display: flex; align-items: center; gap: 4px; justify-content: center; margin-top: 4px; font-size: 10px; color: var(--fg3); }
.conv-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--border); }
.conv-dot.on { background: var(--fg1); }
```

**Content blocks (left to right within `rt-left.rt-prices`):**

| Label | Value | Sub |
|---|---|---|
| Cours actuel | `{current_price}` (mono 18) | "au 24 mai 2026" |
| Objectif 12M | `{target_price}` (mono 18, color `--pri-dim`) | "{rev_arrow} dernière révision {haussière/baissière/inchangée}" |
| Upside / Downside | `{upside_pct}` (mono 18, color pos/neg) | "vs cours actuel" |
| Capitalisation | `{market_cap_bn} Bn` (mono 18) | "Free float ~30%" |

**Recommendation card (right):**

```
RECOMMANDATION
 BUY  /  HOLD  /  SELL    (large 22px, weight 800)
Conviction
●●●●○   (5 dots, on=fg1, off=border)
```

Below the card: "Analyste · M. Bennani" + "v3.2 · 17/05" attribution (10px, fg3).

## Tab content references

The 5 tab contents are specified in `15-ui-goals-and-design.md` (overall structure) and `18-ui-component-library.md` (per-component specs). This doc carries the **canonical source extracts** for each visual.

### Football Field SVG (Valorisation tab — top card)

Mathematics for layout (from `sr-fundamental.jsx:93–153`):

```typescript
const W = 720, padL = 130, padR = 80;
const rowH = 30;
const H = methods.length * rowH + 70;
const allVals = methods.flatMap(m => [m.low, m.high]).concat([currentPrice, targetPrice]);
const minV = Math.min(...allVals) * 0.94;
const maxV = Math.max(...allVals) * 1.06;
const x = (v) => padL + ((v - minV) / (maxV - minV)) * (W - padL - padR);
```

Per-row visual (in SVG):
- Method label: `text-anchor=end`, x=padL−10, y=cy+4, font-size 11, weight 700 if `method === "Ensemble pondéré"` else 500.
- Range bar: `<line>` from x(low) to x(high), stroke="var(--primary)" (ensemble) or "oklch(0.62 .08 250)" (other), stroke-width 12 vs 9, stroke-linecap=round, opacity 0.7 vs 0.45.
- Mid-point dot: `<circle>` cx=x(mid) cy=cy, r=5 (ensemble) or 4, fill=bar color, stroke=card 1.5px.
- Low/high labels at endpoints: mono 10px, fg3.

Current price line: vertical dashed (stroke-dasharray="4 3") `--neg`, label "CP · {price}" at y=14.
Target price line: vertical solid `--pos` stroke-width 2, label "Cible · {price}" at y=H-10.
X-axis ticks: 5 evenly-spaced, mono 9px, fg3, at y=H-22.

### Scenario assumptions expander (Valorisation tab)

Each bear/base/bull scenario block includes a compact `Hypotheses` expander directly below its valuation summary. The expander shows the resolved scalar assumptions returned by the API, not only the analyst-entered override payload:

- Source: `FundamentalStockDetailOut.assumption_provenance[scenario][key]`.
- Value column: resolved numeric value from `/fundamentals/{symbol}/assumptions/{scenario}` or the selected scenario's detail payload.
- Provenance chip per key:
  - `default` -> `defaut` chip, neutral `bg2` surface.
  - `scenario` -> `scenario` chip, primary-tinted surface.
  - `symbol` -> `personnalise` chip, `--pos` outline when the override improves value and `--neg` outline when it tightens value.
- Edit button: small icon+text button in the expander header. It opens a numeric form with every key from `DEFAULT_ASSUMPTIONS`; placeholders show the engine default, and current values prefill from the resolved scenario.
- Save target: `PUT /fundamentals/{symbol}/assumptions/{scenario}/override` with `{ overrides, note }`.
- Clear target: `DELETE /fundamentals/{symbol}/assumptions/{scenario}/override`.

The UI should not send `created_by`; the backend fills it from the authenticated principal.

### Scenario cards (Thèse tab)

```css
.scn-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.scn-card {
  padding: 14px 16px;
  border-radius: var(--radius);
  border: 1px solid var(--line);
  background: var(--card);
  display: flex;
  flex-direction: column;
  gap: 6px;
  position: relative;
  overflow: hidden;
}
.scn-card.base { border-color: oklch(0.72 .09 260); background: linear-gradient(180deg, oklch(0.94 .04 260 / .25), var(--card) 60%); }
.scn-card.bull { background: linear-gradient(180deg, oklch(0.96 .07 165 / .22), var(--card) 60%); }
.scn-card.bear { background: linear-gradient(180deg, oklch(0.95 .08 25 / .15), var(--card) 60%); }
.scn-hdr { display: flex; justify-content: space-between; align-items: center; }
.scn-lbl { font-size: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: .12em; }
.scn-lbl.bull { color: oklch(0.36 .15 165); }
.scn-lbl.base { color: oklch(0.30 .14 260); }
.scn-lbl.bear { color: oklch(0.42 .20 25); }
.scn-prob { font-size: 10px; color: var(--muted-fg); font-weight: 500; }
.scn-price { font-family: var(--font-mono); font-size: 22px; font-weight: 700; line-height: 1.1; }
.scn-up { font-family: var(--font-mono); font-size: 12px; font-weight: 600; }
.scn-drivers { font-size: 11px; color: var(--fg2); margin-top: 6px; line-height: 1.5; }
```

Structure per card:
```
[BEAR · 25%]              P=0.25     ← scn-hdr
158 MAD                              ← scn-price
-12.7%                               ← scn-up
• Régulation 5G défavorable (-50bps)
• Concurrence accrue d'Inwi
• Dégradation FX MAD/USD             ← scn-drivers list
```

Default probabilities and price targets come from the engine's scenario assumption sets (bear/base/bull). The bottom line "E[Prix] = ... = **200.2 MAD** · ≈ objectif central" is computed live: `sum(scenarios[s].price × scenarios[s].probability)`.

### Catalysts list (Thèse tab — third card)

```css
.cat-item {
  display: grid;
  grid-template-columns: 80px 1fr auto;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
  align-items: start;
}
.cat-item:last-child { border-bottom: none; }
.cat-date  { font-family: var(--font-mono); font-size: 11px; font-weight: 600; color: var(--fg2); }
.cat-title { font-size: 12px; font-weight: 600; color: var(--fg1); margin-bottom: 2px; }
.cat-desc  { font-size: 11px; color: var(--muted-fg); }
.cat-imp   { font-size: 10px; font-weight: 700; text-transform: uppercase; padding: 2px 6px; border-radius: 3px; align-self: start; }
.cat-imp.high   { background: oklch(0.96 .07 165 / .35); color: oklch(0.34 .15 165); }
.cat-imp.medium { background: oklch(0.55 .01 250 / .10); color: var(--fg2); }
.cat-imp.low    { background: oklch(0.55 .01 250 / .06); color: var(--fg3); }
```

Importance chip displays "Élevé" / "Modéré" / "Faible" based on `high|medium|low`.

### Risk register (Thèse tab — fourth card)

```css
.risk-row {
  display: grid;
  grid-template-columns: 110px 1fr 60px 70px;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--line);
  align-items: center;
}
.risk-cat   { font-size: 11px; font-weight: 600; color: var(--fg2); }
.risk-text  { font-size: 11px; color: var(--fg2); line-height: 1.5; }
.risk-meter { display: flex; gap: 2px; }
.risk-bar   { width: 6px; height: 14px; background: var(--bg3); border-radius: 1px; }
.risk-bar.on.l { background: oklch(0.65 .12 80); }   /* low severity = yellow-ish */
.risk-bar.on.m { background: oklch(0.62 .14 50); }   /* medium = orange */
.risk-bar.on.h { background: oklch(0.55 .18 25); }   /* high = red */
```

Each row: category (small text) | description text | 3-bar severity meter | direction tag (e.g. "Baissier" in red 10px weight 700).

### DuPont decomposition (Qualité tab)

```css
.dp-row { display: flex; align-items: center; gap: 12px; padding: 12px 4px; }
.dp-box { flex: 1; padding: 14px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--bg2); display: flex; flex-direction: column; gap: 4px; }
.dp-box.result { background: oklch(0.94 .04 260 / .25); border-color: oklch(0.72 .09 260); }
.dp-lbl  { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: var(--fg3); }
.dp-val  { font-family: var(--font-mono); font-size: 22px; font-weight: 700; color: var(--fg1); }
.dp-box.result .dp-val { color: var(--pri-dim); }
.dp-peer { font-size: 10px; color: var(--muted-fg); }
.dp-bar-bg   { height: 4px; background: var(--bg3); border-radius: 2px; overflow: hidden; margin-top: 4px; }
.dp-bar-fill { height: 100%; border-radius: 2px; }
.dp-op   { font-size: 22px; color: var(--fg3); font-weight: 300; font-family: var(--font-mono); }
```

Layout pattern:
```
[Marge nette]  ×  [Rotation actifs]  ×  [Levier financier]  =  [ROE composite]
24.6%             0.72×                 1.85×                  32.8%
Peers MENA: ...   Peers MENA: ...       Peers MENA: ...        Peers MENA: ...
▓▓▓▓▓░░░░░       ▓▓▓░░░░░░░            ▓▓░░░░░░░░             ▓▓▓▓▓▓▓░░░
```

Result box is tinted with `oklch(0.94 .04 260 / .25)` background and primary border. Value uses `--pri-dim`.

Below the 4-box row: a "Lecture :" interpretive paragraph in `bg2` card with `border` and `1px solid var(--line)`, padding 10px 14px, font-size 11px, line-height 1.5, color `var(--fg2)`. The strong "Lecture :" prefix is `var(--fg1)`.

### Peer comparison bar (Qualité tab — second card)

```css
.peer-bar-wrap { display: flex; align-items: center; gap: 8px; }
.peer-bar      { flex: 1; height: 6px; background: var(--bg3); border-radius: 3px; position: relative; overflow: visible; }
.peer-bar-fill { height: 100%; border-radius: 3px; }
.peer-bar-mark { position: absolute; top: -3px; width: 2px; height: 12px; background: var(--fg1); }
```

Row layout: `grid-template-columns: 160px 1fr 70px 70px` — label / bar wrapper / own value (right-aligned, color-coded) / peer value (small, fg3).

Bar fill color rules:
- `dir === "pos"` → `var(--pos)` (target above peer median = good)
- `dir === "neg"` → `var(--neg)` (target above peer median = bad — e.g. accruals, dilution)
- `dir === "neu"` → `var(--primary)`

Peer marker (vertical line) sits at the peer-median position with opacity 0.4.

### Sensitivity heatmap (Valorisation tab — last card)

Cell coloring formula (from `sr-fundamental.jsx:418–424`):

```typescript
const min = 164, max = 235;                            // domain of fair values in the grid
const pct = (v - min) / (max - min);
const isBase = (rowG === "3.5%" && colIdx === 3);     // base-case cell (g=3.5%, WACC=9.2%)
const bg = isBase
  ? "oklch(0.94 .04 260 / .55)"
  : `oklch(${0.55 + pct*0.18} ${0.04 + pct*0.14} ${pct >= 0.5 ? 165 : 25} / ${0.08 + pct*0.30})`;
```

So:
- Low fair-value cells (pct < 0.5) → red hue (25), lower L, lower C, lower opacity.
- High fair-value cells (pct > 0.5) → green hue (165), higher L, higher C, higher opacity.
- Base case cell: primary-tinted background with outline (`1.5px solid var(--primary)`), weight 700, color `var(--pri-dim)`.

Grid: rows = g values (4.0%, 3.7%, 3.5%, 3.2%, 3.0%, 2.5%); columns = WACC values (8.0%, 8.5%, 9.0%, 9.2%, 9.5%, 10.0%).

Footer: "Cellule encadrée : hypothèses base case (g=3.5%, WACC=9.2%) → FV ensemble **201.5 MAD**" left + "Δ -50bps WACC ≈ +5% · Δ +50bps g ≈ +4%" right.

### Estimations table (Estimations tab)

Years: `["2022A", "2023A", "2024A", "2025E", "2026E", "2027E"]`. The `E` suffix triggers the blue tint.

Header cell style:
```css
th {
  background: years[i].endsWith("E") ? "oklch(0.94 .04 260 / .25)" : undefined;
  color: years[i].endsWith("E") ? "var(--pri-dim)" : undefined;
}
```

Body cell style for estimated years:
```css
td {
  background: years[i].endsWith("E") ? "oklch(0.94 .04 260 / .18)" : undefined;
}
```

Row structure: main metric rows interleaved with **sub-rows** (margin / growth). Sub-rows:
- Padding-left: 22px (indented).
- Font-size: 11px (vs 12px main rows).
- Color: starts with `+` → `var(--pos)`; starts with `-` → `var(--neg)`; else `var(--fg2)`.
- Weight: 500 (vs 700 for main rows).

Legend at top-right of card header: 2 chips "Actuel" (bg2 swatch) and "Estimé" (`oklch(0.94 .04 260 / .35)` swatch).

### Comparables table (Comparables tab)

Row tinting rules:
- Self-row (the target symbol): `background: oklch(0.94 .04 260 / .22)`, `font-weight: 600`, ticker color `var(--pri-dim)`.
- Median row: `background: var(--bg2)`, italic, color `var(--fg3)`.
- Others: default.

Per-cell coloring (vs median, computed live):

```typescript
function cell(val, baseline, lower="bad", fmt) {
  if (val == null) return /* "—" */;
  const formatted = fmt === "pct" ? `${(val*100).toFixed(1)}%` : `${val.toFixed(1)}${fmt === "x" ? "×" : ""}`;
  if (baseline == null) return /* default */;
  const diff = (val - baseline) / baseline;
  const good = lower === "bad" ? diff > 0 : diff < 0;
  const col = Math.abs(diff) < 0.05
    ? "var(--fg1)"
    : good ? "var(--pos)" : "var(--neg)";
  // For valuation multiples (PE, EV/EBITDA, P/B), lower is good → lower="bad"
  // For ROE, dividend yield, growth, higher is good → lower="good"
  return <td style={{ color: col, fontWeight: Math.abs(diff) > 0.1 ? 700 : 500 }}>{formatted}</td>;
}
```

### Relative valuation tiles (Comparables tab — bottom)

Three tiles in a `g3` grid. Each tile:

```css
.card {
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--card);
}
.tile-lbl { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; color: var(--fg3); margin-bottom: 6px; }
.tile-val { font-family: var(--font-mono); font-size: 22px; font-weight: 700; color: var(--pos);  /* or --neg depending on metric */ }
.tile-sub { font-size: 11px; color: var(--muted-fg); margin-top: 4px; }
```

Tiles:
1. **Décote vs médiane (P/E)** — sign convention: positive % = premium to peers (color: `--pos` if growth-justified, else `--neg`).
2. **Décote vs historique 5 ans** — current PE vs trailing 5y average PE. Negative = currently cheap.
3. **Rendement total estimé** — `upside_pct + dividend_yield`, color always `--pos` for positive.

## Universe screen (left column, 380px)

Header (`fund-univ-hdr`): coverage count + FY label, search input with icon, BUY/HOLD/SELL filter pills (segmented control), sort dropdown.

Table columns:

| Header | Width | Content |
|---|---|---|
| Titre | 74px | Symbol (mono 11 bold) on first line; sector (9px fg3, truncated) on second line |
| Rec. | 56px (right-aligned) | BUY/HOLD/SELL chip with color-coded background |
| Score | 42px (right-aligned) | `<ScoreChip>` — mono 11 bold, color by score |
| Upside | 60px (right-aligned) | `+14.7%` mono 700, color pos/neg |
| Rev | 32px (center) | `▲` (up, pos green), `▼` (down, neg red), `—` (flat, fg3) |

Active row (selected symbol): tinted `background: oklch(0.94 .04 260 / .22)`, `font-weight: 600`, ticker `--pri-dim`.

Bottom summary bar (`8px 12px`, `border-top`, `background: var(--card)`, `font-size: 10px`, `color: var(--fg3)`):
- Left: `{n_buy} Buy · {n_hold} Hold · {n_sell} Sell` (Buy/Sell colored)
- Right: `Upside moy. +X.X%` (positive avg colored pos)

## Backend additions required

The research overlay introduces fields not currently in the API. Add to `services/api/app/schemas/fundamentals.py` and the corresponding Pydantic + TS types:

| Field on `FundamentalUniverseRow` & `FundamentalStockDetail` | Type | Source |
|---|---|---|
| `recommendation` | `"BUY" \| "HOLD" \| "SELL"` | Rule: upside_pct > 0.12 AND confidence in {high, medium} → BUY; upside_pct < -0.10 AND confidence in {high, medium} → SELL; else HOLD |
| `target_price` | `number \| null` | Default = `ensemble.fair_value_base`; can be analyst-overridden later |
| `conviction` | `int (1..5)` | `round(confidence_score × usable_model_count / 7 × 5)`, clamped to [1, 5] |
| `revision_direction` | `"up" \| "down" \| "="` | Compare current `target_price` vs previous import's `target_price`; threshold ±2% → `=` |
| `analyst` | `string \| null` | For now: literal `"Système quantitatif"`. Future: manual override per symbol. |
| `as_of_date` | ISO date | `ensemble.computed_at` formatted as French long date for UI ("au 24 mai 2026") |
| `free_float_pct` | `number \| null` | Optional metadata; if absent show "~" or omit |

These derivations live in `services/api/app/services/fundamentals.py` as helpers `derive_recommendation()`, `derive_conviction()`, `derive_revision_direction()`. Document the rule thresholds in `08-assumptions-and-defaults.md`.

## Component → file mapping

For Codex's implementation:

| Claude Design source | Repo file (to be created) |
|---|---|
| `Signals Redesign.html` CSS variables | `frontend/styles/fundamentals.css` (or Tailwind globals + arbitrary values) |
| `sr-app.jsx` shell + mode state | `frontend/app/signals/page.tsx` |
| `sr-app.jsx` TweaksPanel | `frontend/components/shell/tweaks-panel.tsx` |
| `sr-components.jsx` Header | `frontend/components/shell/header.tsx` |
| `sr-components.jsx` ModeSwitcher | `frontend/components/signals/mode-switcher.tsx` |
| `sr-fundamental.jsx` UniverseScreen | `frontend/components/signals/fundamental/universe-screen.tsx` |
| `sr-fundamental.jsx` ResearchTicket | `frontend/components/signals/fundamental/research-ticket.tsx` |
| `sr-fundamental.jsx` ThèseTab | `frontend/components/signals/fundamental/thesis-tab.tsx` |
| `sr-fundamental.jsx` ValorisationTab | `frontend/components/signals/fundamental/valorisation-tab.tsx` |
| `sr-fundamental.jsx` QualitéTab | `frontend/components/signals/fundamental/qualite-tab.tsx` |
| `sr-fundamental.jsx` EstimationsTab | `frontend/components/signals/fundamental/estimations-tab.tsx` |
| `sr-fundamental.jsx` ComparablesTab | `frontend/components/signals/fundamental/comparables-tab.tsx` |
| `sr-fundamental.jsx` FootballField | `frontend/components/signals/fundamental/football-field.tsx` |
| `sr-fundamental.jsx` ScenarioCards | `frontend/components/signals/fundamental/scenario-cards.tsx` |
| `sr-fundamental.jsx` CatalystList | `frontend/components/signals/fundamental/catalyst-list.tsx` |
| `sr-fundamental.jsx` RiskRegister | `frontend/components/signals/fundamental/risk-register.tsx` |
| `sr-fundamental.jsx` DuPont decomposition | `frontend/components/signals/fundamental/dupont-decomposition.tsx` |
| `sr-fundamental.jsx` PeerComparisonBar | `frontend/components/signals/fundamental/peer-comparison-bar.tsx` |
| `sr-fundamental.jsx` SensitivityHeatmap | `frontend/components/signals/fundamental/sensitivity-heatmap.tsx` |
| `sr-fundamental.jsx` Comparables table + tiles | `frontend/components/signals/fundamental/comparables-table.tsx` |
| `sr-technical.jsx` TechnicalView | `frontend/components/signals/technical/index.tsx` (refactor of existing) |
| `sr-quantitative.jsx` QuantitativeView | `frontend/components/signals/quantitative/index.tsx` |

## How Codex should use this document

1. Read this file in full before touching the UI.
2. Cross-reference each visual element with the prototype source at `C:/tmp/sr-design/final-app/project/`. The prototype is the visual source of truth.
3. Do not render the HTML prototype in a browser unless explicitly asked. All dimensions, colors, layout rules are in the source code or in this document.
4. The implementation language is **TypeScript + React** (Next.js App Router). The prototype uses Babel-standalone + React 18 UMD — that's a prototyping shortcut, not the target architecture.
5. Where this document is silent, fall back to `17-ui-design-language.md` for design tokens, `18-ui-component-library.md` for component contracts, `15-ui-goals-and-design.md` for tab content, `16-institutional-screens.md` for the 5 screens.

## See also

- [15-ui-goals-and-design.md](15-ui-goals-and-design.md) — page layout + tab content specifications.
- [17-ui-design-language.md](17-ui-design-language.md) — design tokens (now aligned with this handoff).
- [18-ui-component-library.md](18-ui-component-library.md) — per-component implementation contracts.
- [16-institutional-screens.md](16-institutional-screens.md) — backend specs for Magic Formula / PEG / Altman / EVA / regression-adjusted, with UI integration into Qualité + Comparables tabs.
- [14-implementation-roadmap.md](14-implementation-roadmap.md) — Phase F sequencing.
- Bundle location: `C:/tmp/sr-design/final-app/` (extracted from the Claude Design handoff).
## Workflow additions implemented in backend

- These tab: backend supports current thesis, append-only history, edit/save by posting a new current row, tombstone delete, and invalidation-condition chips via `/fundamentals/stocks/{symbol}/thesis`.
- Valorisation tab: `EnsembleOut.sensitivity_grids` can carry default WACC x terminal-growth and WACC x growth-cap heatmaps; assumptions expose provenance through `/fundamentals/stocks/{symbol}/assumptions/{scenario}`.
- Qualite tab: `integrity` and `trend` are additive fields on the stock detail response. The integrity block shows BS balance, cash tie-out, and NI link checks; trend chips use `on_track`, `watch`, `behind`, or `insufficient_data`.
- Calendrier: coverage-wide catalyst list is available at `/fundamentals/calendar`; per-symbol catalysts are available at `/fundamentals/stocks/{symbol}/catalysts`.
- Print artefacts: tear sheet, IC memo, and morning note are available as server-rendered HTML endpoints documented in `19-ui-tear-sheet-spec.md`.
