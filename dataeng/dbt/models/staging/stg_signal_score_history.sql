-- Staging (silver) over the ~6.6M-row signal_score_history fact source.
-- Key modeling decision: the raw `source` column is COMPOUND. It is either a
-- base family ("engine_expanded", "engine_legacy", "wfo") or that base plus a
-- ":method" variant ("wfo:expanded_factor_x_ta_combo"). We split it into
-- source_base + source_method so downstream dims/tests are clean, and keep
-- source_raw so nothing is lost (the original grain still holds).
with src as (
    select * from {{ source('app', 'signal_score_history') }}
)

select
    date                                    as score_date,
    upper(trim(symbol))                     as symbol,
    source                                  as source_raw,
    split_part(source, ':', 1)              as source_base,
    nullif(split_part(source, ':', 2), '')  as source_method,
    lower(category)                         as category,
    lower(horizon)                          as horizon,
    score_pct,
    is_oos
from src
