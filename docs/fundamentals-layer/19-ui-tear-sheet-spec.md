# Tear-sheet and PDF export specification

> Print stylesheet and PDF export contract for the fundamentals page. Allows the analyst to produce a 1-page institutional-grade summary to email to clients or include in research deliverables.

## Goals

1. **One-page A4** rendering with all the information an analyst needs to defend a fair value to a client.
2. **No UI chrome** — no universe, no tab nav, no ensemble sidebar in print.
3. **Print typography** — slightly larger than screen body (14px instead of 12px) for paper readability.
4. **Monochrome by default** — colors only for genuine signals (positive/negative/warning chips), no chrome colors.
5. **No page breaks mid-section** — `page-break-inside: avoid` on every block.

## Triggers

- Keyboard: `Cmd/Ctrl + P` → native print dialog → activates `@media print` stylesheet.
- Button: "Print" in top ribbon → same as above.
- Button: "Export PDF" in top ribbon → renders `<TearSheet>` to a hidden iframe, captures as PDF via `@react-pdf/renderer` or browser print-to-PDF.

## Layout — A4 portrait

A4 = 210mm × 297mm. With 12mm margins on all sides: usable area ~186mm × 273mm.

```
┌────────────────────────────────────────────────────────────────────────┐
│  ATW  ATTIJARIWAFA BANK                                FY 2024 · MAD   │  ← 28mm
│  Banques · MASI · 12 days since import                                  │
├────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ENSEMBLE FAIR VALUE                            VALUATION VERDICT       │  ← 40mm
│  MAD 312                                        Current: MAD 380         │
│  band MC 282–340  ·  model dispersion 224–355   Upside −18%              │
│  ensemble confidence 0.81                       Recommendation: review   │
│                                                                          │
│  ●●●●●●●●●●○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○○ │
│  MAD 200   ●     ●  ●●●   ●   current        MAD 400                    │
│           Rel  Just RI Mc          DDM                                   │
│           240  295 312 305         285                                   │
│                                                                          │
├────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  PILLAR SCORES                                  ACCOUNTING DIAGNOSTICS  │  ← 60mm
│                                                                          │
│  Overall      72  ▓▓▓▓▓▓▓▓░░  6/6 covered      DuPont gap    0.32%      │
│  Value        52  ▓▓▓▓▓░░░░░  sector            Piotroski    66.7        │
│  Quality      72  ▓▓▓▓▓▓▓░░░  sector            Accrual q.   77.1        │
│  Growth       77  ▓▓▓▓▓▓▓▓░░  sector            Altman Z     3.26 safe   │
│  Risk         73  ▓▓▓▓▓▓▓░░░  sector            ROIC spread  +1.99%      │
│  Cash flow    70  ▓▓▓▓▓▓▓░░░  sector            EVA          MAD 278 M   │
│  Health (BS)  68  ▓▓▓▓▓▓▓░░░  sector                                     │
│                                                                          │
├────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  TOP 3 WEIGHTED VALUATION MODELS                                        │  ← 90mm
│                                                                          │
│  Residual income (32%, high)        Fair MAD 320  ·  Spread fade ROE→COE│
│    inputs: book MAD 211, ROE 14%, COE 10.5%, fade 5y                    │
│    method: book + PV(ROE−COE)×book over fade horizon                    │
│                                                                          │
│  Justified multiples (27%, high)    Fair MAD 295  ·  Justified PB+PE    │
│    inputs: ROE 14%, payout 60%, growth 4.3%, COE 10.5%                  │
│    justified PB = 1.57 → implied MAD 330                                 │
│    justified PE = 10.10 → implied MAD 261                                │
│    median MAD 295                                                        │
│                                                                          │
│  DDM (25%, high)                    Fair MAD 285  ·  Gordon dividend    │
│    inputs: dividend MAD 7.98, sustainable g 2.0%, COE 10.5%             │
│    method: D × (1+g) / (COE − terminal_g)                               │
│                                                                          │
├────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  REVERSE DCF — WHAT MARKET BELIEVES                                     │  ← 30mm
│                                                                          │
│  Implied perpetual growth: 3.61%   (at WACC 8.51%)                      │
│                                                                          │
│  vs Terminal growth      3.0%      slightly above → OK                  │
│  vs Sustainable g        6.0%      BELOW → market is pessimistic        │
│  vs Long-term GDP+inf.   5.0%      below trend                          │
│                                                                          │
│  Reading: market is more conservative than fundamentals warrant.        │
│                                                                          │
├────────────────────────────────────────────────────────────────────────┤
│  Generated by {app_name} v{version}        {timestamp}                  │  ← 15mm
│  This is not investment advice. Methodology in docs/fundamentals-layer/. │
└────────────────────────────────────────────────────────────────────────┘
```

