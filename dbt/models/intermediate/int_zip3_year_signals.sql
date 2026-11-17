-- Share of providers in each 3-digit zip area who changed address coming into
-- this year. Backward-looking: compares year t-1 to year t.
select
    data_year,
    zip3,
    avg(moved_from_prev::float) as zip3_move_rate
from {{ ref('int_provider_address_history') }}
where prev_data_year = data_year - 1
group by 1, 2
