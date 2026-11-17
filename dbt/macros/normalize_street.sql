{#
  Normalize a street line so that formatting differences between years
  ("123 Main Street, Suite 4" vs "123 MAIN ST STE 4") do not look like a move.
  Upper-case, drop punctuation, shorten common words, collapse spaces.
#}
{% macro normalize_street(col) -%}
{%- set words = [
    ('STREET', 'ST'), ('AVENUE', 'AVE'), ('BOULEVARD', 'BLVD'), ('ROAD', 'RD'),
    ('DRIVE', 'DR'), ('SUITE', 'STE'), ('NORTH', 'N'), ('SOUTH', 'S'),
    ('EAST', 'E'), ('WEST', 'W')
] -%}
{%- set ns = namespace(expr="regexp_replace(upper(coalesce(" ~ col ~ ", '')), '[^A-Z0-9 ]', ' ', 'g')") -%}
{%- for long, short in words -%}
  {%- set ns.expr = "regexp_replace(" ~ ns.expr ~ ", '\\m" ~ long ~ "\\M', '" ~ short ~ "', 'g')" -%}
{%- endfor -%}
trim(regexp_replace({{ ns.expr }}, '\s+', ' ', 'g'))
{%- endmacro %}
