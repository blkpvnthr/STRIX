-- Grain: one summary row.
-- Research/verification quality from WAREHOUSE-RESIDENT records only. The research
-- claim and verification fact tables are schema-only placeholders until DE-7, so
-- counts here are 0 and integration_status reports the deferral. This mart NEVER
-- fabricates research records; richer metrics (verdict breakdown, coverage, replay,
-- token/cost) arrive when DE-7 persists research runs into the warehouse.
with claims as (
    select count(*) as n from {{ source('warehouse', 'fact_research_claims') }}
),
ver as (
    select count(*) as n from {{ source('warehouse', 'fact_verification_results') }}
)
select
    claims.n as research_claim_rows,
    ver.n as verification_result_rows,
    cast(null as bigint) as verified_claims,
    cast(null as bigint) as contradicted_claims,
    cast(null as bigint) as insufficient_evidence_claims,
    cast(null as bigint) as unverifiable_claims,
    cast(null as bigint) as stale_claims,
    case
        when claims.n = 0 and ver.n = 0 then 'deferred_to_de7_no_warehouse_records'
        else 'partial'
    end as integration_status,
    'Research runs persist to the run store today; warehouse-resident research/'
      || 'verification facts (verdict breakdown, coverage, replay, tokens, cost) '
      || 'land in DE-7. Only genuinely available warehouse counts are shown here.'
      as note
from claims
cross join ver