Total content ~263mm; 10mm safety margin retained.

## Implementation

### Approach: `@media print` stylesheet

Primary implementation. The existing page renders with `display: none` on chrome elements via a print stylesheet; a hidden `<TearSheet>` becomes visible.

```html
<!-- In the fundamentals page layout -->
<main class="fundamentals-page screen-only">
  <UniverseTreeTable ... />
  <DetailColumn ... />
  <EnsembleSidebar ... />
</main>

<aside class="tear-sheet print-only">
  <TearSheet symbol={selectedSymbol} detail={detail} ensemble={ensemble} />
</aside>
```

```css
/* Add to globals.css or print.css */
.screen-only { display: block; }
.print-only  { display: none; }

@media print {
  .screen-only { display: none !important; }
  .print-only  { display: block !important; }

  @page {
    size: A4 portrait;
    margin: 12mm;
  }

  body {
    background: white;
    color: black;
    font-size: 14px;
    line-height: 1.4;
  }

  /* Hide all interactive chrome */
  nav, header.top-ribbon, .universe-panel, .tab-nav, .ensemble-sidebar,
  button, input, select { display: none !important; }

  /* Print-grade typography */
  .tear-sheet h1 { font-size: 18px; }
  .tear-sheet h2 { font-size: 14px; }
  .tear-sheet table { font-size: 12px; }
  .tear-sheet td, .tear-sheet th { padding: 4px 8px; }

  /* No page breaks inside cards */
  .tear-sheet section { page-break-inside: avoid; }
}
```

### `<TearSheet>` component

```typescript
// frontend/components/fundamentals/tear-sheet.tsx
"use client"

import { FundamentalStockDetail, FundamentalEnsembleResult } from "@/lib/api"
import { CrossMethodScatter } from "./cross-method-scatter"
import { ScoreBar } from "./score-bar"

interface TearSheetProps {
  symbol: string;
  detail: FundamentalStockDetail;
  ensemble: FundamentalEnsembleResult;
}

export function TearSheet({ symbol, detail, ensemble }: TearSheetProps) {
  const topModels = ensemble.model_weights
    ? Object.entries(ensemble.model_weights)
        .sort(([, a], [, b]) => b - a)
        .slice(0, 3)
        .map(([key, weight]) => ({
          key,
          weight,
          row: detail.valuations.find(v => v.model === key)!,
        }))
    : []

  const reverseDcf = detail.valuations.find(v => v.model === "reverse_dcf")
  const sustainable = computeSustainableGrowthFromSnapshot(detail.snapshot)

  return (
    <section class="tear-sheet">
      <Header symbol={symbol} detail={detail} />
      <EnsembleSection ensemble={ensemble} />
      <PillarsAndDiagnosticsSection detail={detail} />
      <TopModelsSection models={topModels} />
      <ReverseDcfSection reverseDcf={reverseDcf} sustainable={sustainable} />
      <Footer />
    </section>
  )
}
```

### Sub-section components

#### `<Header>`

```tsx
<header class="tear-header">
  <div class="tear-symbol">{symbol}</div>
  <div class="tear-name">{detail.display_name}</div>
  <div class="tear-meta">
    {detail.sector} · {detail.market_region} · {fmtFreshness(detail.imported_at)}
    <span class="meta-right">FY {detail.fiscal_year} · {detail.currency}</span>
  </div>
</header>
```

