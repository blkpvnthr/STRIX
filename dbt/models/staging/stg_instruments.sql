-- Instrument dimension, standardized. name is NULL unless an authoritative source
-- provides it (never invented).
with src as (
    select * from {{ source('warehouse', 'dim_instrument') }}
)
select
    symbol              as instrument_symbol,
    instrument_sk,
    asset_class,
    name                as instrument_name
from src
