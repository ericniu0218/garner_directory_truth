-- The listing we would show a member today: each provider's row from the most
-- recent data year. This is what gets scored and served by the API.
select f.*
from {{ ref('provider_features') }} f
where f.data_year = (select max(data_year) from {{ ref('provider_features') }})