#### `<EnsembleSection>`

```tsx
<section class="tear-section ensemble">
  <h2>Ensemble fair value</h2>
  <div class="ensemble-grid">
    <div>
      <div class="big-number">{currency} {ensemble.fair_value_base}</div>
      <div class="band">band MC {ensemble.monte_carlo_low}–{ensemble.monte_carlo_high}</div>
      <div class="dispersion">model dispersion {ensemble.model_dispersion_low}–{ensemble.model_dispersion_high}</div>
      <div class="conf">confidence {ensemble.confidence_score?.toFixed(2)}</div>
    </div>
    <div>
      <div>Current: {currency} {ensemble.current_price}</div>
      <div class={cn("upside", upsideClass(ensemble.upside_pct))}>Upside {fmtPct(ensemble.upside_pct)}</div>
      <div class="verdict">{computeVerdict(ensemble)}</div>
    </div>
  </div>
  <CrossMethodScatter
    models={...}
    ensembleBase={ensemble.fair_value_base!}
    modelDispersionLow={ensemble.model_dispersion_low!}
    modelDispersionHigh={ensemble.model_dispersion_high!}
    monteCarloLow={ensemble.monte_carlo_low!}
    monteCarloHigh={ensemble.monte_carlo_high!}
    currentPrice={ensemble.current_price!}
    currency={ensemble.currency!}
  />
</section>
```

#### `<PillarsAndDiagnosticsSection>`

Two columns. Left: 6 pillar rows with score bar, scope, score number. Right: diagnostics table (DuPont gap, Piotroski, Accrual, Altman Z, ROIC spread, EVA).

Pull data from `detail.snapshot.scores`, `detail.snapshot.diagnostics`, and `detail.snapshot.diagnostics.screens`.

#### `<TopModelsSection>`

Loops over `topModels`. Each card:

```tsx
<div class="model-card">
  <h3>{MODEL_LABELS[m.key]} ({(m.weight * 100).toFixed(0)}%, {m.row.confidence})</h3>
  <div class="model-fair">Fair {currency} {m.row.fair_value} · {m.row.methodology}</div>
  <div class="model-inputs">{formatInputs(m.row.inputs)}</div>
</div>
```

`formatInputs()` produces a one-line summary: e.g. `inputs: book MAD 211, ROE 14%, COE 10.5%, fade 5y`. The function uses model-specific templates similar to the step-trace renderers in `model-step-traces.ts`.

#### `<ReverseDcfSection>`

```tsx
<section class="tear-section reverse">
  <h2>Reverse DCF — what market believes</h2>
  <div class="impl-growth">Implied perpetual growth: {fmtPct(reverseDcf.outputs.implied_perpetual_growth)} (at WACC {fmtPct(reverseDcf.inputs.wacc)})</div>
  <div class="comparisons">
    <ComparisonLine label="Terminal growth" value={0.03} impl={impl} />
    <ComparisonLine label="Sustainable g" value={sustainable} impl={impl} />
    <ComparisonLine label="LT GDP+inflation" value={0.05} impl={impl} />
  </div>
  <div class="reading">Reading: {computeReverseDcfReading(impl, sustainable)}</div>
</section>
```

`<ComparisonLine>`: shows the label, target value, the implied value, and a chip ("above"/"below"/"in line").

#### `<Footer>`

```tsx
<footer class="tear-footer">
  <span>Generated by {app_name} v{version}</span>
  <span>{new Date().toISOString().split("T")[0]}</span>
  <div class="disclaimer">This is not investment advice. Methodology in docs/fundamentals-layer/.</div>
</footer>
```

## Print typography

