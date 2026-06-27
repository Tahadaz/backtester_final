-- Staging (silver): a clean 1:1 view over the raw stock_master.
-- Rules of a staging model: rename/cast/light-clean ONLY. No joins, no business
-- logic, no aggregation. One staging model per source table.
with src as (
    select * from {{ source('app', 'stock_master') }}
)

select
    upper(trim(symbol))   as symbol,        -- canonical natural key
    display_name,
    isin,
    sector,
    market_cap_class,
    asset_type,
    market_region,
    shares_outstanding,
    is_active
from src
