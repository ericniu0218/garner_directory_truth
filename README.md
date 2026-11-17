# Directory Truth

Provider directories are often wrong: doctors move, retire, or stop taking patients, and the listing stays.
This project estimates which listings are probably out of date, tells a reviewer which ones to check
first, and shows members how much to trust each listing.

It is an independent project built on public CMS Medicare data for New York. It is not affiliated with
any company and uses no private data. It was motivated by Garner Health's public post on
[directory accuracy](https://garnerhealth.com/blog/directory-accuracy-for-high-value-health-plans), which
describes inferring provider moves from billing signals and manually verifying the listings that matter most.

## What it does

```
data.cms.gov API
      |  dlt: land raw files (local disk or S3), then merge into Postgres
      v
raw.cms_provider_year        658k rows: one per provider per year, 2017-2024
      |  dbt: address history, practice-level signals, labels, 20 data tests
      v
marts.provider_features  ->  model: backtest on later years, score the latest year
      |
      v
Go API  ->  React app
            - Review queue: doubtful listings, ordered by patients affected, with reasons
            - Find a doctor: each result carries a confidence label
            - How well it works: backtest results and their limits
            - Record a check: outcome is stored, the listing leaves the queue,
              and the member view shows "Verified"
```

Airflow runs the steps in order (`airflow/dags/directory_truth.py`). `dbt build` is the quality gate:
if a data test fails, no new scores are published.

## Results (backtest)

Trained on 2019-2021, tested on 2022-2023 (171,307 listings the model never saw). "Stale" means that a
year later the provider's address had changed or the provider no longer appeared in Medicare billing data.

| Approach, reviewing the top 10% | Share that went stale | Versus random |
|---|---|---|
| Gradient boosting (served) | 41.3% | 3.4x |
| Logistic regression | 37.2% | 3.1x |
| Rule: fewest patients first | 35.4% | 2.9x |
| Rule: moved recently first | 17.1% | 1.4x |
| Random review | 12.0% | 1.0x |

Reviewing the model's top 10% finds 34% of all stale listings. Predicted chances match what happened:
the riskiest tenth was predicted at 44% and came in at 41%.

### What the numbers do not show

- **The label is a proxy.** "Not in next year's billing data" includes providers who simply dropped below
  CMS's 11-patient reporting minimum. Among providers with 50 or more patients the model is weaker:
  2.8x better than random on a 7.7% base rate.
- **A simple rule gets most of the way.** "Fewest patients first" reaches 2.9x. The model adds to that,
  but modestly.
- **Predicting an address change alone is hard from public data:** 1.75x better than random. Adding
  practice-level signals (colleagues leaving the same address) did not improve it.
- **Queue ordering is mostly patient volume.** Ordering by expected patients affected finds 46% of affected
  patients in the first 10% of calls; calling the busiest providers first finds 42%.
- Addresses come from NPPES, a registry providers update themselves, so the "truth" here lags reality.
  With verified call outcomes as labels (what the feedback loop collects) the model could be trained on
  the real target.

All figures are reproduced by `make model` and written to `artifacts/metrics.json`.

## Run it locally

Needs `uv`, Go, Node and Postgres 16 (`brew install go postgresql@16`).

```bash
make db-init     # project-local Postgres on port 5433
make pipeline    # download CMS data (~15 min first time), dbt build, backtest, score
make api         # Go API on :8080
make web         # React app on :5173
make test        # Go tests, Python tests, TypeScript check
```

`DT_STATES=NY,NJ make pipeline` adds states. Set `RAW_URL=s3://bucket` to land raw files in S3.

## Design decisions

- **No leakage.** Every feature for year *t* uses data from *t* or earlier (dbt window functions only
  look backward). The backtest trains on earlier years and tests on later ones.
- **History years are not training rows.** With data starting in 2017, "years at this address" cannot
  exceed 1 in 2017. The first two years only build history and tenure is capped at 3, so the feature means
  the same thing in every training row.
- **Safe to re-run.** Landing skips files that exist and writes via a temp file. Loading merges on
  `(npi, data_year)`; a test loads the same file twice and checks the row count. Scores are replaced in one
  transaction.
- **Address normalization.** "123 Main Street, Suite 4" and "123 MAIN ST STE 4" are the same address;
  a dbt macro normalizes before comparing, so formatting changes do not count as moves.
- **A person's check outranks the model.** A verification from the last 180 days decides the member-facing
  label and removes the listing from the queue.
- **Reasons are facts, not model internals.** "Patient volume down 52% vs last year" is something a
  reviewer can check.
- **Claude only proposes.** The note parser (`api/parser.go`) turns free-text call notes into form fields
  using a strict tool schema. The reviewer confirms before anything is saved.

## Status: what is verified and what is not

| Piece | Status |
|---|---|
| Ingestion, dbt (20 tests), backtest, scoring | Run end to end on real data |
| Go API | Run against real data; unit tests pass |
| React app | Queue, record-a-check, and results page exercised in a browser |
| Airflow DAG | Parses on Airflow 3.4 with the expected task order; not yet executed by a scheduler |
| Claude note parser | Compiles and returns a clear error without a key. **Not yet run against the API**, so `evals/` (30 hand-written notes) has no score yet |
| Dockerfiles, docker-compose, Kubernetes manifests | Written and YAML-valid; **not yet built or applied** |
| Terraform (S3 bucket) | Written; **not yet applied** |
| S3 landing | Code path uses fsspec; only local disk has been exercised |

## Layout

```
pipeline/   Python: dlt ingestion, model, tests
dbt/        models (staging -> intermediate -> marts), macros, data tests
api/        Go API, schema, Claude note parser, tests
web/        React + TypeScript app
airflow/    DAG and image
evals/      note-parser eval set and runner
deploy/     Kubernetes manifests, Terraform
```

Data source: CMS, *Medicare Physician & Other Practitioners - by Provider* (public, data.cms.gov).
