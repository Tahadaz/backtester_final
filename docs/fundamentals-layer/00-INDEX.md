# Fundamentals layer — documentation index

This layer covers the fundamental analysis subsystem: workbook ingestion, snapshot construction, pillar scoring, intrinsic valuation across 7 models, ensemble blending, and the analyst-facing UI at `/fundamentals`.

The engine is **MAD-tuned** (default risk-free 3.5%, equity risk premium 5.5%, country risk premium 1.5%) and supports Excel workbook uploads plus batch yfinance ingestion for non-MASI symbols. Cross-currency valuation is guarded by currency tagging rather than FX conversion.

## Reading order

| # | File | What it covers |
|---|---|---|
| 01 | [Overview and design philosophy](01-overview-and-design-philosophy.md) | Why this layer exists, the "rate everything, blend by confidence" thesis, system diagram |
| 02 | [Data flow](02-data-flow.md) | Excel → parse → snapshot → score → valuate → ensemble → API → UI |
| 03 | [Workbook specification](03-workbook-spec.md) | Required sheets, header rows, canonical metric vocabulary |
| 04 | [Pillars and scoring](04-pillars-and-scoring.md) | The 6 pillars, weights, percentile-ranking algorithm |
| 05 | [Diagnostics: Piotroski / DuPont / accrual](05-diagnostics-piotroski-dupont-accrual.md) | The three accounting-quality probes |
| 06 | [Valuation models](06-valuation-models.md) | All 7 models — formulas, eligibility, worked examples |
| 07 | [Ensemble and confidence](07-ensemble-and-confidence.md) | Model weights × confidence, fair-value band construction |
| 08 | [Assumptions and defaults](08-assumptions-and-defaults.md) | `DEFAULT_ASSUMPTIONS` table, override hierarchy |
| 09 | [API + frontend contracts](09-api-data-flow-and-frontend-contracts.md) | REST endpoints, TypeScript types, page surface |
| 10 | [Modelling playbooks](10-modelling-playbooks.md) | Opinionated checklists for common analyst tasks |
| 11 | [Prompts for Claude](11-prompts-for-claude.md) | Ready-to-paste prompts grounded in this repo |
| 12 | [Known issues and limitations](12-known-issues-and-limitations.md) | **The review for Codex.** 21 numbered issues with fix recipes |
| 13 | [Methodology and sources](13-methodology-and-sources.md) | Academic references (Ohlson, Sloan, Piotroski, Damodaran) |
| 14 | [Implementation roadmap](14-implementation-roadmap.md) | v3 implementation status and operational follow-up |
| 15 | [UI goals and design](15-ui-goals-and-design.md) | Full rebuild specification for the `/fundamentals` page — layout, tabs, interactions, compare mode |
| 16 | [Institutional screens](16-institutional-screens.md) | Magic Formula, PEG/GARP, Altman Z, EVA, regression-adjusted multiples — implementation spec |
| 17 | [UI design language](17-ui-design-language.md) | Tokens, typography, color, density, table grammar |
| 18 | [UI component library](18-ui-component-library.md) | Per-component implementation contracts (props, structure, behavior) |
| 19 | [UI tear-sheet spec](19-ui-tear-sheet-spec.md) | Print stylesheet and PDF export |
| 20 | [Claude Design handoff](20-claude-design-handoff.md) | **Canonical UI spec** — unified Signals page topology, 5-tab Fundamental view, DM Sans/Mono + oklch tokens, per-component CSS reference. **Read first before any UI work.** |
| 21 | [Codex briefs — master index + dangers of the current app](21-codex-briefs-INDEX.md) | **Start here for any work derived from the plugin-rubric review.** Lists D1–D10 silent-failure modes and points to briefs 22–29. |
| 22 | [Codex brief: 3-statement integrity & projected statements (P1)](22-codex-3statement-integrity.md) | BS balance / cash tie-out / NI link checks; projected IS/BS/CFS materialised; integrity haircut to confidence. **Most important brief.** |
| 23 | [Codex brief: thesis persistence per symbol (P1)](23-codex-thesis-persistence.md) | `fundamental_thesis` table + CRUD; one-current-per-symbol invariant; append-only history via `is_current` flip. |
| 24 | [Codex brief: catalyst calendar (P1)](24-codex-catalyst-calendar.md) | `fundamental_catalyst` table; worker ingest from yfinance; calendar API; linkage to thesis. |
| 25 | [Codex brief: per-symbol Bull/Base/Bear scenarios (P2)](25-codex-scenarios-per-symbol.md) | `fundamental_assumption_override` table; `resolve_assumptions(symbol, scenario, loader)` three-layer merge; assumption provenance on envelope. |
| 26 | [Codex brief: sensitivity tables (P2 quick win)](26-codex-sensitivity-tables.md) | `compute_sensitivity_grid` 5×5 helper; two grids per scenario per symbol; `EnsembleResult.sensitivity_grids` field. |
| 27 | [Codex brief: materialised comps view (P2 quick win)](27-codex-comps-artifact.md) | `compute_comps_table` materialises peer cohort + 5-row stats footer; rides on envelope, no new DB. |
| 28 | [Codex brief: pillar-score history & trend (P2)](28-codex-pillar-history.md) | `fundamental_pillar_score_history` table; pure `classify_pillar_trend` (on_track / watch / behind / insufficient_data). |
| 29 | [Codex brief: tear-sheet / IC-memo / morning-note export (P2)](29-codex-tearsheet-export.md) | Three Jinja-rendered HTML artefacts under existing auth; optional PDF via soft-import WeasyPrint. |
| 59 | [Cross-sectional fundamental composite — methodology & rationale](59-cross-sectional-composite-methodology.md) | **Strategy reframe.** Why absolute valuation is an anchor, not a signal; the SFC composite (value/quality/fundamental momentum/price momentum), PIT rules, validation gates, sources. |
| 60 | [Codex brief: SFC implementation](60-codex-cross-sectional-composite-implementation.md) | Phased implementation of brief 59: PIT IC study (gate) → persistence → dashboard → blotter. |
| — | [Review vs plugin skills](REVIEW_vs_plugin_skills.md) | The audit that motivated briefs 21–29. Read before brief 21. |

