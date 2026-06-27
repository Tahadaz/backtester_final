# UI goals and design — full rebuild specification

> **Aligned with [20-claude-design-handoff.md](20-claude-design-handoff.md), which is the authoritative source.** This document is the page-level architecture and per-tab content specification. Codex implements per this spec using:
> - Design tokens from [17-ui-design-language.md](17-ui-design-language.md).
> - Components from [18-ui-component-library.md](18-ui-component-library.md).
> - Tear-sheet/PDF from [19-ui-tear-sheet-spec.md](19-ui-tear-sheet-spec.md).
> - Screens (Magic Formula / Altman / EVA / PEG / regression-adj) from [16-institutional-screens.md](16-institutional-screens.md) — integrated into Qualité + Comparables tabs (NOT a standalone Screens tab).

## Audit of the current state

Today's surface lives at `frontend/components/strategy/signal-fundamental-view.tsx` (882 lines, reached via `/fundamentals` → `/signals?mode=fundamental`). Specific failures:

1. `ValuationTable` (lines 325–369): 6 columns, no row expansion, no methodology surfaced, no inputs visible, no step trace. The engine's `inputs`, `outputs`, `methodology`, `warnings` are completely unrendered — the analyst sees a fair value with no idea how it was derived.
2. `DetailStrip` (lines 210–259): 4 generic KPI tiles. No recommendation, no conviction, no target price, no analyst attribution.
3. `SummaryTab` (lines 261–323): Flat boxes; pillars not clickable; no DuPont decomposition.
4. `SensitivityHeatmap`: minimal, no current-assumption marker.
5. No football-field chart.
6. No scenario cards.
7. No catalysts list, no risk register.
8. No DuPont decomposition.
9. No comparables table.
10. No estimations table.
11. Generic admin-panel CSS — far below institutional standard.
12. Universe table: 4 columns only, no recommendation, no revision arrow, no BUY/HOLD/SELL filter.

The page is functional but reads as a hobby project. **The rebuild keeps the backend engine untouched; everything here is frontend-only, ships behind `NEXT_PUBLIC_FUNDAMENTALS_V2_UI=true`.**

## Page topology

```
/signals  (single unified route)
├── Header (top, persistent)
├── ModeSwitcher (3 mode pills: Technical / Fundamental / Quantitative)
└── Active view based on ?mode= query param
    ├── TechnicalView (existing flow, refactored to fit in mode shell)
    ├── FundamentalView (rebuilt — this doc's focus)
    └── QuantitativeView (leaderboard sidebar + 4 tabs)
```

**Main navigation** (top of app, all routes):
`Tableau de Bord · Data · Signals · Strategy · Backtest · Analytics · Glossaire`

No standalone "Fundamentals" or "Quantitative" nav items — both live inside Signals.

**Legacy redirects:**
- `/fundamentals` → 301 → `/signals?mode=fundamental` (already in place).
- `/fundamentals?symbol=ATW` → preserves symbol in redirect.

## Mode switcher

See [20-claude-design-handoff.md](20-claude-design-handoff.md) §"Mode switcher" for the full CSS spec. 3 pills:

| Pill | Icon | Title | Description |
|---|---|---|---|
| Technical | `Zap` (lucide) | Analyse Technique | Indicateurs · WFO · Backtest |
| Fundamental | `BarChart3` (lucide) | Analyse Fondamentale | DCF · Qualité · Comparables |
| Quantitative | `TrendingUp` (lucide) | Analyse Quantitative | Stat-arb · Facteurs · Macro |

URL state: `mode=technical|fundamental|quantitative`. Default = `technical`.

