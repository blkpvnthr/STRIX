-- Grain: one row per first-filed (cik, metric, unit, period_start, period_end).
-- Point-in-time honest selection: keep only filed_rank_asc = 1 (the originally
-- filed value), so restated figures never overwrite the as-first-known value used
-- for historical correctness. A period_type classification (instant / quarter /
-- annual / ytd / other) is derived from the period length so marts can pick the
-- right grain and NEVER sum overlapping quarterly and year-to-date durations.
with mapped as (
    select * from {{ ref('int_sec_concept_mapping') }}
    where filed_rank_asc = 1
),
classified as (
    select
        *,
        case
            when period_kind = 'instant' then null
            else {{ strix_date_diff_days('period_end', 'period_start') }}
        end as period_length_days
    from mapped
)
select
    silver_natural_key,
    cik,
    metric,
    statement,
    concept,
    unit,
    period_start,
    period_end,
    period_kind,
    period_length_days,
    case
        when period_kind = 'instant' then 'instant'
        when period_length_days between 80 and 100 then 'quarter'
        when period_length_days between 350 and 380 then 'annual'
        when period_length_days between 150 and 300 then 'ytd'
        else 'other'
    end as period_type,
    filed_date,
    fiscal_year,
    fiscal_period,
    form,
    accession,
    frame,
    value,
    bronze_artifact_id,
    source_locator,
    silver_publication_id
from classified
