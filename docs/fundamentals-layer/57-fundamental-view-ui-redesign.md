# Brief 57 — Fundamental view UI redesign (signals page)

**Status:** spec approved, implementation via Sonnet subagents, phase-by-phase.
**Scope:** `frontend/` only. No API/backend changes. No new npm dependencies.
**Author intent:** restructure the fundamental analysis view so a trader gets the
call at a glance and can drill into every detail — matching how sell-side research
notes and desk dashboards (Bloomberg ANR/DES/EE/RV) organize the same content —
while making every tab readable by a junior trader through glossary links and
plain-language verdicts.

---

## 0. Ground rules (apply to every phase)

1. **Nothing is deleted except the three items in §1.3.** Every data element,
   chart, table, and control in the current view must exist in the new view.
   Each phase ends with the content-preservation checklist for the tabs it touches.
2. **No new libraries.** Stack is fixed: Next 16, React 19, Tailwind v4 (tokens in
   `frontend/app/globals.css`), shadcn/Radix primitives in `components/ui/`,
   Recharts 2.15 for any new chart, lucide-react icons, SWR for data.
3. **All UI copy in French with proper accents** ("Thèse", "Hypothèses",
   "Données au", "Synthèse", "Valorisation", "Qualité"). Fix existing unaccented
   strings when a component is touched. Keep number formatting via the existing
   `fmt*` helpers (they move to `lib/formatters.ts` in Phase 0).
4. **Preserve all `data-capture="…"` attributes** (`tearsheet`, `scenarios`,
   `wacc-buildup`, `sensitivity`, `valuation-models`, `scoring`, `diagnostics`) —
   external capture tooling depends on them. When a block moves, the attribute
   moves with it.
5. **Preserve URL params** (`scenario`, `fund_tab`, `fund_horizon`,
   `fund_benchmark`, `fund_excluded_models`, `fund_weight_mode`) and the
   localStorage keys (`fundamental_valuation_exclusions_by_symbol`,
   `justified_multiple_ratio_mask`, `relative_multiple_ratio_mask`). Legacy
   `fund_tab` values must keep working via the mapping in §3.2.
6. **Verification per phase:** `npm run lint` and `npm run build` must pass in
   `frontend/`. Then start `npm run dev` and load
   `http://localhost:3000/signals?view=fundamental` (fundamental view of the
   signals page), click through every tab for at least 2 symbols (one bank,
   one industrial — e.g. ATW and one non-financial), confirm no console errors
   and the phase checklist.

---

## 1. Current state (inventory)

Everything lives in `frontend/components/strategy/signal-fundamental-view.tsx`
(6,915 lines, ~90 components). Layout: horizontal `ResizablePanelGroup`
(`UniverseScreen` list left ≈28% | detail right), the detail side itself a
**vertical** `ResizablePanelGroup` (`ResearchTicket` header pane | tab pane).
Six tabs: `thesis`, `valuation` (with 8 sub-tabs: Synthèse + 7 models),
`estimates`, `comparables`, `assumptions`, `quality`.

### 1.1 Component inventory (all preserved unless listed in §1.3)