## Fundamental view layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  HEADER (route-level)                                                          │
├──────────────────────────────────────────────────────────────────────────────┤
│  MODE SWITCHER  [⚡ Technical] [📊 Fundamental·active] [📈 Quantitative]      │
├──────────────┬───────────────────────────────────────────────────────────────┤
│  UNIVERSE     │ RESEARCH TICKET (research-ticket-grade header)                │
│  SCREEN       │   ATW  ATTIJARIWAFA BANK · Banques · Maroc · Large Cap · MAD │
│  (380px)      │   Cours actuel │ Objectif 12M │ Upside │ Mkt Cap  | RECO=BUY │
│               │                                                  | ●●●●○    │
│               ├───────────────────────────────────────────────────────────────┤
│  Coverage     │  TABS                                                          │
│  · 13 titres  │  [Thèse·active] [Valorisation] [Qualité & ROE]                │
│  FY 2025E     │  [Estimations] [Comparables]                                   │
│               ├───────────────────────────────────────────────────────────────┤
│  [Search...]  │                                                                │
│  Tous|B|H|S   │  Tab body                                                      │
│  Sort ▾       │                                                                │
│               │                                                                │
│  TICKER REC ▲ │                                                                │
│  ATW   BUY ▲  │                                                                │
│  IAM   BUY =  │                                                                │
│  BMCE  HLD =  │                                                                │
│  ATH   BUY ▼  │                                                                │
│  CIH   SEL ▼  │                                                                │
│  ...          │                                                                │
│               │                                                                │
│  Footer:      │                                                                │
│  4 Buy · 6    │                                                                │
│  Hold · 2 Sell│                                                                │
│  Upside moy.  │                                                                │
│  +5.8%        │                                                                │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

Important deltas vs my earlier 7-tab proposal:
- **5 tabs only** (was 7). "Lineage" removed (provenance moves into Estimations / metadata on each card). "Assumptions" merged into Valorisation (DCF assumptions card). "Screens" removed as a tab; screens integrated into Qualité + Comparables.
- **No permanent right-rail Ensemble sidebar.** The ensemble info lives inside the Valorisation tab.
- **Universe panel is 380px wide** (not 240px).

## Tab 1 — Thèse

Investment thesis + scenarios + catalysts + risks.

### Content layout

```
gap3 (12px vertical gap between blocks)
├── Thesis card (eyebrow + 2 prose paragraphs)
├── Scenario block:
│   ├── Section label: "Scénarios à 12 mois — Distribution probabiliste"
│   ├── <ScenarioCards> grid (Bear / Base / Bull)
│   └── Expected price line: "E[Prix] = 158×0.25 + 202×0.55 + 248×0.20 = 200.2 MAD"
├── Catalysts card:
│   ├── Card header: "Catalyseurs à venir" + "Prochains 6 mois"
│   └── 5 <CatalystList> items (date, title, desc, importance chip)
└── Risks card:
    ├── Card header: "Principaux risques"
    └── 5 <RiskRegister> rows (category, text, 3-bar meter, direction)
```

### Component refs

- `<ThesisCard>` — sub-component used inside this tab only. Eyebrow (10px UPPER 800 letter-spacing .12em color pri-dim) + 2 paragraphs (13px line-height 1.6, second paragraph muted).
- `<ScenarioCards>` — see [18-ui-component-library.md](18-ui-component-library.md).
- `<CatalystList>` — see [18-ui-component-library.md](18-ui-component-library.md).
- `<RiskRegister>` — see [18-ui-component-library.md](18-ui-component-library.md).

### Data binding

| UI element | Backend field |
|---|---|
| Thesis prose | `detail.thesis_paragraphs` (NEW — array of strings; default: generated from snapshot via `frontend/lib/fundamentals/thesis-generator.ts`) |
| Scenario prices | `detail.scenarios.bear.fair_value_base`, `.base.*`, `.bull.*` |
| Scenario probabilities | `detail.scenarios.bear.probability` (DEFAULT 0.25 / 0.55 / 0.20 — overridable per symbol via assumption set) |
| Scenario drivers | `detail.scenarios.bear.drivers` (NEW — list of strings; default: derived from sensitivity worst-direction inputs) |
| Catalysts | `detail.catalysts` (NEW — array of `{date, title, desc, importance}`) |
| Risks | `detail.risks` (NEW — array of `{category, text, severity: 1|2|3, direction}`) |

