{#
  Use the custom schema name verbatim (staging / intermediate / marts / seeds)
  instead of dbt's default `<target_schema>_<custom>` concatenation, so the
  published analytical layer has stable, predictable schema names that the STRIX
  research tools and independent verifier can target directly.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
