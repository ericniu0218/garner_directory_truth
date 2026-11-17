-- One row per provider per year, with a normalized address key.
with src as (
    select * from {{ source('raw', 'cms_provider_year') }}
)

select
    npi,
    data_year::int                                   as data_year,
    last_org_name,
    first_name,
    credentials,
    entity_code,                                      -- I = individual, O = organization
    street1,
    street2,
    city,
    state,
    zip5,
    left(zip5, 3)                                     as zip3,
    ruca,
    provider_type,
    medicare_participating,
    tot_benes,
    tot_services,
    tot_hcpcs_codes,
    tot_medicare_payment,
    bene_avg_age,
    bene_avg_risk_score,
    {{ normalize_street('street1') }}                 as street1_norm,
    {{ normalize_street('street1') }} || '|' || coalesce(zip5, '') as address_key
from src
where npi is not null
