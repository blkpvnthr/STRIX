-- Grain: one row per (instrument_symbol, session_date) for non-benchmark symbols.
-- Benchmark-relative daily returns vs SPY on ALIGNED trading sessions (inner join
-- on session_date), so only sessions where both traded contribute. The benchmark
-- is SPY; this is documented and configurable via the strix_benchmark var.
{% set benchmark = var('strix_benchmark', 'SPY') %}
with r as (
    select * from {{ ref('int_daily_returns') }}
),
bench as (
    select session_date, daily_return as benchmark_return
    from {{ ref('int_daily_returns') }}
    where instrument_symbol = '{{ benchmark }}'
)
select
    r.instrument_symbol,
    r.session_date,
    r.daily_return,
    bench.benchmark_return,
    '{{ benchmark }}' as benchmark_symbol,
    r.daily_return - bench.benchmark_return as excess_return
from r
join bench using (session_date)
where r.instrument_symbol <> '{{ benchmark }}'
