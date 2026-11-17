-- One row per provider per year: features known at the end of that year, plus
-- the label (what happened by the following year). The label is null for the
-- most recent year, which is the year we score.
with hist as (
    select * from {{ ref('int_provider_address_history') }}
),

max_year as (
    select max(data_year) as max_year from hist
),

next_year as (
    select npi, data_year, address_key, zip5 from hist
)

select
    h.npi,
    h.data_year,
    h.last_org_name,
    h.first_name,
    h.credentials,
    h.entity_code,
    h.street1,
    h.street2,
    h.city,
    h.state,
    h.zip5,
    h.zip3,
    h.provider_type,
    h.address_key,

    -- features
    h.tenure_years,
    h.moves_prior,
    h.moves_last_2y,
    h.years_observed,
    (h.years_observed = 1)                            as is_first_year,
    (h.street2 is not null)                           as has_suite,
    coalesce(c.providers_at_address, 1)               as providers_at_address,
    coalesce(c.address_arrivals, 0)                   as address_arrivals,
    c.address_departure_rate,                         -- null when nobody was here last year
    c.prev_residents_still_billing,
    c.address_is_new,
    z.zip3_move_rate,
    coalesce(h.ruca, 'unknown')                       as ruca,
    coalesce(h.medicare_participating, 'unknown')     as medicare_participating,
    h.tot_benes,
    h.tot_services,
    h.tot_hcpcs_codes,
    h.tot_medicare_payment,
    h.bene_avg_age,
    h.bene_avg_risk_score,
    case
        when h.prev_data_year = h.data_year - 1 and h.prev_tot_benes > 0
        then h.tot_benes::float / h.prev_tot_benes - 1
    end                                               as benes_yoy,
    case
        when h.prev_data_year = h.data_year - 1 and h.prev_tot_services > 0
        then h.tot_services / h.prev_tot_services - 1
    end                                               as services_yoy,

    -- labels (null when there is no following year of data yet)
    case
        when h.data_year = m.max_year then null
        when n.npi is null then null                  -- not in next year's file: see gone_next_year
        else (n.address_key <> h.address_key)
    end                                               as moved_next_year,
    case
        when h.data_year = m.max_year then null
        else (n.npi is null)
    end                                               as gone_next_year,
    case
        when h.data_year = m.max_year or n.npi is null then null
        else (n.zip5 is distinct from h.zip5)
    end                                               as moved_zip_next_year
from hist h
cross join max_year m
left join {{ ref('int_address_year_signals') }} c
    on c.data_year = h.data_year and c.address_key = h.address_key
left join {{ ref('int_zip3_year_signals') }} z
    on z.data_year = h.data_year and z.zip3 = h.zip3
left join next_year n
    on n.npi = h.npi and n.data_year = h.data_year + 1
