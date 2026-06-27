{{ config(
    materialized='incremental',
    unique_key='signal_score_key',
    incremental_strategy='delete+insert'
) }}

-- The primary fact (~6.6M rows). Grain: one row per
-- (score_date, symbol, source_raw, category, horizon).
--
-- Foreign keys are computed with the SAME surrogate-key expressions as the
-- dimensions, so they match exactly — the relationships tests prove there are
-- no orphan facts.
--
-- Incremental: on the first run the table is built in full. On later runs only
-- the most recent day onward is reprocessed; `unique_key` + delete+insert make
-- re-running idempotent and capture late-arriving same-day rows. Without this,
-- every run would rescan all 6.6M rows.
with scores as (
    select * from {{ ref('stg_signal_score_history') }}
    {% if is_incremental() %}
    where score_date >= (select max(score_date) from {{ this }})
    {% endif %}
)

select
    {{ dbt_utils.generate_surrogate_key(['score_date', 'symbol', 'source_raw', 'category', 'horizon']) }} as signal_score_key,
    {{ dbt_utils.generate_surrogate_key(['symbol']) }}                                                    as symbol_key,
    cast(to_char(score_date, 'YYYYMMDD') as integer)                                                      as date_key,
    {{ dbt_utils.generate_surrogate_key(['source_raw']) }}                                                as source_key,
    {{ dbt_utils.generate_surrogate_key(['category', 'horizon']) }}                                       as category_key,
    score_date,
    symbol,
    score_pct,
    is_oos
from scores
