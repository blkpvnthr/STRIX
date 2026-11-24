-- Grain: one row per (instrument_symbol, session_date).
-- Cumulative simple return from each instrument's FIRST available session:
-- close / first_close - 1. This is a PRICE return (not total return); dividends
-- and corporate actions are not added back here.
with d as (
    select * from {{ ref('int_market_daily') }}
)
select
    instrument_symbol,
    session_date,
    session_index,
    close_price,
    first_value(close_price) over (
        partition by instrument_symbol order by session_index
        rows between unbounded preceding and unbounded following
    ) as base_close,
    {{ strix_safe_divide(
        'close_price',
        'first_value(close_price) over (partition by instrument_symbol order by session_index rows between unbounded preceding and unbounded following)'
    ) }} - 1 as cumulative_return
from d
