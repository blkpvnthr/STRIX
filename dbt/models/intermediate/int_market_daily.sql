-- Grain: one row per (instrument_symbol, session_date).
-- Base trading-session model: assigns a dense per-instrument session index and the
-- prior close, then the daily simple return. All downstream market analytics build
-- on this so session alignment and return math are defined in exactly one place.
with bars as (
    select * from {{ ref('stg_market_bars') }}
),
ordered as (
    select
        *,
        row_number() over (
            partition by instrument_symbol order by session_date
        ) as session_index,
        lag(close_price) over (
            partition by instrument_symbol order by session_date
        ) as prev_close
    from bars
)
select
    instrument_symbol,
    session_date,
    date_key,
    session_index,
    open_price,
    high_price,
    low_price,
    close_price,
    volume,
    vwap,
    prev_close,
    {{ strix_safe_divide('close_price', 'prev_close') }} - 1 as daily_return,
    -- log return (for volatility); NULL when either price is non-positive.
    case
        when prev_close is not null and prev_close > 0 and close_price > 0
        then {{ strix_ln('close_price / prev_close') }}
    end as log_return,
    source_code,
    bronze_artifact_id,
    silver_publication_id
from ordered
