-- Staging (silver) over macro_factor_meta — the non-equity symbols (commodities,
-- forex, etc.) that also appear in the signal fact. Shaped to UNION cleanly with
-- stg_stock_master inside dim_symbol.
with src as (
    select * from {{ source('app', 'macro_factor_meta') }}
)

select
    upper(trim(canonical_id)) as symbol,
    display_name,
    asset_type,
    market_region,
    active                    as is_active
from src
