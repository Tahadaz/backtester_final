-- "Junk" dimension: the distinct (category, horizon) combinations that appear in
-- the signal fact. Collapsing two low-cardinality flags into one small dimension
-- keeps the fact narrow (one category_key instead of two text columns).
with combos as (
    select distinct
        category,
        horizon
    from {{ ref('stg_signal_score_history') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['category', 'horizon']) }} as category_key,
    category,
    horizon
from combos
