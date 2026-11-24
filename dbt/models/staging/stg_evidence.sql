-- Evidence dimension, standardized: one row per Bronze artifact referenced by
-- facts. evidence_id is the Bronze artifact id used for source-to-claim lineage.
with src as (
    select * from {{ source('warehouse', 'dim_evidence') }}
)
select
    evidence_id,
    source_code,
    content_hash,
    retrieved_at
from src
