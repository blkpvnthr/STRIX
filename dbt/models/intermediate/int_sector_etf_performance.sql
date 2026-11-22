-- Grain: one row per sector ETF present in the data.
-- Full-window price-return performance of each SPDR sector ETF and its performance
-- RELATIVE to SPY over ALIGNED sessions. Only sectors actually present appear; the
-- sector_rotation mart uses this to distinguish partial from complete coverage and
-- never publishes a complete ranking when sectors are missing.
{% set benchmark = var('strix_benchmark', 'SPY') %}
{% set sectors = "'XLK','XLF','XLE','XLY','XLP','XLV','XLI','XLU','XLB','XLRE','XLC'" %}
with last_cum as (
    select
        instrument_symbol,
        cumulative_return,
        row_number() over (
            partition by instrument_symbol order by session_index desc
        ) as rn,
        min(session_date) over (partition by instrument_symbol) as first_session,
        max(session_date) over (partition by instrument_symbol) as last_session,
        count(*) over (partition by instrument_symbol) as session_count
    from {{ ref('int_cumulative_returns') }}
),
window_return as (
    select
        instrument_symbol,
        cumulative_return as full_window_return,
        first_session,
        last_session,
        session_count
    from last_cum
    where rn = 1
),
bench as (
    select full_window_return as benchmark_return
    from window_return
    where instrument_symbol = '{{ benchmark }}'
),
sector_dim as (
    select sector_code, sector_name from {{ source('warehouse', 'dim_sector') }}
)
select
    sd.sector_code,
    sd.sector_name,
    w.full_window_return,
    b.benchmark_return,
    '{{ benchmark }}' as benchmark_symbol,
    w.full_window_return - b.benchmark_return as relative_return,
    w.first_session,
    w.last_session,
    w.session_count
from window_return w
join sector_dim sd on sd.sector_code = w.instrument_symbol
left join bench b on true
where w.instrument_symbol in ({{ sectors }})