| Area | Components (current line refs) |
|---|---|
| Shell | `SignalFundamentalView` (6520), `UniverseScreen` (1729), `ResearchTicket` (1911) |
| Thesis | `ThesisTab` (2167): thesis paragraph, scenario cards (`buildScenarios`), catalysts list, risks list |
| Valuation | `ValuationTab` (5141), `FootballField` (2581), `TriangulationBand` (own file), `ValuationMethodCard`/`Rows`, `DcfMethodView` + `DcfPvTable`/`DcfHistoryStrip`/`DcfTerminalBlock`/`DcfValueWaterfall`/`DcfCoherenceChips`, `CostOfCapitalBuildUp`, `ModelStoryPanel`, `SensitivityMatrix`/`SensitivityHeatmap`/`ModelSensitivityPanel`, `MultipleRatioSelectionPanel`, `ReverseDcfSummaryCells`/`DiagnosticTiles`, `AssumptionStrip`, `ModellingMapPanel`, `DecisionStrip`, `ValuationModelControls`, `SharedProjectionPanel` |
| Estimates | `EstimatesTab` (5979), `LegacyEstimateTable`, `ProjectionAssumptionEditor`, `GrowthDecompositionChart`, `FcfBridge`, `DriverEvidenceChart`, `MiniSeriesChart` |
| Comparables | `ComparablesTab` (6454), `ComparableBenchmarkPanel`, `ComparableFairValueTable`, `ComparableValuationTiles`/`Cells`, benchmark selector + `useComparableChoices` |
| Assumptions | `AssumptionsTab` (4600), `ValuePreview`, symbol-save + desk-save flows |
| Quality | `QualityTab` (5542), `DupontBox`, `ZoneGauge` + `ALTMAN_TERM_DEFS`, `PeerMetricRows`, `ScreenSummaryCard`, `ScreenWarningChips`/`ScreenUnavailable`, `CoverageRatingPanel`, `StatementEvidenceCard`, `ModelValueGrid` |
| Shared | `FundCard`, `StatTile`, `RecChip`, `ScoreChip`, `ScorePair`, `LoadingRows`, `StoryMetricGrid`, `StoryTable`, all `fmt*`/`as*` helpers, all constants (`MODEL_LABELS`, `MODEL_FORMULA_META`, `SEVERE_VALUATION_WARNINGS`, …) |

### 1.2 Known problems being fixed

- 6 tabs + 8 sub-tabs, with assumption editing duplicated across 3 tabs and
  comparables appearing twice.
- No decision-first landing view; evidence scattered.
- `ResearchTicket` uses a ResizeObserver + `--rt-scale` font-rescaling hack
  inside nested resizable panels → the shifting/cramped appearance.
- Hardcoded pseudo-content: catalysts ("T+30j…" identical for every stock),
  3 template risk rows, boilerplate thesis paragraph.
- Glossary (`lib/glossary.ts`, ~120 entries with a complete valuation cluster)
  is wired only inside the DCF drill-down (13 `GlossaryTerm` usages, lines
  ~3560–3810). Zero glossary coverage elsewhere; no entries for quality-screen
  terms (Altman, EVA, ROIC, DuPont, PEG, multiples…).
- Mixed FR/EN and missing accents; active tab resets on symbol switch.

### 1.3 The only deletions

1. Hardcoded catalysts rows and template risk rows in `ThesisTab` (the
   *sections* survive with real-data-or-empty-state behavior, §4.1.6).
2. The duplicate assumption-editing surfaces (editing keeps exactly one home,
   §4.3; other tabs show read-only values that link there).
3. The `--rt-scale` ResizeObserver mechanism + the vertical
   `ResizablePanelGroup` split (`signals-fundamental-detail-layout-v6`),
   replaced by the fixed header of §3.3. Delete the `--rt-scale` CSS block in
   `globals.css` when Phase 1 lands.

---

## 2. Target file structure (Phase 0)

Split the monolith **mechanically, zero behavior change**, into:

```
frontend/components/strategy/fundamental/
  index.tsx                 # SignalFundamentalView shell (exported name unchanged)
  research-ticket.tsx
  universe-screen.tsx
  tabs/
    synthese-tab.tsx        # Phase 2 (Phase 0: current ThesisTab lands here as-is)
    valuation-tab.tsx
    estimates-tab.tsx       # Phase 0: current EstimatesTab + AssumptionsTab both here
    quality-tab.tsx         # Phase 0: current ComparablesTab + QualityTab both here
  panels/
    dcf-method-view.tsx     # DcfMethodView + its sub-blocks
    sensitivity.tsx         # SensitivityMatrix/Heatmap/ModelSensitivityPanel
    comparables.tsx         # ComparableBenchmarkPanel/FairValueTable/Tiles + hooks
    cost-of-capital.tsx
    model-story.tsx
    coverage-rating.tsx
  shared/
    cards.tsx               # FundCard, StatTile, RecChip, ScoreChip, ScorePair, LoadingRows
    verdict-chip.tsx        # new in Phase 1 (§5.3)
    charts.tsx              # MiniSeriesChart, DriverEvidenceChart, GrowthDecompositionChart, FcfBridge, FootballField
  lib/
    constants.ts            # FUND_TABS, MODEL_ORDER, MODEL_LABELS, MODEL_FORMULA_META, masks, warning sets…
    formatters.ts           # fmt*, as*, clampValue, formatDate, scoreClass…
    view-models.ts          # buildComparablesView, comparableModelSummary, buildValuationSelectionSummary, sortValuationRows, valuation exclusion storage helpers
    types.ts                # DetailTab, Scenario, view-model interfaces
```

