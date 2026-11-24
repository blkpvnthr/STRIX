-- Grain: one row per instrument over its full available window.
-- Drawdown summary: running peak at the latest session, current drawdown, maximum
-- drawdown over the window, the drawdown duration (sessions since the peak that
-- precedes the trough) and recovery duration (sessions from trough back to a new
-- peak, NULL if not yet recovered). Evaluation period is the instrument's full span.
with dd as (
    select
        instrument_symbol,
        session_date,
        session_index,
        close_price,
        running_peak,
        drawdown
    from {{ ref('int_rolling_drawdown') }}
),
spans as (
    select
        instrument_symbol,
        min(session_date) as first_session,
        max(session_date) as last_session,
        count(*) as session_count,
        min(drawdown) as max_drawdown
    from dd
    group by instrument_symbol
),
trough as (
    -- the session achieving the maximum drawdown (earliest if tied)
    select instrument_symbol, session_date as trough_date, session_index as trough_idx, drawdown
    from (
        select dd.*, s.max_drawdown,
               row_number() over (partition by dd.instrument_symbol
                                  order by dd.session_index) as rn
        from dd join spans s using (instrument_symbol)
        where dd.drawdown = s.max_drawdown
    ) t
    where rn = 1
),
latest as (
    select instrument_symbol, drawdown as current_drawdown, running_peak, close_price
    from (
        select dd.*, row_number() over (partition by instrument_symbol
                                        order by session_index desc) as rn
        from dd
    ) x
    where rn = 1
),
peak_before_trough as (
    -- last session at/above the pre-trough peak: the drawdown's starting point
    select t.instrument_symbol, max(dd.session_index) as peak_idx
    from trough t
    join dd on dd.instrument_symbol = t.instrument_symbol
            and dd.session_index <= t.trough_idx
            and dd.drawdown = 0
    group by t.instrument_symbol
),
recovery as (
    -- first session at/after the trough that returns to a non-negative drawdown
    select t.instrument_symbol, min(dd.session_index) as recovery_idx
    from trough t
    join dd on dd.instrument_symbol = t.instrument_symbol
            and dd.session_index > t.trough_idx
            and dd.drawdown >= 0
    group by t.instrument_symbol
)
select
    s.instrument_symbol,
    s.first_session as evaluation_start,
    s.last_session  as evaluation_end,
    s.session_count,
    l.close_price,
    l.running_peak,
    l.current_drawdown,
    s.max_drawdown,
    t.trough_date,
    (t.trough_idx - pbt.peak_idx)       as drawdown_duration_sessions,
    (r.recovery_idx - t.trough_idx)     as recovery_duration_sessions
from spans s
left join latest l using (instrument_symbol)
left join trough t using (instrument_symbol)
left join peak_before_trough pbt using (instrument_symbol)
left join recovery r using (instrument_symbol)
