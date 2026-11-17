-- Fails if any provider has more than one row in a year.
select npi, data_year, count(*) as n
from {{ ref('provider_features') }}
group by 1, 2
having count(*) > 1
