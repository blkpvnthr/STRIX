-- Grain: one row per (instrument_symbol, session_date).
-- Running peak and current drawdown from that peak (a non-positive ratio). The
-- max-drawdown over any evaluation period is min(drawdown) over that period.
with d as (
    select
        instrument_symbol,
        session_date,
        session_index,
        close_price
    from {{ ref('int_market_daily') }}
)
select
    instrument_symbol,
    session_date,
    session_index,
    close_price,
    max(close_price) over (
        partition by instrument_symbol order by session_index
        rows between unbounded preceding and current row
    ) as running_peak,
    {{ strix_safe_divide(
        'close_price',
        'max(close_price) over (partition by instrument_symbol order by session_index rows between unbounded preceding and current row)'
    ) }} - 1 as drawdown
from d
