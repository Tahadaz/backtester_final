-- Staging (silver) over fundamental_pillar_score_history.
-- Grain: one row per (symbol, as_of_date). Scores are on a 0-100 scale
-- (verified against the data: min ~3.3, max 100).
with src as (
    select * from {{ source('app', 'fundamental_pillar_score_history') }}
)

select
    upper(trim(symbol))  as symbol,
    import_id,
    as_of                as as_of_date,
    value_score,
    quality_score,
    growth_score,
    risk_score,
    cash_flow_score,
    health_score,
    overall_score
from src
