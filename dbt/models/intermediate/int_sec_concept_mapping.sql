-- Grain: one row per ranked SEC observation that maps to a canonical metric.
-- Joins ranked facts to the explicit sec_concept_map seed. Observations whose
-- concept has no mapping are intentionally excluded (that metric is simply
-- unavailable for the issuer) — no value is fabricated to fill a gap.
with f as (
    select * from {{ ref('int_financial_facts_ranked') }}
),
m as (
    select * from {{ ref('sec_concept_map') }}
)
select
    f.silver_natural_key,
    f.cik,
    f.taxonomy,
    f.concept,
    m.metric,
    m.statement,
    f.unit,
    f.period_start,
    f.period_end,
    f.period_kind,
    f.filed_date,
    f.fiscal_year,
    f.fiscal_period,
    f.form,
    f.accession,
    f.frame,
    f.value,
    f.filed_rank_asc,
    f.filed_rank_desc,
    f.bronze_artifact_id,
    f.source_locator,
    f.silver_publication_id
from f
join m
    on f.concept = m.concept
   and (m.taxonomy is null or f.taxonomy = m.taxonomy)
