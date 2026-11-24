-- Grain: one row per (series_id, source_code, observation_date).
-- Per-series macro conditions in LONG form. Each series is classified by an
-- authoritative concept + seasonal-adjustment flag from the economic_series_map seed;
-- series are NEVER combined. observation_date is the PERIOD the value describes;
-- vintage_date (FRED realtime_start) is the known-at/release date — kept distinct.
-- Both percentage change (for index levels, i.e. inflation) and percentage-point
-- change (for rates) are provided; read the one appropriate to the concept/unit.
with pit as (
    select * from {{ ref('int_economic_pit') }}
),
mapped as (
    select
        p.*,
        m.concept,
        m.seasonal_adjustment,
        m.unit as concept_unit
    from pit p
    left join {{ ref('economic_series_map') }} m
        on p.series_id = m.series_id
       and p.source_code = m.source
),
seq as (
    select
        *,
        lag(value) over (partition by series_id, source_code order by observation_date) as prev_value
    from mapped
),
yoy as (
    select
        s.*,
        b.value as value_year_ago
    from seq s
    left join mapped b
        on s.series_id = b.series_id
       and s.source_code = b.source_code
       and b.observation_date = s.observation_date - interval 1 year
)
select
    series_id,
    source_code,
    coalesce(concept, 'unmapped') as concept,
    coalesce(seasonal_adjustment, 'UNKNOWN') as seasonal_adjustment,
    coalesce(concept_unit, 'unknown') as unit,
    observation_date,
    frequency,
    value,
    {{ strix_safe_divide('value', 'prev_value') }} - 1 as mom_pct,
    (value - prev_value) as mom_diff_pp,
    {{ strix_safe_divide('value', 'value_year_ago') }} - 1 as yoy_pct,
    (value - value_year_ago) as yoy_diff_pp,
    realtime_start as vintage_date,
    observation_date_fallback,
    bronze_artifact_id,
    source_locator,
    silver_publication_id
from yoy
