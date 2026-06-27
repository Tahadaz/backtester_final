-- Conformed dimension of EVERY symbol the facts reference: MASI equities
-- (stock_master) UNIONed with macro factors (macro_factor_meta). `asset_type`
-- and `source_table` distinguish the two. Built this way so the signal fact —
-- which scores both equities and macro factors — has zero orphan rows.
--
-- `symbol_key` is a surrogate key: a deterministic hash of the natural key
-- (symbol). Facts recompute the same hash to form their foreign key, which is
-- exactly what makes the relationships tests line up.
with equities as (
    select
        symbol,
        display_name,
        isin,
        sector,
        market_cap_class,
        asset_type,
        market_region,
        shares_outstanding,
        'stock_master'::varchar as source_table
    from {{ ref('stg_stock_master') }}
),

macro as (
    select
        symbol,
        display_name,
        cast(null as varchar) as isin,
        cast(null as varchar) as sector,
        cast(null as varchar) as market_cap_class,
        asset_type,
        market_region,
        cast(null as bigint)  as shares_outstanding,
        'macro_factor_meta'::varchar as source_table
    from {{ ref('stg_macro_factor_meta') }}
),

unioned as (
    select * from equities
    union all
    select * from macro
)

select
    {{ dbt_utils.generate_surrogate_key(['symbol']) }} as symbol_key,
    symbol,
    display_name,
    isin,
    sector,
    market_cap_class,
    asset_type,
    market_region,
    shares_outstanding,
    source_table
from unioned
