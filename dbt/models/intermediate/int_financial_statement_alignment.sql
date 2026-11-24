-- Grain: one row per (cik, fiscal_year, fiscal_period, period_end, period_type).
-- Aligns first-filed metrics onto a single row per reporting period by pivoting the
-- canonical metrics into columns. Only ONE value per (period, metric) is taken
-- (max over a single first-filed row), so quarterly and YTD durations — which have
-- different period_end/period_type — remain on separate rows and are never summed.
with sel as (
    select * from {{ ref('int_financial_period_selection') }}
)
select
    cik,
    fiscal_year,
    fiscal_period,
    period_end,
    period_type,
    period_kind,
    max(filed_date) as filed_date,
    max(case when metric = 'revenue' then value end)              as revenue,
    max(case when metric = 'gross_profit' then value end)         as gross_profit,
    max(case when metric = 'operating_income' then value end)     as operating_income,
    max(case when metric = 'net_income' then value end)           as net_income,
    max(case when metric = 'total_assets' then value end)         as total_assets,
    max(case when metric = 'total_liabilities' then value end)    as total_liabilities,
    max(case when metric = 'shareholders_equity' then value end)  as shareholders_equity,
    max(case when metric = 'operating_cash_flow' then value end)  as operating_cash_flow,
    max(case when metric = 'capital_expenditures' then value end) as capital_expenditures,
    max(case when metric = 'cash_and_equivalents' then value end) as cash_and_equivalents,
    max(case when metric = 'eps_diluted' then value end)          as eps_diluted,
    max(case when metric = 'eps_basic' then value end)            as eps_basic,
    max(case when metric = 'long_term_debt' then value end)       as long_term_debt,
    max(case when metric = 'current_assets' then value end)       as current_assets,
    max(case when metric = 'current_liabilities' then value end)  as current_liabilities,
    -- carry one lineage anchor per period row for evidence resolution
    max(bronze_artifact_id) as bronze_artifact_id,
    max(accession) as accession
from sel
group by cik, fiscal_year, fiscal_period, period_end, period_type, period_kind
