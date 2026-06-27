-- Second fact (~700 rows) — small, so a full table rebuild each run is fine.
-- Grain: one row per (symbol, import_id) — each import is a recompute, so the
-- SAME as_of can appear across imports (that's why as_of alone isn't the key).
-- Shares the conformed dim_symbol and dim_date with fct_signal_scores — that
-- reuse is what "conformed" means.
with pillars as (
    select * from {{ ref('stg_fundamental_pillar_scores') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['symbol', 'import_id']) }} as pillar_key,
    {{ dbt_utils.generate_surrogate_key(['symbol']) }}             as symbol_key,
    cast(to_char(as_of_date, 'YYYYMMDD') as integer)               as date_key,
    symbol,
    import_id,
    as_of_date,
    value_score,
    quality_score,
    growth_score,
    risk_score,
    cash_flow_score,
    health_score,
    overall_score
from pillars