NEW fields require backend support. For an initial release, the catalysts and risks can be hard-coded per symbol (manual JSON file in `services/api/app/seed_data/fundamental_catalysts.json`) until a proper editing surface exists. See [20-claude-design-handoff.md](20-claude-design-handoff.md) §"Backend additions required".

## Tab 2 — Valorisation (the user's chief pain point — solved here)

Football field chart + per-method drill-down + DCF assumptions + sensitivity heatmap.

### Content layout

```
gap3
├── Scenario seg toggle + WACC/g/Currency status strip
│   [Bear · Base·active · Bull]              WACC 9.2% · g 3.5% · MAD
├── Football Field card:
│   ├── Card header: "Football Field — Fourchette de valorisation par méthode"
│   │   right aside: "Cours 180.9 · Cible 201.5"
│   └── <FootballField> SVG chart
├── Détail par méthode card (the user's drill-down):
│   ├── Card header: "Détail par méthode de valorisation"
│   └── Table: each row is a <MethodologyCardRow>:
│       collapsed: Méthode | Bear | Base | Bull | Upside | Conf | Poids
│       expanded:  ↳ inputs / step-by-step / outputs / warnings / cross-check
├── DCF assumptions card:
│   ├── Card header: "Hypothèses clés — DCF FCFF"
│   └── g4 grid of <Stat> tiles (WACC, terminal g, EBITDA margin, CAPEX/CA, tax rate, BFR/CA, horizon, FCFF base)
└── Sensitivity heatmap card:
    ├── Card header: "Sensibilité — Juste valeur (WACC × Croissance terminale)"
    └── <SensitivityHeatmap> grid (6 rows g × 6 cols WACC, oklch coloration, base cell outlined)
        Footer: base case note + Δ sensitivity headlines
```

### Football field chart

Reference: SVG with method ranges + current/target lines. Full spec in [20-claude-design-handoff.md](20-claude-design-handoff.md) §"Football Field SVG".

Methods displayed (top to bottom):
1. DCF · FCFF
2. DCF · FCFE
3. DDM (3 phases)
4. Revenu résiduel
5. Multiples justif.
6. Comparables MENA
7. **Ensemble pondéré** (highlighted: wider bar, larger dot, weight 1.00, primary color)

### Per-method drill-down (user's specific request)

The "Détail par méthode" table is **not just a flat table**. Each method row is an instance of `<MethodologyCardRow>` that:

