-- Grain: one row per (cik, fiscal_year, fiscal_period, period_end, period_type).
-- Authoritative SEC Company Facts, first-filed (point-in-time honest), aligned onto
-- one row per reporting period with canonical metric columns. period_type separates
-- instant/quarter/annual/ytd so overlapping durations are never summed. Issuer
-- taxonomy gaps surface as NULL metrics (never invented). company_name is from SEC
-- entityName when available, else NULL.
with a as (
    select * from {{ ref('int_financial_statement_alignment') }}
),
co as (
    select cik, company_name from {{ ref('stg_companies') }}
)
select
    a.cik,
    co.company_name,
    a.fiscal_year,
    a.fiscal_period,
    a.period_end,
    a.period_type,
    a.period_kind,
    a.filed_date,
    a.revenue,
    a.gross_profit,
    a.operating_income,
    a.net_income,
    a.total_assets,
    a.total_liabilities,
    a.shareholders_equity,
    a.operating_cash_flow,
    a.capital_expenditures,
    a.cash_and_equivalents,
    a.eps_diluted,
    a.eps_basic,
    a.long_term_debt,
    a.current_assets,
    a.current_liabilities,
    a.accession,
    a.bronze_artifact_id
from a
left join co using (cik)
