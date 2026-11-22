{#
  Adapter-dispatched helpers for SQL that differs between DuckDB (operational)
  and Snowflake (optional). Default implementations target DuckDB; Snowflake
  variants are provided where the dialect diverges. Keeping dialect differences
  behind these macros lets the same model SQL compile for both backends.
#}

{# --- sample standard deviation ----------------------------------------- #}
{% macro strix_stddev_samp(expr) -%}
    {{ return(adapter.dispatch('strix_stddev_samp', 'strix_transform')(expr)) }}
{%- endmacro %}

{% macro default__strix_stddev_samp(expr) -%}
    stddev_samp({{ expr }})
{%- endmacro %}

{% macro snowflake__strix_stddev_samp(expr) -%}
    stddev_samp({{ expr }})
{%- endmacro %}

{# --- natural log (for log returns) ------------------------------------- #}
{% macro strix_ln(expr) -%}
    {{ return(adapter.dispatch('strix_ln', 'strix_transform')(expr)) }}
{%- endmacro %}

{% macro default__strix_ln(expr) -%}
    ln({{ expr }})
{%- endmacro %}

{% macro snowflake__strix_ln(expr) -%}
    ln({{ expr }})
{%- endmacro %}

{# --- whole-day difference between two dates (a - b) -------------------- #}
{% macro strix_date_diff_days(later, earlier) -%}
    {{ return(adapter.dispatch('strix_date_diff_days', 'strix_transform')(later, earlier)) }}
{%- endmacro %}

{% macro default__strix_date_diff_days(later, earlier) -%}
    date_diff('day', {{ earlier }}, {{ later }})
{%- endmacro %}

{% macro snowflake__strix_date_diff_days(later, earlier) -%}
    datediff('day', {{ earlier }}, {{ later }})
{%- endmacro %}

{# --- null-safe division (NULL when denominator is 0 or NULL) ---------- #}
{% macro strix_safe_divide(numerator, denominator) -%}
    {{ return(adapter.dispatch('strix_safe_divide', 'strix_transform')(numerator, denominator)) }}
{%- endmacro %}

{% macro default__strix_safe_divide(numerator, denominator) -%}
    case
        when {{ denominator }} is null or {{ denominator }} = 0 then null
        else ({{ numerator }}) / ({{ denominator }})
    end
{%- endmacro %}

{% macro snowflake__strix_safe_divide(numerator, denominator) -%}
    case
        when {{ denominator }} is null or {{ denominator }} = 0 then null
        else ({{ numerator }}) / ({{ denominator }})
    end
{%- endmacro %}

{# --- annualize a per-period volatility: vol * sqrt(periods_per_year) --- #}
{% macro strix_annualize_vol(period_vol, periods_per_year=252) -%}
    ({{ period_vol }}) * sqrt({{ periods_per_year }})
{%- endmacro %}