1. **Collapsed state** — renders as a normal row: Method | Bear | Base | Bull | Upside | Confiance | Poids.
2. **Click chevron / row** → expands inline below to reveal the 6-section `<MethodologyCard>` body:
   - **Methodology prose** (the engine's `result.methodology` string, e.g. "FCFF discounted cash flow with fading growth and net-debt bridge to equity value.")
   - **Inputs used** — table of every input the model pulled, with value + source label (e.g. `fcf_start: 1200 MAD M`, source `reported_free_cash_flow`).
   - **Step-by-step computation** — model-specific `<ComputationStepsTable>` (e.g. for FCFF DCF: 8 numbered steps showing fade growth → projected FCF → terminal → equity → per share).
   - **Outputs persisted** — `projected_fcf` array as a horizontal mini-table; `implied_prices` dict as a breakdown table.
   - **Warnings** — translated to plain language via `warning-dictionary.ts`.
   - **Cross-check** — comparison with adjacent models or sustainable growth.

This is the deep-dive the user explicitly requested: *"click on different valuation methods like DCF or DDM to see details on how we got the results and a deep dive on each methodology"*.

The expanded card uses the spec in [18-ui-component-library.md](18-ui-component-library.md) `<MethodologyCard>`. The collapsed row is a new sub-component `<MethodologyCardRow>` that wraps it.

### DCF assumptions card

8 stat tiles in a `g4` (4-column) grid:
1. WACC `9.2%` — sub: "Beta 0.78 · Rf 3.8% · MRP 6.5%"
2. Croissance terminale `3.5%` — sub: "vs inflation LT ~2.5%"
3. Marge EBITDA stable `51%` — sub: "vs moy. 5 ans 50.4%"
4. CAPEX / CA stable `17%` — sub: "5G + fibre · 2026-2030"
5. Taux IS effectif `31%` — sub: "Maroc · pas de niche"
6. BFR / CA `-4%` — sub: "Cycle court négatif"
7. Horizon explicite `5 ans` — sub: "2026E → 2030E"
8. FCFF base 2026E `6.1 Bn` — sub: "vs 5.8 Bn 2025E"

Values come from the symbol's active assumption set + computed metrics. The "edit assumptions" action is reachable via a small "Modifier" link top-right of the card — opens a modal `<AssumptionEditor>` (per the previous spec, retained).

### Sensitivity heatmap

6 rows × 6 cols. Default axes:
- Rows: g terminal ∈ {2.5, 3.0, 3.2, 3.5, 3.7, 4.0}%
- Cols: WACC ∈ {8.0, 8.5, 9.0, 9.2, 9.5, 10.0}%

Cell coloring: oklch interpolation per [20-claude-design-handoff.md](20-claude-design-handoff.md) §"Sensitivity heatmap". Base case cell (g=3.5%, WACC=9.2% in the canonical example) outlined with primary border, bold, color `--pri-dim`.

Footer line: left = base case note, right = Δ sensitivity headlines (e.g. "Δ -50bps WACC ≈ +5%").

## Tab 3 — Qualité & ROE

DuPont decomposition + peer comparisons + Altman Z + EVA cards (the screens that fit here per Addendum #3).

### Content layout

```
gap3
├── 4-KPI grid:
│   Score global · Score qualité · Score santé · Score croiss.
│   (uses <Stat> tiles)
├── DuPont card:
│   ├── Card header: "Décomposition DuPont — ROE 2024A"
│   │   aside: "ROE = Marge nette × Rotation actifs × Levier financier"
│   └── <DuPontDecomposition>:
│       [Marge nette] × [Rotation actifs] × [Levier financier] = [ROE composite]
│       Each box: value + peer comparison + small bar fill
│       Result box (rightmost): tinted, primary border
│       "Lecture :" interpretive paragraph below
├── Qualité vs peers card:
│   ├── Card header: "Indicateurs qualité — Comparaison peers"
│   └── 8 <PeerComparisonBar> rows:
│       ROIC, Marge opér., FCF conversion, Couverture intérêts,
│       Dette nette / EBITDA, Capex / CA, Accruals ratio, Dilution actions
│       Each row: label | bar with peer mark | own value | peer value
├── Distress probability card (Altman Z) — NEW (Addendum #3 integration):
│   ├── Card header: "Risque de défaut — Altman Z-score"
│   └── <ZoneGauge> safe/grey/distress with current Z marker
│       + 5-factor components table
│       + zone label (Safe / Grey / Distress)
└── Création de valeur économique card (EVA) — NEW (Addendum #3 integration):
    ├── Card header: "Création de valeur — ROIC vs WACC"
    └── Dual horizontal bars: ROIC bar (top) + WACC bar (bottom)
        + spread label (ROIC - WACC = +1.99% → EVA MAD 278 M)
        + EVA margin sub-text
```

### Component refs

- `<DuPontDecomposition>` — see [20-claude-design-handoff.md](20-claude-design-handoff.md) and [18-ui-component-library.md](18-ui-component-library.md).
- `<PeerComparisonBar>` — see [18-ui-component-library.md](18-ui-component-library.md).
- `<ZoneGauge>` (for Altman) — see [18-ui-component-library.md](18-ui-component-library.md).
- `<EvaSpreadVisualization>` — new component for the ROIC vs WACC dual bars.

### Data binding

| UI element | Backend field |
|---|---|
| 4 KPI scores | `detail.snapshot.scores.{overall|quality|health|growth}` |
| DuPont components | `detail.snapshot.diagnostics.dupont.{net_margin, asset_turnover, equity_multiplier, reported_roe, roe_bridge_gap, score}` |
| Peer comparison values | `detail.snapshot.diagnostics.metric_breakdown[metric]` (per S8 fix) |
| Altman Z | `detail.snapshot.diagnostics.screens.altman_z` (from [16-institutional-screens.md](16-institutional-screens.md)) |
| EVA | `detail.snapshot.diagnostics.screens.eva` (from [16-institutional-screens.md](16-institutional-screens.md)) |

## Tab 4 — Estimations

6-year P&L (3A + 3E) + consensus vs house.

### Content layout

```
gap3
├── P&L card:
│   ├── Card header: "P&L détaillé — Réel + Estimations 2025–2027"
│   │   aside (legend): chip [Actuel] chip [Estimé]
│   └── <EstimationsTable>:
│       Columns: Métrique | 2022A | 2023A | 2024A | 2025E | 2026E | 2027E
│       Estimated columns shaded oklch(0.94 .04 260 / .25) in header, .18 in body
│       Rows: main metric rows + indented sub-rows (margin/growth) in muted, color by sign
└── Consensus vs House card:
    ├── Card header: "Consensus marché vs Maison · FY 2026E"
    └── Table: Métrique | Consensus (n=14) | Maison | Écart | Position
        Position: "Au-dessus" (green) or "En-dessous" (red)
```

### Data binding

| UI element | Backend field |
|---|---|
| Annual rows | `detail.annual_metrics` (existing) — pivoted into the table shape by frontend |
| Forecast rows | `detail.forecast_metrics` (NEW — array of `{year, metric, value}` for E years) |
| Consensus | `detail.consensus.{revenue, ebitda, ...}` (NEW — optional external feed) |
| House | Derived from `detail.forecast_metrics` for FY 2026E |
| Écart | `(house - consensus) / consensus` formatted as ±% |

NEW fields: forecast_metrics + consensus. For initial release, forecast_metrics can be generated by extrapolating from the latest 3-year CAGR (with the same fade logic as the DCF). Consensus can be hard-coded per symbol via a manual JSON seed.

## Tab 5 — Comparables

Peer table + relative valuation tiles + screen integrations.

### Content layout

```
gap3
├── Comparables table card:
│   ├── Card header: "Comparables — Multiples sectoriels (Télécoms MENA + global)"
│   │   aside: "NTM forward · oklch coloration vs médiane"
│   └── <ComparablesTable>:
│       Columns: Ticker | Nom | Pays | Mkt Cap (Bn$) | P/E | EV/EBITDA | P/B | ROE | Div Yield | g CA
│       Rows: 8 peers + 1 median row
│       Self-row tinted oklch(0.94 .04 260 / .22), ticker pri-dim
│       Median row: bg2, italic
│       Cell colors: vs median per metric (good/bad based on lower-is-better flag)
├── 3-tile g3 grid (Relative valuation):
│   ├── Décote vs médiane (P/E)
│   ├── Décote vs historique 5 ans
│   └── Rendement total estimé
│   Each tile: lbl (10px UPPER 700 fg3) + val (mono 22px 700 colored) + sub (11px muted)
├── Score Magic Formula card (Addendum #3 integration):
│   ├── Card header: "Magic Formula — Greenblatt"
│   └── Two bars: ROC bar + Earnings Yield bar with sector ranks
│       + composite Magic Formula score
├── PEG / GARP card (Addendum #3 integration):
│   ├── Card header: "PEG · GARP"
│   └── Zone chart with stock's position marker, PEG value, zone label
└── Regression-adjusted multiples card (Addendum #3 integration):
    ├── Card header: "Multiples ajustés par régression"
    └── Per-multiple divergent bar chart (richness z-score) + coefficient inspector
```

### Component refs

- `<ComparablesTable>` — see [18-ui-component-library.md](18-ui-component-library.md).
- `<RelativeValuationTiles>` — 3-tile grid.
- `<MagicFormulaCard>` — from Addendum #3 integration here.
- `<PegGarpCard>` — from Addendum #3.
- `<RegressionAdjustedCard>` — from Addendum #3.

### Data binding

| UI element | Backend field |
|---|---|
| Peers list | `detail.peers` (NEW — array of peer symbols + their key multiples) OR build live from the cohort in the universe via `relative_multiples` peer_stats |
| Median row | Computed cohort median (already in `relative_multiples.peer_stats`) |
| Décote vs médiane | `(own_pe / median_pe) - 1` |
| Décote vs historique 5 ans | `(current_pe / trailing_5y_avg_pe) - 1` (NEW — requires historical multiples in snapshot) |
| Rendement total estimé | `upside_pct + dividend_yield` |
| Magic Formula score | `detail.snapshot.diagnostics.screens.magic_formula.score` |
| PEG | `detail.snapshot.diagnostics.screens.peg_garp.peg` |
| Regression richness | `detail.snapshot.diagnostics.screens.regression_adj.regression_richness` |

## Universe screen specification

Full spec in [20-claude-design-handoff.md](20-claude-design-handoff.md) §"Universe screen". Summary:

- Width: 380px.
- Header: coverage count + FY label, search input, filter pills (Tous/Buy/Hold/Sell), sort dropdown.
- Table: 5 columns (Titre / Rec / Score / Upside / Rev).
- Each row clickable → selects symbol → updates `selected_symbol` URL param.
- Sort options: Upside (default), Score, Conviction, Mkt Cap.
- Bottom summary bar: "{n_buy} Buy · {n_hold} Hold · {n_sell} Sell" + avg upside.

## Research ticket specification

Full spec in [20-claude-design-handoff.md](20-claude-design-handoff.md) §"Research Ticket header".

Replaces the current top KPI strip. Carries:
- Symbol large (22px weight 700) + company name (14px fg2) + meta chip (sector · country · cap class · currency).
- 4 price blocks: Cours actuel / Objectif 12M / Upside / Capitalisation.
- Recommendation card (BUY/HOLD/SELL): large 22px, weight 800, colored per oklch palette.
- Conviction meter: 5 dots.
- Analyst attribution: "Analyste · ..." + version stamp.

## Per-tab interaction flows

### Switching scenario

Each scenario seg in Valorisation triggers a new fetch:
```
GET /fundamentals/stocks/{symbol}?scenario={bear|base|bull}
```

The page updates the football field, methods table, DCF assumptions card, sensitivity heatmap with the scenario-specific assumption set's values. Bear scenario applies `SCENARIO_DEFAULT_OVERRIDES.bear`, etc.

### Switching tab

URL state: `fund_tab=thesis|valorisation|qualite|estimations|comparables`. Default: `thesis`. Persists in URL for shareable links.

### Click on universe row

URL state: `symbol=ATW`. Triggers detail fetch. Tab resets to `thesis` (per Claude Design conversation behavior).

### Expand a methodology row in Valorisation

Inline expansion within the table. URL state: `expanded_method=fcff_dcf` (so a sharable URL can pre-expand the model). Multiple expanded methods allowed simultaneously.

### Edit assumptions

"Modifier" link in DCF assumptions card → opens `<AssumptionEditor>` modal. Save triggers `PUT /fundamentals/stocks/{symbol}/assumptions/{scenario}` and refreshes detail.

### Compare mode (optional, future)

Not in the Claude Design prototype. Deferred to a future iteration.

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Cmd/Ctrl + K` | Focus universe search |
| `Cmd/Ctrl + P` | Print tear-sheet (per [19-ui-tear-sheet-spec.md](19-ui-tear-sheet-spec.md)) |
| `Esc` | Close any open modal/popover |
| `↑` `↓` | Navigate universe rows |
| `Enter` | Select highlighted universe row |
| `1`-`5` | Jump to tab 1-5 (Thèse..Comparables) |
| `B` `O` `U` | Switch scenario Bear / b(O)se (base) / b(U)ll |
| `T` `F` `Q` | Switch mode Technical / Fundamental / Quantitative |
| `R` | Refresh data |

## Loading states

- Universe panel: skeleton rows 24px tall.
- Research ticket: skeleton header (4 KPI blocks + rec card placeholder).
- Tab body: skeleton matched to the tab's primary content (e.g. football field skeleton on Valorisation).
- Use SWR's `keepPreviousData` so stale data renders while fresh loads.

## Empty states

- No symbol selected: detail area shows centered prompt.
- Symbol has no snapshot: tab body shows "No fundamental data available — upload workbook" (admin link to data page).
- Symbol has `confidence=unavailable` on all models: Valorisation tab shows "All models excluded — view Qualité tab for input diagnostics".

## Error states

- API error: red banner at top of tab body with retry button.
- Stale snapshot (>90 days): amber banner "Snapshot age N days — consider re-importing".

## Responsive behavior

| Breakpoint | Layout |
|---|---|
| ≥ 1280px | Full layout: 380px universe + flex detail (the design target) |
| 1024–1279px | Universe collapsible to icon strip (toggle button) |
| 768–1023px | Universe drawer (slide-in from left) + full-width detail |
| < 768px | Mobile placeholder: "Best viewed on desktop" |

Mobile optimization is deferred.

## Performance

- Universe render: < 100ms for up to 200 symbols.
- Tab switch: instant (no API call required — fetched data is per-symbol-per-scenario).
- Detail fetch debounced 200ms.
- SWR `dedupingInterval: 60_000` on universe + detail.

## Feature flag

Full v2 UI ships behind `NEXT_PUBLIC_FUNDAMENTALS_V2_UI=true`. When off, redirect to legacy page. When on, the new layout renders.

## Implementation phases

See [14-implementation-roadmap.md](14-implementation-roadmap.md) Phase F (D5.0–D5.9) for the 10-PR sequenced plan.

## Verification

After all D5.x PRs:

1. `/signals` loads with mode switcher; default mode = Technical.
2. Click "Analyse Fondamentale" → URL = `/signals?mode=fundamental`.
3. Universe screen: 5-column table with BUY/HOLD/SELL filter chips; bottom summary visible.
4. Click any symbol → Research Ticket populates with all 4 price blocks + recommendation + conviction meter.
5. Thèse tab: thesis prose + 3 scenario cards (Bear 25% / Base 55% / Bull 20%) + catalyst timeline + risk register.
6. Valorisation tab: football field chart + methods table; clicking any method row reveals inputs / step-by-step / outputs / warnings.
7. Qualité tab: DuPont decomposition (4 boxes Marge × Rotation × Levier = ROE) + peer comparison bars + Altman Z zone gauge + EVA dual-bar.
8. Estimations tab: 6-year P&L (3A + 3E) with shaded estimated columns; consensus vs house table below.
9. Comparables tab: peer table with relative coloration + 3 valuation tiles + Magic Formula / PEG / regression-adj cards.
10. Switch scenario `Bear` → Valorisation refreshes with bear values.
11. Toggle Tweaks panel → dark mode flips, sidebar width changes apply.
12. Visual diff: side-by-side with the prototype `C:/tmp/sr-design/final-app/project/Signals Redesign.html` rendered in a browser → pixel-equivalent (excluding the data values, which are real not synthetic).

## See also

- [20-claude-design-handoff.md](20-claude-design-handoff.md) — canonical UI spec with CSS reference.
- [17-ui-design-language.md](17-ui-design-language.md) — design tokens.
- [18-ui-component-library.md](18-ui-component-library.md) — per-component specs.
- [19-ui-tear-sheet-spec.md](19-ui-tear-sheet-spec.md) — print/PDF.
- [16-institutional-screens.md](16-institutional-screens.md) — backend for screens.
- [14-implementation-roadmap.md](14-implementation-roadmap.md) — sequencing.
## Quality tab - Integrity block

The Quality tab should render the backend `integrity` field from `GET /fundamentals/stocks/{symbol}` or `GET /fundamentals/stocks/{symbol}/integrity`.

- Show three fixed rows: BS balance, Cash tie-out, NI link.
- Status chips: `pass` green, `warn` amber, `fail` red, `unavailable` and `derived` grey.
- On hover/focus, show the `inputs` map and signed `delta` / `rel_delta`.
- If `overall_status` is not `pass`, show the applied `confidence_haircut` because valuation confidence already includes it.
