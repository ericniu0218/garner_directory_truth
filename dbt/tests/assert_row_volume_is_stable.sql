-- Data-quality gate: fail if any year has fewer than half the rows of the
-- year before it, which would point to a partial download.
with counts as (
    select data_year, count(*) as n from {{ ref('provider_features') }} group by 1
)
select c.data_year, c.n, p.n as prev_n
from counts c
join counts p on p.data_year = c.data_year - 1
where c.n < 0.5 * p.n