- `frontend/components/strategy/signal-fundamental-view.tsx` becomes a one-line
  re-export (`export { SignalFundamentalView } from "./fundamental"`) so
  `app/signals/page.tsx` is untouched; delete the old file body.
- Rule of thumb: files ≤ ~700 lines. No logic edits in Phase 0 — cut/paste +
  imports only. `npm run build` output must be functionally identical.

---

## 3. Target information architecture

### 3.1 Tabs: six → four

| # | id (`fund_tab`) | Label | Contents |
|---|---|---|---|
| 1 | `synthese` (default, omitted from URL) | **Synthèse** | decision-first landing (§4.1) |
| 2 | `valuation` | **Valorisation** | ensemble + model master-detail (§4.2) |
| 3 | `estimates` | **Estimations & Hypothèses** | forecasts + the single assumptions editor (§4.3) |
| 4 | `quality` | **Comparables & Qualité** | peer benchmarking + quality screens (§4.4) |

### 3.2 Legacy URL mapping (in `tabFromQuery`)

`thesis` → `synthese`; `assumptions` → `estimates`; `comparables` → `quality`;
unknown → `synthese`. Writing to the URL always uses the new ids (default
`synthese` written as `null`, preserving current behavior).

**Tab persistence:** `handleSelectSymbol` stops resetting `fund_tab` (keep
resetting `scenario`; keep the per-symbol exclusion seeding). Switching stock
while on Valorisation stays on Valorisation.

### 3.3 Shell layout

Keep the horizontal `ResizablePanelGroup` (universe left 28% / detail right 72%,
same min/max, same `autoSaveId`). The detail side becomes a plain flex column —
**no vertical resizable split**:

```
┌────────────┬──────────────────────────────────────────────┐
│ Universe   │ ResearchTicket (fixed-height header, §3.4)   │
│ list       ├──────────────────────────────────────────────┤
│ (existing, │ Tab bar: Synthèse·Valorisation·Estimations…  │
│ untouched) ├──────────────────────────────────────────────┤
│            │ Purpose line (one sentence, muted)           │
│            │ Tab body (scrollable, own scroll container)  │
└────────────┴──────────────────────────────────────────────┘
```

Keep existing error/empty states (`displayError`, liquidity-hidden warning,
"Sélectionnez un titre…"). Keep the `max-xl:block` stacked mobile behavior.

### 3.4 ResearchTicket redesign (Phase 1)

Delete the ResizeObserver/`--rt-scale`/density machinery entirely. New ticket:
fixed typography, CSS grid, `data-capture="tearsheet"` kept on the root.

- **Row 1 (identity):** `SYMBOL` (font-semibold, ~15px) · company name (muted) ·
  sector / région / devise as small chips · right-aligned dates caption
  ("Données au … · Valorisé le … · Cible …", 11px muted, `CalendarDays` icon).
- **Row 2 (KPI strip):** 4 stat tiles + recommendation card, one row,
  `grid-template-columns: repeat(4, minmax(0,1fr)) auto`, wrapping to 2×2+full
  below `xl`:
  1. *Cours actuel* — value 18px `tabular-nums`, sub "au {date}".
  2. *Objectif* — value in the existing blue accent
     `oklch(0.30 0.14 260)`; the **horizon toggle** (Trimestre/Semestre/Année,
     existing availability logic + disabled tooltip) renders as a 3-button
     segmented control inside this tile's header; sub shows the revision arrow
     + "révision haussière/baissière/inchangée".
  3. *Upside / Downside* — value colored `t-pos`/`t-neg`, sub "vs cours actuel".
  4. *Capitalisation* — sub "Free float … · ADV20 … MAD".
  - *Recommendation card* (right, ~150px): existing `recommendationClass`
    tinted card, label "Recommandation {scenario}", big rec value, conviction
    dots (1–5) — all as today, minus scaling.
