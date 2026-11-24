-- Source dimension, standardized (preserves source classifications).
with src as (
    select * from {{ source('warehouse', 'dim_source') }}
)
select
    source_code,
    source_name,
    category            as source_category
from src
