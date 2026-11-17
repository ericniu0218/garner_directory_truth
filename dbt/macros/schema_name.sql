{#
  Use the configured schema name as-is (staging, marts) instead of public_staging.
  schema_suffix lets a test build a second copy (for example marts_asof2021)
  without touching the real tables.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}{{ target.schema }}{%- else -%}{{ custom_schema_name | trim }}{{ var('schema_suffix', '') }}{%- endif -%}
{%- endmacro %}