- Height: content-driven, ~96–120px desktop; no clamps, no `calc(*var(--rt-scale))`.
- CSS: new classes in `globals.css` under a `/* research ticket v2 */` section;
  delete the old `.research-ticket` block.

---

## 4. Per-tab specification

Every tab starts with a **purpose line** — one muted sentence (12px) under the
tab bar answering "what question does this tab answer":

- Synthèse: « L'essentiel : la recommandation, ce qui la soutient, et ce qui pourrait la changer. »
- Valorisation: « Ce que valent les modèles par rapport au prix de marché, et comment la cible est construite. »
- Estimations & Hypothèses: « D'où viennent les prévisions, et les hypothèses que vous pouvez ajuster. »
- Comparables & Qualité: « Le titre face à ses pairs, et la solidité de ses fondamentaux. »

### 4.1 Synthèse (Phase 2) — replaces ThesisTab

Vertical stack, `fund-gap` spacing, in this order:

1. **Verdict strip** — a single row (wrap allowed) of `VerdictChip`s (§5.3),
   each chip deep-linking (`onClick` → `setActiveTab` + scroll target) to the
   section that owns it:
   - *Valorisation*: upside vs ensemble fair value → "Décoté de X%" / "Cher de X%" / "Proche de sa valeur" (thresholds: ≥+10% good, ≤−10% serious, else neutral) → links to Valorisation.
   - *Score Value* and *Score Qualité*: reuse `scoreClass` bands; label "Value 78 — élevé" → links to Comparables & Qualité.
   - *Altman Z*: zone → "Zone saine / grise / de fragilité" (good/warning/serious) → links to Qualité section.
   - *Création de valeur*: ROIC vs WACC (from the EVA screen; "non applicable (financier)" when `applicable === false`) → links to Qualité.
   - *Vs pairs*: median premium/discount on enabled multiples → "Décoté vs pairs / Prime vs pairs" → links to Comparables.
   - *Liquidité*: ADV20 vs `FUNDAMENTAL_LIQUIDITY_ADV20_THRESHOLD`.
   - Any chip whose input is null renders the neutral "Non renseigné" variant.
2. **Football field** — reuse `FootballField` (moved to `shared/charts.tsx`)
   showing per-model fair-value ranges, current-price line, ensemble fair-value
   line. Model names are `GlossaryTerm`s. Below it a one-line caption:
   « Fourchettes de juste valeur par modèle ; la ligne verticale est le cours actuel. »
3. **Scenario strip** — the existing `scn-grid` bear/base/bull cards
   (`data-capture="scenarios"` preserved), plus the probability-weighted value
   line. Unchanged content, moved here.
4. **Triangulation band** — `<TriangulationBand triangulation={detail.triangulation} />`
   (also shown on Valorisation; it is cheap and central to the story).
5. **Thèse d'investissement** — keep the generated paragraph (it is honest: it
   restates rec/target/upside) but drop the second filler paragraph; add the
   `RecChip` inline.
6. **Catalyseurs & Risques** — one `FundCard` with two columns.
   *Catalysts:* render **only** real data — if the API exposes earnings/report
   dates for the symbol use them; otherwise render the muted empty state
   « Aucun catalyseur renseigné pour ce titre. » **Never render the hardcoded
   T+30/60/90 rows.** *Risks:* derive only data-backed rows — Altman zone when
   `zone` present, severe valuation warnings present in
   `SEVERE_VALUATION_WARNINGS` ∩ detail warnings (reuse the FR labels from
   `ScreenWarningChips`), liquidity below threshold. Empty state: « Aucun
   signal de risque déclenché par les écrans. »

### 4.2 Valorisation (Phase 3)

