-- Daily OHLCV bars, standardized. Prices are preserved exactly as stored
-- (DECIMAL(18,6)); no unit conversion or adjustment is applied here. Whether the
-- feed is split/dividend adjusted is a provider property carried downstream, not
-- altered in staging.
with src as (
    select * from {{ source('warehouse', 'fact_market_bars') }}
)
select
    silver_natural_key,
    date_key,
    symbol                              as instrument_symbol,
    session_date,
    observation_ts,
    open                               as open_price,
    high                               as high_price,
    low                                as low_price,
    close                              as close_price,
    volume,
    trade_count,
    vwap,
    -- lineage (preserved verbatim for source resolution)
    source_code,
    silver_schema_version,
    bronze_artifact_id,
    source_locator,
    retrieved_at,
    silver_publication_id,
    row_signature
from src
