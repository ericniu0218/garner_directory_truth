-- Application tables. dbt owns staging/marts; the scoring job and the API own app.*.
-- Several API replicas and the scoring job may apply this file at the same
-- time. "create ... if not exists" can still collide when run concurrently, so
-- take a transaction-scoped lock first.
select pg_advisory_xact_lock(7426001);

create schema if not exists app;

-- One row per provider listing in the latest data year, replaced on every scoring run.
create table if not exists app.scores (
    npi                         text primary key,
    data_year                   int not null,
    p_stale                     double precision not null,  -- P(address changes or provider stops billing within a year)
    p_move                      double precision not null,  -- P(address changes within a year), stricter label
    risk_pct                    double precision not null,  -- percentile of p_stale, 0..1
    expected_patients_affected  double precision not null,  -- p_stale * Medicare patients seen
    reasons                     jsonb not null,
    model_version               text not null,
    scored_at                   timestamptz not null default now()
);

-- Outcome of a human check on a listing. These rows are the feedback labels.
create table if not exists app.verifications (
    id                      bigserial primary key,
    npi                     text not null,
    outcome                 text not null check (outcome in ('confirmed', 'moved', 'closed', 'unreachable')),
    new_street              text,
    new_city                text,
    new_zip                 text,
    new_phone               text,
    accepting_new_patients  boolean,
    notes                   text,
    source                  text not null default 'manual',  -- manual | simulated
    created_at              timestamptz not null default now()
);
create index if not exists verifications_npi_idx on app.verifications (npi, created_at desc);

-- Backtest metrics for each training run, shown in the UI.
create table if not exists app.model_runs (
    id             bigserial primary key,
    model_version  text not null,
    metrics        jsonb not null,
    created_at     timestamptz not null default now()
);