Header row (unchanged logic, tidied):
- scenario segmented control (bear/base/bull) + the governance banner when ≠ base;
- WACC / g / devise caption (right-aligned, each term a `GlossaryTerm`);
- weight-mode toggle (`ic` / equal) with `ic-weighting` glossary link.

**Synthesis block** (always visible, replaces the "Synthèse" sub-tab):
`DecisionStrip`, selection summary tiles (fair value, low–high band, upside,
"N modèles inclus / M utilisables", weight source), `TriangulationBand`,
`FootballField` (same component instance pattern as Synthèse), and the
include/exclude model controls (`ValuationModelControls` with include-all /
exclude-all; `data-capture="valuation-models"` preserved).

**Model master-detail** (replaces the 7 model sub-tabs):
- Left rail (~230px, stacked buttons; on `<lg` it collapses to the existing
  horizontal pill row): one row per model in `MODEL_ORDER` order —
  model label (as `GlossaryTerm`), fair value, effective weight %, include
  switch, warning icon when severe warnings hit. Active row highlighted.
- Right panel: the **unchanged** existing per-model views — `DcfMethodView`
  (with `DcfPvTable`, history strip, terminal block, waterfall, coherence chips,
  `CostOfCapitalBuildUp` with `data-capture="wacc-buildup"`), `ModelStoryPanel`,
  `MultipleRatioSelectionPanel`, reverse-DCF tiles, comparable tiles, and
  `ModelSensitivityPanel` (`data-capture="sensitivity"`).
- **Assumptions become read-only here**: `AssumptionStrip` stays (display), the
  inline editors and Save buttons are removed; in their place one link-button
  « Ajuster les hypothèses → » that navigates to `estimates` (§4.3) and scrolls
  to the editor. The `assumptionDraft` prop plumbing into ValuationTab is
  removed (drafts still affect `visibleValuations` computed in the shell).

### 4.3 Estimations & Hypothèses (Phase 4) — merge of EstimatesTab + AssumptionsTab

Order (estimates first — they are the desk-first-class citizen):

1. **Prévisions** — existing EstimatesTab content: horizon-aware forecast
   tables (`LegacyEstimateTable`, projection views), `GrowthDecompositionChart`,
   `FcfBridge`, `DriverEvidenceChart`, `SharedProjectionPanel`. Column headers
   get `GlossaryTerm`s (fcff, fcfe, terminal-growth…).
2. **Hypothèses (éditeur unique)** — the AssumptionsTab machinery in full:
   grouped editable fields (`editableAssumptionKeys`), `ValuePreview`,
   historical-alias evidence, scenario context, and **both** save flows
   ("Enregistrer pour {symbol}" / "Enregistrer desk") with `isSaving`/
   `isDeskSaving` states and `saveError` display. `ProjectionAssumptionEditor`
   lives here. This is the only writable surface in the whole view.
   Anchor id `#assumptions-editor` for the deep-link from Valorisation.
3. **Carte de modélisation** — `ModellingMapPanel` + `CoverageRatingPanel`
   (which models are seeded/usable and why).

Unsaved-draft indicator: when `assumptionDraft` is non-empty, show a sticky thin
bar at the bottom of the tab body: « Hypothèses modifiées — non enregistrées »
+ the two save buttons + « Réinitialiser ».

### 4.4 Comparables & Qualité (Phase 5) — merge of ComparablesTab + QualityTab

Two anchored sections with a small in-tab section nav (two pill buttons that
scroll, not sub-tabs):

1. **Comparables** — benchmark selector (sector/index, existing
   `useComparableChoices`), `ComparableBenchmarkPanel`, peer table
   (`PeerMetricRows` / `ComparableFairValueTable`), metric tiles. Every metric
   header (P/E, P/B, P/S, EV/EBITDA, ROE, Dividend Yield, Revenue Growth) is a
   `GlossaryTerm`; each multiple gets a gap `VerdictChip` (« −23% vs pairs »,
   tone from `comparableGapTone`).
