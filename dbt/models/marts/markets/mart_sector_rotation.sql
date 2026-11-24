-- Grain: one row per sector ETF present (plus a coverage flag on every row).
-- Absolute and SPY-relative full-window performance of the 11 SPDR sector ETFs,
-- ranked by relative performance. sectors_present / 11 and is_complete_ranking make
-- partial coverage explicit: a ranking is only COMPLETE when all 11 sectors are
-- present. Consumers must not treat a partial ranking as a full sector ranking.
with s as (
    select * from {{ ref('int_sector_etf_performance') }}
),
cov as (
    select count(*) as sectors_present from s
)
select
    s.sector_code,
    s.sector_name,
    s.full_window_return,
    s.benchmark_return,
    s.benchmark_symbol,
    s.relative_return,
    rank() over (order by s.relative_return desc) as relative_rank,
    s.first_session,
    s.last_session,
    s.session_count,
    cov.sectors_present,
    11 as sectors_expected,
    (cov.sectors_present = 11) as is_complete_ranking
from s
cross join cov
