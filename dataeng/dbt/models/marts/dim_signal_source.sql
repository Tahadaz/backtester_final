-- Dimension of signal sources. One row per distinct raw source string, carrying
-- the decomposed base family + method variant (parsed back in staging).
with sources as (
    select distinct
        source_raw,
        source_base,
        source_method
    from {{ ref('stg_signal_score_history') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['source_raw']) }} as source_key,
    source_raw,
    source_base,
    source_method
from sources
