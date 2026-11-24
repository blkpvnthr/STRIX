-- Grain: one row per major index ETF proxy present (SPY, QQQ, DIA, IWM).
-- A latest-session market snapshot built from the performance, volatility, and
-- drawdown marts, with SPY-relative performance and freshness/coverage. These are
-- INDEX-ETF PROXIES for broad market segments — they are explicitly NOT market
-- breadth (advance/decline); the proxy_note column states this and no breadth
-- figure is derived from them.
{% set indices = "'SPY','QQQ','DIA','IWM'" %}
with perf as (
    select * from {{ ref('mart_instrument_performance') }}
    where instrument_symbol in ({{ indices }})
),
vol as (
    select instrument_symbol, vol_20_annualized, vol_20_samples
    from {{ ref('mart_market_volatility') }}
),
dd as (
    select instrument_symbol, current_drawdown, max_drawdown
    from {{ ref('mart_market_drawdown') }}
),
spy as (
    select daily_return as spy_daily, weekly_return as spy_weekly, monthly_return as spy_monthly
    from perf where instrument_symbol = 'SPY'
),
data_through as (
    select max(as_of_session) as data_through_date from perf
)
select
    p.instrument_symbol,
    p.as_of_session,
    p.close_price,
    p.daily_return,
    p.weekly_return,
    p.monthly_return,
    v.vol_20_annualized as realized_vol_20d,
    v.vol_20_samples,
    dd.current_drawdown,
    dd.max_drawdown,
    p.daily_return   - spy.spy_daily   as daily_vs_spy,
    p.weekly_return  - spy.spy_weekly  as weekly_vs_spy,
    p.monthly_return - spy.spy_monthly as monthly_vs_spy,
    p.sessions_available,
    dt.data_through_date,
    'index_etf_proxy_not_market_breadth' as proxy_note
from perf p
left join vol v using (instrument_symbol)
left join dd using (instrument_symbol)
cross join spy
cross join data_through dt
