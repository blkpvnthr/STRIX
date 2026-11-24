-- Warehouse load provenance: one row per Silver publication loaded. Exposed so
-- marts can stamp which publication versions they were built from.
with src as (
    select * from {{ source('warehouse', 'fact_pipeline_runs') }}
)
select
    silver_publication_id,
    dataset,
    source_code,
    row_count,
    published_at,
    load_execution_id,
    warehouse_loaded_at
from src
