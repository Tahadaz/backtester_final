# Workbook specification

The Excel ingestion path expects a specific sheet layout. This document captures the contract.

> Reference: `core/quant_core/fundamentals/workbook.py`.

## Required sheets

| Sheet name | Required? | Purpose |
|---|---|---|
| `Factor_Summary_Latest` | ✅ Yes | Per-symbol latest-period metric values |
| `Factor_Summary_10Y` | ✅ Yes | Per-symbol per-year metric history (long format) |
| `Market_Map` | ✅ Yes | Symbol ↔ company name mapping, sector, market region |
| `Summary` | Optional | Workbook-level summary (versioning, generation date) |
| `Coverage_10Y` | Optional | Per-symbol metric coverage diagnostic |
| `Data_Gap_Audit` | Optional | Pre-import data quality findings |
| `Long_Data` | Optional | Reserved for future long-format imports |
| `Annual_Source` | Optional | Source-of-truth annotations for annual rows |
| `prices` | Optional | Price series (ignored by fundamentals parser) |
| `nbre titres` | Optional | Shares-outstanding series (ignored — use snapshot metric) |

All sheets in `IGNORED_WIDE_SHEETS` (`workbook.py:19`) are not parsed as metric-wide tables.

## Sheet: `Factor_Summary_Latest`

Per-symbol, latest-period metric snapshot.

### Required columns

| Column | Type | Notes |
|---|---|---|
| `Company` | string | Must match an entry in `Market_Map` |
| `Latest Statement Year` | int | Fiscal year of the snapshot |
| `<metric_name>` | float | One column per metric (see canonical vocabulary below) |

### Header row

Row 1. All metric column headers must match canonical names exactly (case-sensitive).

### Row interpretation

Each non-header row produces one `FundamentalSnapshot`. Missing values → metric is absent from `snapshot.metrics` (not stored as `None`).

## Sheet: `Factor_Summary_10Y`

Long-format historical data. Each row is one (symbol, fiscal year, metric, value).

### Required columns

| Column | Type | Notes |
|---|---|---|
| `Company` | string | Must match `Market_Map` |
| `Statement_Year` | int | Fiscal year |
| `Has_Core_Fundamentals` | bool | If False, row is skipped during parsing |
| `<metric_name>` | float | One column per metric (wide format inside long table) |

### Header row

Row 1.

### Row interpretation

For each row, each metric column → one `AnnualMetricRow`. So a row with 30 metric columns produces 30 annual metric records.

## Sheet: `Market_Map`

Symbol ↔ company ↔ sector mapping. Used to resolve `Company` names from the other sheets to canonical `symbol` values.

### Required columns

| Column | Type | Notes |
|---|---|---|
| `Symbol` | string | The canonical ticker (e.g. `ATW`, `BCP`) |
| `Company` | string | Display name, must match `Factor_Summary_*` `Company` |
| `Sector` | string | Sector classification (used for peer grouping) |
| `Shares_Outstanding` | float | Diluted share count (used for per-share fair values) |

### Optional columns

| Column | Type | Notes |
|---|---|---|
| `Market_Region` | string | "masi" / "us" / "european" / "asian" / null |
| `ISIN` | string | International Securities ID |
| `Display_Name` | string | Friendly name for UI |

## Canonical metric vocabulary

The parser recognizes specific metric column names. Names are case-sensitive.

### Value metrics

| Name | Unit | Direction |
|---|---|---|
| `PER` | ratio | lower-better |
| `Price_to_Book` | ratio | lower-better |
| `Price_to_Sales` | ratio | lower-better |
| `EV_to_EBIT` | ratio | lower-better |
| `EV_to_EBITDA` | ratio | lower-better |
| `EV_to_Sales` | ratio | lower-better |
| `FCF_Yield` | percentage or ratio | higher-better |
| `Dividend_Yield` | percentage or ratio | higher-better |

The `_ratio()` helper at `valuation.py:69` interprets values: `abs(value) > 2.0` → assumed percentage, divided by 100.

### Quality metrics

| Name | Unit | Direction |
|---|---|---|
| `ROE` | percentage | higher-better |
| `ROA` | percentage | higher-better |
| `Operating_Margin` | percentage | higher-better |
| `Net_Margin` | percentage | higher-better |
| `FCF_Margin` | percentage | higher-better |
| `Debt_to_Equity` | ratio | lower-better |

### Growth metrics

| Name | Unit | Direction |
|---|---|---|
| `Revenue_Growth` | percentage | higher-better |
| `EBIT_Growth` | percentage | higher-better |
| `NetIncome_Growth` | percentage | higher-better |
| `FCF_Growth` | percentage | higher-better (preferred over Revenue_Growth for FCF DCF after V4 fix) |
| `OperatingCF_Growth` | percentage | higher-better |

