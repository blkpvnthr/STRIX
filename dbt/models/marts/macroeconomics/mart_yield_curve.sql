-- Grain: one row per observation_date (curve snapshot).
-- Treasury curve spreads and changes. Yields and spreads are in PERCENTAGE POINTS;
-- a parallel _bps column gives basis points (pp * 100) so the two units are never
-- mixed silently. Spreads over a missing leg are NULL. Daily change is vs the prior
-- available curve date; historical change is vs the first available curve date.
with c as (
    select * from {{ ref('int_treasury_maturity_alignment') }}
),
seq as (
    select
        *,
        lag(y_10y) over (order by observation_date) as y_10y_prev,
        lag(y_2y)  over (order by observation_date) as y_2y_prev,
        lag(y_3m)  over (order by observation_date) as y_3m_prev,
        first_value(y_10y) over (
            order by observation_date rows between unbounded preceding and unbounded following
        ) as y_10y_first
    from c
)
select
    observation_date,
    y_3m, y_2y, y_10y, y_30y,
    tenor_count,
    (y_10y - y_2y)  as spread_10y_2y_pp,
    (y_10y - y_2y)  * 100 as spread_10y_2y_bps,
    (y_10y - y_3m)  as spread_10y_3m_pp,
    (y_10y - y_3m)  * 100 as spread_10y_3m_bps,
    (y_30y - y_10y) as spread_30y_10y_pp,
    (y_30y - y_10y) * 100 as spread_30y_10y_bps,
    case
        when y_10y is null or y_2y is null then null
        else (y_10y - y_2y) < 0
    end as is_inverted_10y_2y,
    (y_10y - y_10y_prev) as change_10y_daily_pp,
    (y_10y - y_10y_first) as change_10y_since_start_pp
from seq