2. **Qualité & écrans** — existing QualityTab content unchanged in substance
   (`data-capture="scoring"` and `"diagnostics"` preserved): Value/Quality
   score pair with score bands, DuPont decomposition (`DupontBox` row), Altman
   `ZoneGauge` + `ALTMAN_TERM_DEFS` term table, EVA / value-creation panel,
   Magic Formula / PEG / regression screens (`ScreenSummaryCard`),
   `StatementEvidenceCard`, `ScreenWarningChips`. Additions: a `VerdictChip`
   next to each screen verdict (plain-language, §5.3) and `GlossaryTerm` on
   every screen name.

---

## 5. Design system rules

### 5.1 Tokens & typography

- Use only existing `globals.css` tokens and Tailwind theme colors —
  `t-pos`/`t-neg`, the blue accent `oklch(0.30 0.14 260)`, `text-muted-foreground`,
  `ring-line`, card surfaces. **No new hex/oklch literals** without adding a
  named token first.
- Numbers: always `tabular-nums` (`font-mono` where the ticket already does).
  Sizes: KPI values 18px, table/tile values 13px, labels 11px uppercase
  tracking-wide muted, purpose lines 12px.
- Spacing rhythm: 4/8/12/16px; cards `rounded-md border` on card surface —
  match `FundCard`. Section labels via existing `.fund-section-label`.
- Dark mode: the app uses `next-themes`; use semantic tokens only, never raw
  colors, so both themes work. Verify each phase in both themes.

### 5.2 Charts (dataviz rules)

