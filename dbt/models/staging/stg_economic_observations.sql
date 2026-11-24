-- Economic observations (BLS + FRED), standardized. observation_date is the
-- period the value describes; realtime_start is the FRED vintage (known-at) date.
-- BLS rows carry no vintage (realtime_start is null) — a documented limitation,
-- never faked. Series are NOT combined here; source_code keeps feeds distinct.
with src as (
    select * from {{ source('warehouse', 'fact_economic_observations') }}
)
select
    silver_natural_key,
    series_id,
    observation_date,
    frequency,
    period,
    value,
    realtime_start,
    realtime_end,
    -- true when the row carries an explicit vintage (FRED); false for BLS.
    (realtime_start is not null) as has_vintage,
    -- lineage
    source_code,
    silver_schema_version,
    bronze_artifact_id,
    source_locator,
    retrieved_at,
    silver_publication_id,
    row_signature
from src
