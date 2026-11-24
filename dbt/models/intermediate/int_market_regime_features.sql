-- Grain: one row per instrument over its full available window.
-- Measurable regime FEATURES per instrument: full-window price return, annualized
-- realized volatility (all log returns), max drawdown, session span, and trend
-- direction. These are descriptive similarity features only — they carry no
-- predictive claim and establish no causality (enforced in the mart's framing).
with daily as (
    select * from {{ ref('int_market_daily') }}
),
dd as (
    select instrument_symbol, min(drawdown) as max_drawdown
    from {{ ref('int_rolling_drawdown') }}
    group by instrument_symbol
),
cum as (
    select
        instrument_symbol,
        cumulative_return as full_window_return,
        row_number() over (partition by instrument_symbol order by session_index desc) as rn
    from {{ ref('int_cumulative_returns') }}
),
agg as (
    select
        instrument_symbol,
        count(*) as session_count,
        count(log_return) as return_count,
        min(session_date) as first_session,
        max(session_date) as last_session,
        ({{ strix_stddev_samp('log_return') }}) * sqrt(252) as annualized_volatility
    from daily
    group by instrument_symbol
)
select
    agg.instrument_symbol,
    agg.session_count,
    agg.return_count,
    agg.first_session,
    agg.last_session,
    c.full_window_return,
    agg.annualized_volatility,
    dd.max_drawdown,
    case
        when c.full_window_return is null then null
        when c.full_window_return > 0 then 'up'
        when c.full_window_return < 0 then 'down'
        else 'flat'
    end as trend_direction
from agg
left join dd on dd.instrument_symbol = agg.instrument_symbol
left join cum c on c.instrument_symbol = agg.instrument_symbol and c.rn = 1
