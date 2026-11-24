-- SEC Company Facts observations, standardized. Values keep their reported unit
-- (unit column); no cross-unit conversion is performed. period_end is the event
-- date; filed_date is the known-availability date used for point-in-time.
with src as (
    select * from {{ source('warehouse', 'fact_company_financials') }}
)
select
    silver_natural_key,
    cik,
    taxonomy,
    concept,
    unit,
    period_start,
    period_end,
    filed_date,
    fiscal_year,
    fiscal_period,
    form,
    accession,
    frame,
    value,
    -- A period is a duration (10-K/10-Q flows) vs an instant (balance sheet) when
    -- period_start is null. Exposed so downstream models never mix the two.
    case when period_start is null then 'instant' else 'duration' end as period_kind,
    -- lineage
    source_code,
    silver_schema_version,
    bronze_artifact_id,
    source_locator,
    retrieved_at,
    silver_publication_id,
    row_signature
from src
