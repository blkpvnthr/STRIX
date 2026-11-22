-- Economic series dimension, standardized. source_code keeps BLS and FRED series
-- distinct so incompatible series are never merged by id alone.
with src as (
    select * from {{ source('warehouse', 'dim_economic_series') }}
)
select
    series_id,
    series_sk,
    source_code,
    frequency
from src
