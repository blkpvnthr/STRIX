-- Grain: one row per instrument (latest session snapshot).
-- Rolling annualized realized volatility over 5/10/20/60 trailing daily LOG returns.
-- Methodology: sample standard deviation (n-1) of daily log returns, annualized by
-- sqrt(252) trading days. Each window's sample size is reported; a window with fewer
-- than 2 samples is NULL (stddev undefined). Read any volatility WITH its sample size.
with v as (
    select
        iv.*,
        row_number() over (partition by iv.instrument_symbol order by iv.session_date desc) as rn
    from {{ ref('int_rolling_volatility') }} iv
)
select
    instrument_symbol,
    session_date as as_of_session,
    vol_5_annualized,
    vol_5_samples,
    vol_10_annualized,
    vol_10_samples,
    vol_20_annualized,
    vol_20_samples,
    vol_60_annualized,
    vol_60_samples,
    252 as annualization_trading_days,
    'sample_stddev_of_daily_log_returns' as methodology
from v
where rn = 1
