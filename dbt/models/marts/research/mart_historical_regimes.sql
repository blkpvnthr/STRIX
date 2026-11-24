-- Grain: one row per instrument (full-window regime feature vector).
-- Measurable, DESCRIPTIVE similarity features only: full-window price return,
-- annualized volatility, max drawdown, trend direction, plus coverage bounds and a
-- latest macro context snapshot (CPI YoY, 10y-2y spread). These features imply NO
-- prediction and establish NO causality — the disclaimer column states this. A
-- regime is only comparable to a historical window actually present in the data:
-- covers_2022 is true ONLY when the instrument's sessions span 2022, so no claim is
-- made about 2022 unless 2022 data has been ingested. Macro context uses scalar
-- subqueries so instruments are never dropped when macro data is absent.
with feat as (
    select * from {{ ref('int_market_regime_features') }}
)
select
    feat.instrument_symbol,
    feat.first_session as coverage_start,
    feat.last_session as coverage_end,
    feat.session_count,
    feat.full_window_return,
    feat.annualized_volatility,
    feat.max_drawdown,
    feat.trend_direction,
    (feat.first_session <= date '2022-12-31' and feat.last_session >= date '2022-01-01') as covers_2022,
    (
        select yoy_pct from {{ ref('mart_macro_conditions') }}
        where concept = 'cpi_index' and yoy_pct is not null
        order by observation_date desc limit 1
    ) as latest_cpi_yoy,
    (
        select spread_10y_2y_pp from {{ ref('mart_yield_curve') }}
        where spread_10y_2y_pp is not null
        order by observation_date desc limit 1
    ) as latest_10y_2y_spread_pp,
    'descriptive_features_only_no_prediction_no_causality' as disclaimer
from feat
