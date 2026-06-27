-- Calendar dimension generated with dbt_utils.date_spine (one row per day).
-- Starts 2000-01 (signal history) and runs 10 years into the FUTURE so it covers
-- forward-dated fundamental projections (as_of fiscal-year-ends up to 2026-12-31+).
-- A date dimension lets you slice facts by year/quarter/month/weekday for free.
with spine as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2000-01-01' as date)",
        end_date="cast(current_date + interval '10 years' as date)"
    ) }}
)

select
    cast(to_char(date_day, 'YYYYMMDD') as integer) as date_key,   -- e.g. 20260513, joins to facts
    cast(date_day as date)                         as full_date,
    extract(year    from date_day)::int            as year,
    extract(quarter from date_day)::int            as quarter,
    extract(month   from date_day)::int            as month,
    to_char(date_day, 'Mon')                       as month_short,
    extract(day     from date_day)::int            as day_of_month,
    extract(isodow  from date_day)::int            as iso_day_of_week,  -- 1=Mon .. 7=Sun
    (extract(isodow from date_day) in (6, 7))      as is_weekend
from spine
