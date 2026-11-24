-- Grain: one row per instrument (latest available session snapshot).
-- Trailing price-return performance over standard horizons. Prices come from Alpaca
-- with adjustment=all (split AND dividend adjusted), so these returns are TOTAL
-- returns on the adjusted series — labeled explicitly in return_basis; they are NOT
-- raw price returns and are NOT unadjusted. Horizons are measured in TRADING
-- SESSIONS (5/21/63/252), plus calendar year-to-date. A horizon whose lookback
-- predates the instrument's history yields NULL (never a partial-window number).
{% set horizons = {'w1': 5, 'm1': 21, 'q1': 63, 'y1': 252} %}
with d as (
    select
        instrument_symbol,
        session_date,
        session_index,
        close_price,
        daily_return,
        year(session_date) as cal_year,
        max(session_index) over (partition by instrument_symbol) as last_idx
    from {{ ref('int_market_daily') }}
),
calc as (
    select
        instrument_symbol,
        session_date,
        session_index,
        close_price,
        daily_return,
        last_idx,
        cal_year,
        {% for name, k in horizons.items() %}
        {{ strix_safe_divide('close_price', 'lag(close_price, ' ~ k ~ ') over w') }} - 1 as ret_{{ name }},
        {% endfor %}
        first_value(close_price) over (
            partition by instrument_symbol, cal_year order by session_index
            rows between unbounded preceding and unbounded following
        ) as ytd_base
    from d
    window w as (partition by instrument_symbol order by session_index)
)
select
    instrument_symbol,
    session_date as as_of_session,
    close_price,
    daily_return                                     as daily_return,
    ret_w1                                           as weekly_return,
    ret_m1                                           as monthly_return,
    ret_q1                                           as quarterly_return,
    ret_y1                                           as trailing_annual_return,
    {{ strix_safe_divide('close_price', 'ytd_base') }} - 1 as ytd_return,
    'split_dividend_adjusted (Alpaca adjustment=all)' as return_basis,
    (last_idx + 1)                                   as sessions_available
from calc
where session_index = last_idx
