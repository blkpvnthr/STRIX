-- Grain: one row per (instrument_symbol, session_date).
-- Rolling realized volatility over 5/10/20/60 trailing daily LOG returns, each the
-- sample standard deviation of log returns annualized by sqrt(252). Sample-size
-- columns expose how many log returns each window actually used (a window near the
-- series start is under-filled and must be read with its sample size).
with base as (
    select
        instrument_symbol,
        session_date,
        session_index,
        log_return
    from {{ ref('int_market_daily') }}
)
select
    instrument_symbol,
    session_date,
    ({{ strix_stddev_samp('log_return') }} over w5) * sqrt(252) as vol_5_annualized,
    count(log_return) over w5 as vol_5_samples,
    ({{ strix_stddev_samp('log_return') }} over w10) * sqrt(252) as vol_10_annualized,
    count(log_return) over w10 as vol_10_samples,
    ({{ strix_stddev_samp('log_return') }} over w20) * sqrt(252) as vol_20_annualized,
    count(log_return) over w20 as vol_20_samples,
    ({{ strix_stddev_samp('log_return') }} over w60) * sqrt(252) as vol_60_annualized,
    count(log_return) over w60 as vol_60_samples
from base
window
    w5 as (partition by instrument_symbol order by session_index rows between 4 preceding and current row),
    w10 as (partition by instrument_symbol order by session_index rows between 9 preceding and current row),
    w20 as (partition by instrument_symbol order by session_index rows between 19 preceding and current row),
    w60 as (partition by instrument_symbol order by session_index rows between 59 preceding and current row)
