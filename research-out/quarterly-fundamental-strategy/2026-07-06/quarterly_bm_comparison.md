# Quarterly B/M Comparison (Phase 4)

## Key realization: quarterly data is already blended into the current pipeline

`methodology_bakeoff.py::_load_panel` already calls `build_pit_panel(annual_rows=..., period_rows=..., ...)` — `period_rows` (quarterly + semiannual) are already merged into the same metric resolver as annual rows via `panel.py:_latest_metric_map`. Confirmed directly: ATW's resolved book equity in the *existing* panel changes value at 2022-09-30, 2024-09-30, and 2025-07-31 — dates that are not ATW's (December) fiscal year-end, i.e., genuine quarterly/interim balance-sheet updates are already flowing into "QB1," which is therefore not a pure annual-only baseline as originally assumed. **QB1 and QB2 (Phase 4's proposed comparison) are largely the same thing today**, not two different untested variants.

## Annual-only ablation (QB1 restricted) vs current pipeline (QB2, as-is)

Built two panels: `build_pit_panel(..., period_rows=period, ...)` (current, as-is) vs `build_pit_panel(..., period_rows=None, ...)` (artificial annual-only ablation), same 3,104 stock-months, and counted book-equity "refresh events" (a monthly observation whose numerator differs from the immediately preceding one by more than a rounding tolerance) vs "repeat events" (same numerator as last month).

| Panel | Total refresh events | Total repeat events | % repeat |
|---|---|---|---|
| With quarterly/semiannual (current) | 381 | 2,723 | 87.7% |
| Annual-only (ablation) | 377 | 2,727 | 87.9% |

**Only 4 more refresh events across the entire 71-symbol, 111-month panel from including quarterly/semiannual data** — a negligible difference. Breaking down by symbol: **only 5 of 71 symbols (7%) get even a single additional refresh event** from the quarterly data (BCP, IAM, JET, LHM, MSA — each +1 event only). This is a real, quantified, and rather stark finding: despite 56-72 of 73 symbols having *some* quarterly/semiannual row in the raw table (`quarterly_data_semantics.md`), almost none of that translates into the resolved panel actually picking up a different, fresher book-equity value than the annual filing already provides — likely because the quarterly rows' PIT availability dates land close to (or after) the next annual filing's own availability date, so the resolver's "latest wins" rule rarely selects the quarterly value as the winner in practice.

## Does quarterly B/M improve on annual B/M?

**No, not measurably, given the current resolver behavior.** The signal the "monthly six-vintage" strategy already uses is *already* the quarterly-blended one (QB2 in the brief's terms), and an annual-only ablation would produce almost the same panel. This is not a case of "quarterly data would help but hasn't been tried" — it has effectively already been tried (it's the status quo), and its incremental contribution is minimal in aggregate. The negative-book-equity, minority-interest, and other accounting-context questions from the brief are therefore moot for B/M specifically at this data-coverage level: there is no meaningfully different "quarterly variant" to canonicalize beyond what's already in production.