- Recharts for anything new; keep `FootballField`'s existing implementation
  (extract, don't rewrite).
- One axis per chart, never dual-axis. Thin marks: 2px lines, bars with 4px
  rounded data-ends, 2px surface gap between adjacent fills.
- Color by job: series identity uses the existing categorical assignments
  already in the app (model colors in `FootballField` stay stable per model —
  color follows the entity, never rank or sort order). Status (good/warning/
  serious) uses the tones in §5.3 and is never reused for series identity.
- Text wears text tokens, never series color. Selective direct labels only —
  never a number on every point. Tooltips on hover for every plotted mark
  (Recharts `<Tooltip>` styled like the existing card tooltip).
- Grid/axes recessive: `ring-line` color, no axis lines heavier than 1px.

### 5.3 `VerdictChip` (new shared component, Phase 1)

```tsx
// shared/verdict-chip.tsx
type VerdictTone = "good" | "warning" | "serious" | "neutral"
function VerdictChip({ tone, label, glossaryId, onClick }: {
  tone: VerdictTone; label: string; glossaryId?: string; onClick?: () => void
})
```

- Pill: `inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium`.
- **Icon + text always, never color alone** (CVD rule): good → `CircleCheck`,
  warning → `AlertTriangle`, serious → `CircleAlert`, neutral → `Minus`.
- Tones map to existing semantic classes: good = the `t-pos` green family
  (border/text tinted, transparent-tint bg), serious = `t-neg` family,
  warning = the amber already used for warnings (`border-amber-300 bg-amber-50
  text-amber-900` + dark-mode equivalents via tokens), neutral = muted.
- When `glossaryId` present, render a trailing `GlossaryTerm iconOnly`.
- Clickable variant gets `hover:bg-…` and `cursor-pointer`, `role="button"`.

### 5.4 Tab bar

Keep the existing `.signal-fund-tabs` / `.signal-fund-tab` styling (underline
active state) — only the tab *list* changes. Purpose line sits directly under
it inside the scroll container.

---

## 6. Glossary work (Phase 1, blocking for Phases 2/5)

### 6.1 New entries in `frontend/lib/glossary.ts`

Follow the existing entry shape exactly (`id`, `title.{fr,en}`, `plain.{fr,en}`,
full definition fields, category — mirror the valuation cluster entries around
line 1355). Add, in a "Qualité & écrans" section:

`altman-z`, `eva`, `roic`, `roe`, `dupont`, `peg`, `magic-formula`,
`payout-ratio`, `free-float`, `beta`, `per`, `price-to-book`, `price-to-sales`,
`ev-ebitda`, `dividend-yield`, `sensitivity-grid`, `scenario-bear-base-bull`,
`conviction`, `upside`, `football-field`.

Each `plain.fr` must be genuinely plain-language (one or two sentences a junior
understands, e.g. altman-z: « Un score qui combine cinq ratios du bilan pour
estimer le risque de faillite : au-dessus de ~3 la société est en zone saine,
en dessous de ~1,8 en zone de fragilité. »). Verify the `/glossary` page renders
the new section.

### 6.2 Coverage rule

Every technical label rendered in the fundamental view — metric tile labels,
table column headers, model names, screen names, assumption field names — is
wrapped in `GlossaryTerm` when an entry exists. Sonnet must grep its own output:
a tab is done when the only un-linked technical terms are ones without entries
(and §6.1 should make that set empty for user-facing terms).

---

## 7. Implementation phases (one Sonnet task each, sequential)

Each phase = one focused subagent run; Fable reviews the diff + runs the
verification of §0.6 before the next phase starts. Commit per phase on the
current branch (`feature/forward-estimate-layer`) with message prefix
`feat(fundamental-ui):`.

| Phase | Scope | Acceptance (beyond lint/build/§0.6) |
|---|---|---|
| **0 — Split** | §2 file split, zero behavior change; old file becomes re-export | App renders identically (6 tabs still); no logic diffs — moves + imports only; each new file ≤ ~700 lines |
| **1 — Shell & ticket** | §3.1–3.4 tab merge (4 tabs, legacy mapping, persistence), new ResearchTicket, delete vertical split + `--rt-scale` CSS, `VerdictChip`, §6 glossary entries, purpose lines | Old deep-links (`fund_tab=thesis/assumptions/comparables`) land on the right tab; tab survives symbol switch; ticket has fixed type sizes at 1280/1536/1920px widths and stacks below `xl`; `/glossary` shows new section |
| **2 — Synthèse** | §4.1 | All 7 verdict chips render (or "Non renseigné"); chips navigate + scroll; football field + scenario cards + triangulation present; **zero hardcoded catalyst/risk rows anywhere in the codebase** (grep "T+30j") |
| **3 — Valorisation** | §4.2 master-detail; strip assumption editing from valuation | Every existing model view reachable; include/exclude + weight mode + exclusions localStorage/URL still work; sensitivity loads lazily as today; « Ajuster les hypothèses → » lands on the editor; content checklist: DcfPvTable, history strip, terminal block, waterfall, coherence chips, WACC build-up, model story, ratio masks, reverse-DCF tiles, sensitivity matrix+heatmap all present |
| **4 — Estimations & Hypothèses** | §4.3 merge, sticky draft bar | Both save flows work (symbol + desk) incl. error state; drafts still live-update valuation rows; content checklist: estimate tables, growth decomposition, FCF bridge, driver evidence, assumption editor with previews, modelling map, coverage rating |
| **5 — Comparables & Qualité** | §4.4 merge + chip/glossary sweep | Content checklist: benchmark selector, peer tables, fair-value-from-comps, Value/Quality scores, DuPont, Altman gauge + term table, EVA panel, Magic/PEG/regression screens, statement evidence, warning chips; every screen name and multiple header glossary-linked; both themes clean |

Post-phase-5 cleanup task: delete now-dead CSS classes from `globals.css`
(old ticket, sub-tab styles if unused), run `graphify update .`, and do a final
two-theme click-through of all 4 tabs × 3 symbols.

### Prompt skeleton for each Sonnet run

> Read `docs/fundamentals-layer/57-fundamental-view-ui-redesign.md` §0, §2/§3/§4
> (your phase's sections), §5, §6. Implement Phase N exactly. Do not touch other
> phases' scope. Ground rules §0 are binding — especially content preservation
> (§1.1 inventory) and no new dependencies. Finish with `npm run lint` and
> `npm run build` in `frontend/` and report the §7 acceptance checklist item by
> item.

---

## 8. Out of scope (explicitly)

- Backend/API changes (incl. adding a real catalysts endpoint — the UI ships
  with the empty state until one exists; tracked separately).
- `UniverseScreen` redesign (left list stays as-is this round).
- The non-fundamental tabs of the signals page.
- New charting beyond reusing/moving existing components.
