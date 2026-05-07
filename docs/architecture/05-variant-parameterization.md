# Variant Parameterization & UI Propagation

This document describes how the Signal Engine supports multiple algorithmic variants (Legacy, Expanded, and Factor x TA) through a unified parameterization layer.

## Overview

The Signal Engine is designed to be variant-agnostic at the UI layer while allowing specialized metadata rendering based on the `variant_id`.

Supported variants:
- **Legacy**: Original signal logic.
- **Expanded**: Enriched technical analysis candidates.
- **Factor x TA**: Factor-conditioned technical signals generated from the per-stock, per-horizon factor-selection state.

## Variant Identification

Variants are identified by the `variant` field in API responses (e.g., `SignalRepresentative`).

### Heuristics
- **Factor variants**: identified by `variant='factor_x_ta'` on persisted results and by factor-condition metadata on representatives. These are treated as macro-conditioned technical signals.

## UI Components

### Unified Components
- **TechnicalAnalysisPanel**: The primary rendering engine for signal details. It accepts a `variant` prop to adjust its internal logic (e.g., fetching different detail schemas).
- **SharedSignalsView**: The shared Signal-page wrapper used by both Expanded TA and Factor x TA. The top-level `view=factor_x_ta` route remains available, but it renders the same hierarchy as native TA with `variant='factor_x_ta'`.
- **VariantDetailSheet**: A side-panel used across the dashboard and signal views. It dynamically adapts based on the variant:
    - For `factor_x_ta` variants, it displays an **ACTIF** status badge and identifies the origin as **Macro**.

### Decommissioned Components
The following components were removed to simplify the codebase:
- `FactorXTaPanel`: Functionality merged into `TechnicalAnalysisPanel`.
- `factor-x-ta-detail.tsx`: Merged into unified detail logic.

## Backend Integration

The backend ensures that every signal record is tagged with its originating `variant`.

### Persistence Tables
- `signal_engine_global_result`
- `wfo_global_signal`
- `wfo_signal_summary`

Batch scripts (`factor_x_ta_batch.py` and `wfo_factor_x_ta_batch.py`) explicitly set the `variant='factor_x_ta'` flag during the serialization phase.

### Factor Selection State
Factor x TA no longer reads a symbol-wide active-factor flag. The authoritative table is `stock_factor_relevance`, keyed by:

```text
(symbol, horizon, factor_canonical_id)
```

Only rows with `cusum_status='valid'` are eligible. The `horizon` value uses the selection vocabulary `short | mid | long`; adapters convert `mid` to the pipeline-facing `medium` value when scheduling Signal Engine and WFO jobs.

The Factor x TA cutover migration deletes existing persisted `variant='factor_x_ta'` rows from Signal Engine and WFO result tables, because those rows were produced before horizon-aware factor eligibility existed.

## Navigation and State

The `variant` parameter is propagated through URL search parameters:
- `/signals/variant/[id]?variant=factor_x_ta`
- `/signals?view=factor_x_ta`

This allows the `TechnicalAnalysisPanel` to determine which API endpoint or data structure to use for detailed drill-downs.
