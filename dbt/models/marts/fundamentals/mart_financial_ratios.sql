-- Grain: one row per (cik, fiscal_year, fiscal_period, period_type, ratio_name).
-- Financial ratios in LONG form, each preserving its numerator, denominator,
-- operator, formula, formula version, unit, reporting period, filing accession,
-- evidence anchor, availability (filed) date, and an explicit calculation_status.
-- Growth ratios are computed only against the prior-year SAME period/period_type, so
-- quarterly and annual grains never mix. Zero denominators and missing inputs are
-- surfaced as statuses, never as silent zeros.
{% set version = var('strix_calc_methodology_version', '1.0.0') %}
with a as (
    select
        *,
        lag(revenue) over (
            partition by cik, fiscal_period, period_type order by fiscal_year
        ) as revenue_py,
        lag(operating_income) over (
            partition by cik, fiscal_period, period_type order by fiscal_year
        ) as operating_income_py
    from {{ ref('int_financial_statement_alignment') }}
),
defs as (
    {% set ratios = [
      ('gross_profit_margin','divide','gross_profit / revenue','ratio','gross_profit','revenue'),
      ('operating_margin','divide','operating_income / revenue','ratio','operating_income','revenue'),
      ('net_profit_margin','divide','net_income / revenue','ratio','net_income','revenue'),
      ('return_on_equity','divide','net_income / shareholders_equity','ratio','net_income','shareholders_equity'),
      ('debt_to_equity','divide','long_term_debt / shareholders_equity','ratio','long_term_debt','shareholders_equity'),
      ('current_ratio','divide','current_assets / current_liabilities','ratio','current_assets','current_liabilities'),
      ('operating_cash_flow_margin','divide','operating_cash_flow / revenue','ratio','operating_cash_flow','revenue'),
      ('free_cash_flow','subtract','operating_cash_flow - capital_expenditures','currency','operating_cash_flow','capital_expenditures'),
      ('revenue_growth','growth','revenue / revenue_prior_year - 1','ratio','revenue','revenue_py'),
      ('operating_income_growth','growth','operating_income / operating_income_prior_year - 1','ratio','operating_income','operating_income_py')
    ] %}
    {% for name, op, formula, unit, num, den in ratios %}
    select
        cik, fiscal_year, fiscal_period, period_end, period_type,
        filed_date, accession, bronze_artifact_id,
        '{{ name }}' as ratio_name,
        '{{ op }}' as operator,
        '{{ formula }}' as formula,
        '{{ unit }}' as unit,
        cast({{ num }} as double) as numerator,
        cast({{ den }} as double) as denominator
    from a
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)
select
    cik, fiscal_year, fiscal_period, period_end, period_type,
    ratio_name, operator, formula,
    '{{ version }}' as formula_version,
    unit,
    numerator,
    denominator,
    case
        when numerator is null or denominator is null then null
        when operator = 'subtract' then numerator - denominator
        when denominator = 0 then null
        when operator = 'divide' then numerator / denominator
        when operator = 'growth' then numerator / denominator - 1
    end as ratio_value,
    case
        when numerator is null or denominator is null then 'insufficient_data'
        when operator in ('divide', 'growth') and denominator = 0 then 'undefined_zero_denominator'
        else 'computed'
    end as calculation_status,
    filed_date as available_at,
    accession,
    bronze_artifact_id
from defs
