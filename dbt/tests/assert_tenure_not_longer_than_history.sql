-- A provider cannot have been at an address longer than we have observed them.
select npi, data_year
from {{ ref('provider_features') }}
where tenure_years > years_observed or tenure_years < 1