### Risk metrics

| Name | Unit | Direction |
|---|---|---|
| `Debt_to_Equity` | ratio | lower-better |
| `NetDebt_to_Equity` | ratio | lower-better |
| `NetDebt_to_EBITDA` | ratio | lower-better |
| `Current_Ratio` | ratio | higher-better |
| `Cash_Ratio` | ratio | higher-better |
| `Equity_Multiplier` | ratio | lower-better (for solvency interpretation) |

### Cash flow metrics

| Name | Unit | Direction |
|---|---|---|
| `FCF_Margin` | percentage | higher-better |
| `FCF_Yield` | percentage | higher-better |
| `Operating_CF_Margin` | percentage | higher-better |
| `CAF_Margin` | percentage | higher-better |

### Dividend metrics

| Name | Unit | Direction |
|---|---|---|
| `Dividend_Yield` | percentage | higher-better |
| `Dividend_Coverage` | ratio | higher-better |
| `Dividend_Payout` | percentage | NA (used as input, not score) |

### Identification / market data

| Name | Unit | Notes |
|---|---|---|
| `Current_Price` | absolute (MAD) | Required for DCF per-share computation |
| `MarketCap_Calc` | absolute (MAD M) | Used by reverse DCF, eligibility checks |
| `Shares_Outstanding` | absolute count | Required for DCF per-share computation |
| `Asset_Turnover` | ratio | Used by DuPont diagnostic |

### Income statement (10Y long-format)

These appear in `Factor_Summary_10Y`, not in `Factor_Summary_Latest`:

| Name | Notes |
|---|---|
| `Chiffre_daffaires` / `Clean_Chiffre_daffaires` | Revenue (French alias used) |
| `Resultat_net` / `Clean_Resultat_net` | Net Income |
| `Dividendes` / `Clean_Dividendes` | Total dividends paid |
| `Free_Cash_Flow` | FCF time series |
| `NetDebt` | Net debt time series |

The `Clean_*` prefix indicates pre-processed (outliers removed, restated values applied) by the upstream workbook author. The parser uses both via `_latest_metric(history, "Clean_X", "X")` — preferring the Clean version when present.

## Quality issues

The parser emits `FundamentalQualityIssue` rows for soft problems:

| Code | Severity | When |
|---|---|---|
| `unmapped_company` | error | A row in `Factor_Summary_*` references a Company not in `Market_Map` |
| `missing_required_sheet` | error | One of the required sheets is absent |
| `metric_name_unknown` | warn | A column name not in canonical vocabulary |
| `duplicate_symbol` | warn | Same symbol appears in multiple Market_Map rows |
| `negative_revenue` | warn | A revenue value is negative (likely data error) |
| `fy_gap` | warn | A symbol's annual history has missing fiscal years |
| `metric_out_of_range` | warn | A ratio falls outside plausible bounds (e.g. PER > 1000) |

## Authoring a new workbook

If you're producing the Excel workbook upstream:

1. **Start from the canonical metric vocabulary.** Don't invent new metric names unless they're additive (the parser will warn on unknowns; new metrics need code support to feed pillars).
2. **Verify the 3 required sheets exist** before exporting.
3. **Make `Company` consistent across all sheets.** The `_normalize_company` helper trims whitespace and upper-cases, but mismatches will cause `unmapped_company` errors.
4. **Use IFRS-equivalent definitions** for income statement metrics.
5. **Include `Clean_*` versions** for restated history. The engine prefers them.
6. **Validate before upload** — load the workbook in Excel, check that `Market_Map.Symbol` matches `stock_master.symbol` in the DB.

## Parser internals (high level)

`parse_fundamental_workbook(payload: bytes | Path) -> FundamentalWorkbook`:

1. Opens the workbook with `openpyxl.load_workbook(...)`.
2. Reads `Summary` for versioning (optional).
3. Reads `Market_Map` → builds CompanyMapping list.
4. Reads `Factor_Summary_Latest` → builds FundamentalSnapshot list (one per company).
5. Reads `Factor_Summary_10Y` → builds AnnualMetricRow list.
6. Validates: every Company in 4 and 5 maps to a Market_Map entry.
7. Returns the `FundamentalWorkbook`.

The function does NOT score or valuate — that happens downstream in `score_fundamental_snapshots` and `compute_symbol_valuations`. The workbook is purely structural ingestion.

## See also

- [02-data-flow.md](02-data-flow.md) — where workbook parsing sits in the pipeline.
- [04-pillars-and-scoring.md](04-pillars-and-scoring.md) — which metrics feed which pillars.
- [10-modelling-playbooks.md#playbook-1](10-modelling-playbooks.md#playbook-1--i-just-uploaded-a-new-workbook-what-to-check-before-trusting-the-scores) — post-upload validation checklist.
