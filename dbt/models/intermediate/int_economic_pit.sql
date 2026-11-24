-- Grain: one row per (series_id, observation_date) selected as-of a cutoff.
-- Point-in-time economic selection: for series WITH a vintage (FRED), choose the
-- latest realtime_start <= strix_as_of. For series WITHOUT a vintage (BLS,
-- Treasury-sourced), vintage cannot be established, so STRICT point-in-time
-- selection excludes them (has_vintage = false) rather than treating observation
-- date as proof of availability. The non-strict path keeps them, labeled as
-- observation-date fallback. Default as-of is far future (latest known).
{% set as_of = var('strix_as_of', '9999-12-31') %}
{% set strict = var('strix_pit_strict', false) %}
with rev as (
    select * from {{ ref('int_economic_revisions') }}
),
vintaged as (
    -- FRED: latest vintage at or before the cutoff
    select
        series_id, observation_date, frequency, period, value,
        realtime_start, realtime_end, source_code, has_vintage,
        bronze_artifact_id, source_locator, silver_publication_id,
        row_number() over (
            partition by series_id, observation_date
            order by realtime_start desc
        ) as pick
    from rev
    where has_vintage
      and realtime_start <= date '{{ as_of }}'
),
no_vintage as (
    -- BLS etc.: no vintage. Included only in NON-strict mode, flagged as fallback.
    select
        series_id, observation_date, frequency, period, value,
        realtime_start, realtime_end, source_code, has_vintage,
        bronze_artifact_id, source_locator, silver_publication_id,
        1 as pick
    from rev
    where not has_vintage
)
select
    series_id, observation_date, frequency, period, value,
    realtime_start, realtime_end, source_code,
    has_vintage,
    not has_vintage as observation_date_fallback,
    bronze_artifact_id, source_locator, silver_publication_id
from vintaged
where pick = 1
{% if not strict %}
union all
select
    series_id, observation_date, frequency, period, value,
    realtime_start, realtime_end, source_code,
    has_vintage,
    not has_vintage as observation_date_fallback,
    bronze_artifact_id, source_locator, silver_publication_id
from no_vintage
{% endif %}