## Public surface (entry points)

| Symbol | Location | Purpose |
|---|---|---|
| `parse_fundamental_workbook` | `core/quant_core/fundamentals/workbook.py` | Excel → `FundamentalWorkbook` |
| `score_fundamental_snapshots` | `core/quant_core/fundamentals/scoring.py:232` | Compute 6-pillar percentile scores |
| `compute_symbol_valuations` | `core/quant_core/fundamentals/valuation.py:601` | Run all 7 valuation models for one symbol |
| `compute_valuation_ensemble` | `core/quant_core/fundamentals/valuation.py:555` | Blend model outputs into a fair-value band |
| `DEFAULT_ASSUMPTIONS` | `core/quant_core/fundamentals/valuation.py:14` | MAD-tuned defaults |
| `execute_import_run` | `services/api/app/services/fundamentals.py` | Full ingestion pipeline (parse → score → valuate → persist) |
| `latest_import` | `services/api/app/services/fundamentals.py` | Latest workbook import for the upload UI contract |

## Severity legend (used throughout)

- 🔴 **Logic concern** — math doesn't match textbook or has a silent failure mode
- 🟡 **Configuration smell** — a default that's likely wrong in production
- 🔵 **Missing institutional feature** — works as designed but lacks something standard analysts expect

## Related layer docs

- [`docs/factor-layer/00-INDEX.md`](../factor-layer/00-INDEX.md) — the factor system (technical signals)
- [`docs/signal-generation/00-INDEX.md`](../signal-generation/00-INDEX.md) — signal engine, where fundamental modes will plug in
- [`docs/data-layer/00-INDEX.md`](../data-layer/00-INDEX.md) — OHLCV ingestion (parallel pipeline)
- [`docs/APP_MAP.md`](../APP_MAP.md) — top-level navigation