```css
.tear-sheet {
  font-family: "Inter", system-ui, sans-serif;
  font-size: 14px;
  line-height: 1.4;
  color: black;
  background: white;
}

.tear-sheet .font-mono {
  font-family: "IBM Plex Mono", monospace;
  font-variant-numeric: tabular-nums;
}

.tear-sheet h1 {
  font-size: 22px;
  font-weight: 700;
  margin: 0;
}

.tear-sheet h2 {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #6B7280;
  margin: 0 0 4mm 0;
  padding-bottom: 2mm;
  border-bottom: 1px solid #E5E7EB;
}

.tear-sheet section {
  margin-bottom: 6mm;
  page-break-inside: avoid;
}

.tear-sheet .big-number {
  font-family: "IBM Plex Mono", monospace;
  font-size: 24px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
```

## Page break rules

```css
@media print {
  .tear-sheet section { page-break-inside: avoid; }
  .tear-sheet h2     { page-break-after: avoid; }   /* heading sticks to its section */
  .tear-sheet table  { page-break-inside: avoid; }
}
```

Ideally everything fits on 1 page. If the symbol has unusual data (e.g. extremely long sector name, lots of warnings), the layout can overflow to page 2 — but the design is sized so that 95% of symbols fit on page 1.

## PDF export — alternative path

For cases where browser print-to-PDF is unreliable (server-side rendering, automated reports), implement a separate `@react-pdf/renderer` path:

```typescript
// frontend/lib/fundamentals/tear-sheet-pdf.tsx
import { Document, Page, Text, View, StyleSheet } from "@react-pdf/renderer"

const styles = StyleSheet.create({
  page: { padding: 30, fontSize: 11 },
  title: { fontSize: 16, fontWeight: 700 },
  // ...
})

export function TearSheetPdf({ symbol, detail, ensemble }: TearSheetProps) {
  return (
    <Document>
      <Page size="A4" style={styles.page}>
        <View>
          <Text style={styles.title}>{symbol} — {detail.display_name}</Text>
          {/* ... rest of the layout */}
        </View>
      </Page>
    </Document>
  )
}
```

Add `@react-pdf/renderer` to `frontend/package.json` only if the user wants server-side or programmatic generation. For the default user flow (analyst presses Ctrl+P), the browser print is sufficient.

## Testing

### Visual regression

- For 3 sample symbols (1 industrial, 1 bank, 1 utility), generate the tear-sheet and verify against a stored reference image (Playwright + `expect(page).toHaveScreenshot()`).

### Print correctness

- `playwright`'s `page.pdf()` API generates an actual PDF; compare structurally against expected output for one symbol.
- Manually verify on Chrome, Safari, Firefox, Edge — `@media print` behavior diverges across browsers.

### Long-content overflow

- For a symbol with many warnings or unusually-long display_name, verify the layout still fits on 1 page or breaks gracefully.

## Verification

After implementation:

1. Open `/fundamentals?symbol=ATW`, press Ctrl+P → preview shows the tear-sheet, no universe/sidebar/tabs visible.
2. Print → A4 page renders with all 5 sections visible.
3. Compare against the layout sketch at the top of this doc — match.
4. Save as PDF → file opens cleanly, copy-paste of numbers works (PDF text is selectable).
5. For a bank (e.g. ATW), the verdict box reflects financial-sector handling (DCFs excluded).
6. For a utility (e.g. an electricity producer), DDM is heavily weighted and the reverse-DCF reading reflects this.

## See also

- [15-ui-goals-and-design.md](15-ui-goals-and-design.md) — page-level layout that this tear-sheet replaces in print.
- [18-ui-component-library.md](18-ui-component-library.md) — `<TearSheet>` component spec.
- [17-ui-design-language.md](17-ui-design-language.md) — typography and color rules adapted for paper.
## Backend export endpoints

The backend now exposes synchronous HTML artefacts:

- `GET /fundamentals/stocks/{symbol}/tearsheet?lang=fr&format=html`
- `GET /fundamentals/stocks/{symbol}/ic-memo?lang=fr`
- `GET /fundamentals/morning-note?date=YYYY-MM-DD&symbols=ATW,IAM&lang=fr`

The renderer is tolerant of missing optional sections and shows a top-page missing-data banner instead of failing the request. PDF remains a soft follow-up; no hard PDF rendering dependency is required for v1.
