-- Grain: one row per unordered instrument pair (symbol_a < symbol_b).
-- Pearson correlation of DAILY SIMPLE returns over ALIGNED sessions (inner join on
-- session_date), with the aligned sample count. Pairs with fewer than 3 aligned
-- observations are excluded (correlation undefined). The `corr` aggregate is
-- available in both DuckDB and Snowflake; the independent verifier recomputes these
-- with the exact Decimal Pearson implementation.
with r as (
    select instrument_symbol, session_date, daily_return
    from {{ ref('int_daily_returns') }}
),
pairs as (
    select
        a.instrument_symbol as symbol_a,
        b.instrument_symbol as symbol_b,
        a.daily_return as ret_a,
        b.daily_return as ret_b,
        a.session_date
    from r a
    join r b
        on a.session_date = b.session_date
       and a.instrument_symbol < b.instrument_symbol
)
select
    symbol_a,
    symbol_b,
    corr(ret_a, ret_b) as return_correlation,
    count(*) as aligned_sessions,
    min(session_date) as first_session,
    max(session_date) as last_session
from pairs
group by symbol_a, symbol_b
having count(*) >= 3
