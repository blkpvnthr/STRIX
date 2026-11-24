{#
  Custom generic (schema) tests for STRIX business rules. Each returns the rows
  that VIOLATE the rule; dbt fails the test when any row is returned.

  Design notes:
  - These tests encode business invariants, NOT blunt sign checks. Negative
    accounting values (e.g. net losses, negative equity), negative economic rates,
    and negative returns are all legitimate and are never rejected here.
#}

{# A numeric column must fall within [min_value, max_value] (NULLs ignored). #}
{% test strix_in_range(model, column_name, min_value, max_value) %}
select {{ column_name }} as value
from {{ model }}
where {{ column_name }} is not null
  and ({{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }})
{% endtest %}

{#
  Look-ahead guard: a point-in-time observation's availability date must not be
  AFTER the date it is attributed to for selection. For SEC facts, filed_date is
  the availability date and must be >= period_end (you cannot file before the
  period closes, and a filing is not knowable before it is filed). Rows where the
  availability date precedes the observation period boundary indicate a
  look-ahead/metadata error.
#}
{% test strix_no_lookahead(model, available_date, event_date) %}
select {{ available_date }} as available_date, {{ event_date }} as event_date
from {{ model }}
where {{ available_date }} is not null
  and {{ event_date }} is not null
  and {{ available_date }} < {{ event_date }}
{% endtest %}

{#
  No duplicate fiscal period per (entity, concept, period, form): guards against
  double counting overlapping SEC observations within the SAME filing form. Rows
  returned are offending (entity, concept, period_key, form) groups with >1 row.
#}
{% test strix_unique_fiscal_period(model, entity_col, concept_col, period_col, form_col) %}
select
    {{ entity_col }} as entity,
    {{ concept_col }} as concept,
    {{ period_col }} as period_key,
    {{ form_col }} as form,
    count(*) as n
from {{ model }}
group by 1, 2, 3, 4
having count(*) > 1
{% endtest %}

{#
  Uniqueness over a combination of columns. Pass `combination_of_columns` as a
  list; returns column-tuples that occur more than once.
#}
{% test strix_unique_combination(model, combination_of_columns) %}
{% set cols = combination_of_columns | join(', ') %}
select {{ cols }}, count(*) as n
from {{ model }}
group by {{ cols }}
having count(*) > 1
{% endtest %}

{#
  Units consistency: every row for a given logical metric must share one unit.
  Returns metrics that resolve to more than one distinct unit.
#}
{% test strix_single_unit_per_metric(model, metric_col, unit_col) %}
select {{ metric_col }} as metric, count(distinct {{ unit_col }}) as units
from {{ model }}
where {{ unit_col }} is not null
group by 1
having count(distinct {{ unit_col }}) > 1
{% endtest %}
