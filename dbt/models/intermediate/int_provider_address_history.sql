-- Address history per provider. Everything here looks BACKWARD from each row's
-- year only (lag and running windows), so these columns are safe to use as
-- model features for that year without leaking the future.
with base as (
    select * from {{ ref('stg_cms_provider_year') }}
),

flagged as (
    select
        *,
        lag(address_key) over w                       as prev_address_key,
        lag(data_year)   over w                       as prev_data_year,
        lag(tot_benes)   over w                       as prev_tot_benes,
        lag(tot_services) over w                      as prev_tot_services,
        case
            when lag(address_key) over w is null then 0
            when lag(address_key) over w <> address_key then 1
            else 0
        end                                           as moved_from_prev
    from base
    window w as (partition by npi order by data_year)
),

islands as (
    select
        *,
        sum(moved_from_prev) over (
            partition by npi order by data_year
            rows between unbounded preceding and current row
        )                                             as address_seq
    from flagged
)

select
    *,
    -- Years seen at the current address, up to and including this year.
    row_number() over (partition by npi, address_seq order by data_year)::int as tenure_years,
    -- Address changes seen so far (address_seq is the running count of moves).
    address_seq::int                                  as moves_prior,
    -- Address changes in this year and the one before. Unlike moves_prior this
    -- uses a fixed-length window, so it means the same thing in every year.
    sum(moved_from_prev) over (
        partition by npi order by data_year
        rows between 1 preceding and current row
    )::int                                            as moves_last_2y,
    row_number() over (partition by npi order by data_year)::int as years_observed
from islands
