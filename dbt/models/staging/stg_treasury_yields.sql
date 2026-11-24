-- Treasury par yields, standardized. yield_pct is expressed in PERCENT (e.g.
-- 4.25 = 4.25%). The unit is fixed and documented so downstream spread math never
-- silently mixes percent and basis points.
with src as (
    select * from {{ source('warehouse', 'fact_treasury_yields') }}
)
select
    silver_natural_key,
    date_key,
    observation_date,
    tenor,
    yield_pct,
    -- lineage
    source_code,
    silver_schema_version,
    bronze_artifact_id,
    source_locator,
    retrieved_at,
    silver_publication_id,
    row_signature
from src
