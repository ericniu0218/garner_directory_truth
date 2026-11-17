-- gone_next_year must be known for every year except the latest one,
-- and must be unknown for the latest one (there is no "next year" yet).
select npi, data_year
from {{ ref('provider_features') }}
where (data_year = (select max(data_year) from {{ ref('provider_features') }}))
      <> (gone_next_year is null)
