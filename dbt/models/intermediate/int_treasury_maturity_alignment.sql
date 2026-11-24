-- Grain: one row per observation_date (curve snapshot).
-- Pivots par yields (percent) into the maturities the curve-spread marts need.
-- Missing tenors on a given date remain NULL; spreads over a NULL leg are NULL
-- (never silently zero). Units are percent throughout.
with y as (
    select * from {{ ref('stg_treasury_yields') }}
)
select
    observation_date,
    max(case when tenor = '1M' then yield_pct end)  as y_1m,
    max(case when tenor = '3M' then yield_pct end)  as y_3m,
    max(case when tenor = '6M' then yield_pct end)  as y_6m,
    max(case when tenor = '1Y' then yield_pct end)  as y_1y,
    max(case when tenor = '2Y' then yield_pct end)  as y_2y,
    max(case when tenor = '3Y' then yield_pct end)  as y_3y,
    max(case when tenor = '5Y' then yield_pct end)  as y_5y,
    max(case when tenor = '7Y' then yield_pct end)  as y_7y,
    max(case when tenor = '10Y' then yield_pct end) as y_10y,
    max(case when tenor = '20Y' then yield_pct end) as y_20y,
    max(case when tenor = '30Y' then yield_pct end) as y_30y,
    count(*) as tenor_count
from y
group by observation_date
