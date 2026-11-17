-- Signals about the ADDRESS (not the provider), as of each year. A practice
-- that is relocating shows up as colleagues leaving the same address.
-- Backward-looking only: year t is described using years t-1 and t.
with hist as (
    select * from {{ ref('int_provider_address_history') }}
),

-- Providers who were at the address last year and are still billing this year:
-- what share of them now list a different address?
departures as (
    select
        h.data_year,
        h.prev_address_key                           as address_key,
        count(*)::int                                as prev_residents_still_billing,
        avg(h.moved_from_prev::float)                as address_departure_rate
    from hist h
    where h.prev_data_year = h.data_year - 1
    group by 1, 2
),

arrivals as (
    select
        data_year,
        address_key,
        sum(moved_from_prev)::int                    as address_arrivals,
        count(*)::int                                as providers_at_address
    from hist
    group by 1, 2
)

select
    a.data_year,
    a.address_key,
    a.providers_at_address,
    a.address_arrivals,
    d.address_departure_rate,
    coalesce(d.prev_residents_still_billing, 0)      as prev_residents_still_billing,
    (d.address_key is null)                          as address_is_new
from arrivals a
left join departures d
    on d.data_year = a.data_year and d.address_key = a.address_key
