-- Grain: one row per raw SEC observation (same as staging), annotated with filing
-- rank within its reporting slot so restatements are explicit, never silently
-- dropped. filed_rank_asc = 1 is the FIRST-FILED (original) value (point-in-time
-- honest); filed_rank_desc = 1 is the LATEST restatement. A reporting slot is
-- (cik, concept, unit, period_start, period_end) so an amended value for the same
-- period competes with its original rather than double counting.
with f as (
    select * from {{ ref('stg_company_financials') }}
)
select
    *,
    row_number() over (
        partition by cik, concept, unit, coalesce(cast(period_start as varchar), 'NA'), period_end
        order by filed_date asc, accession asc
    ) as filed_rank_asc,
    row_number() over (
        partition by cik, concept, unit, coalesce(cast(period_start as varchar), 'NA'), period_end
        order by filed_date desc, accession desc
    ) as filed_rank_desc
from f
