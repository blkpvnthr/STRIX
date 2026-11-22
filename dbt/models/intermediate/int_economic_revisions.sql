-- Grain: one row per economic observation, annotated with vintage rank.
-- FRED carries a vintage (realtime_start); BLS does not. vintage_rank_desc = 1 is
-- the latest vintage for a (series, observation_date); rank is NULL where no vintage
-- exists (BLS), which marts treat as observation-date fallback (documented).
with o as (
    select * from {{ ref('stg_economic_observations') }}
)
select
    *,
    case when has_vintage then
        row_number() over (
            partition by series_id, observation_date
            order by realtime_start desc
        )
    end as vintage_rank_desc,
    case when has_vintage then
        row_number() over (
            partition by series_id, observation_date
            order by realtime_start asc
        )
    end as vintage_rank_asc
from o
