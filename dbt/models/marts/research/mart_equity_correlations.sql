-- Grain: one row per unordered instrument pair (symbol_a < symbol_b).
-- Aligned-session return correlations with full methodology metadata. Correlation is
-- Pearson on DAILY SIMPLE returns over sessions where BOTH instruments traded
-- (inner-join alignment); pairs with < 3 aligned sessions are excluded upstream.
-- Evidence per instrument resolves via warehouse lineage (symbol -> fact rows ->
-- Bronze); a single pair spans many artifacts, so no single evidence id is claimed.
select
    symbol_a,
    symbol_b,
    return_correlation,
    aligned_sessions,
    first_session as window_start,
    last_session as window_end,
    'pearson' as correlation_method,
    'daily_simple_returns' as return_definition,
    'inner_join_aligned_sessions' as missing_date_handling,
    'alpaca_adjustment_all' as source_feed
from {{ ref('int_cross_asset_correlation') }}
