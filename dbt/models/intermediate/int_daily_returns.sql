-- Grain: one row per (instrument_symbol, session_date) with a defined return.
-- Daily simple returns, the shared input for relative performance and correlation.
select
    instrument_symbol,
    session_date,
    session_index,
    close_price,
    daily_return,
    log_return,
    source_code,
    bronze_artifact_id
from {{ ref('int_market_daily') }}
where daily_return is not null
