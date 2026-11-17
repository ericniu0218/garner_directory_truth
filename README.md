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
      |  dbt: address history, practice-level signals, labels, 14 data tests
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
the riskiest tenth was predicted at 44% and came in at 41%. The result is not carried by one year:
3.4x on 2022 and 3.5x on 2023.

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
- **Only New York is loaded**, so a provider who moves to another state looks "gone", not "moved".
- **Recorded checks are not yet used for training.** They are stored as labels and change what members
  and reviewers see, but the model is still trained only on the CMS proxy label.
- **No sign-in.** The API has no authentication or rate limiting. Before any real use, the write
  endpoints and the note parser (each call costs money) would need both.
- Addresses come from NPPES, a registry providers update themselves, so the "truth" here lags reality.
  With verified call outcomes as labels (what the feedback loop collects) the model could be trained on
  the real target.

All figures are reproduced by `make model` and written to `artifacts/metrics.json`.

## Note parser eval

`make eval` sends 30 hand-written call notes through the real API path and compares each field with
the expected value (`evals/call_notes.jsonl`, report in `artifacts/parser_eval.json`). First run, default
model setting, labels unchanged after seeing the result:

| Field | Correct |
|---|---|
| outcome | 28/30 (93%) |
| accepting_new_patients | 29/30 (97%) |
| new street, ZIP, city, phone | 100% (fields the note leaves out came back empty every time, nothing was invented) |

The notes include a prompt-injection attempt ("ignore previous instructions...") and second-hand
information; the parser handled both as labeled.

The three misses:

- `confirmed-06`, `tricky-08`: the provider stays in the same building but the suite changed. The
  parser said "moved"; I had labeled both "confirmed". This is a product-policy question, not clearly a
  parser error: a changed suite changes where a patient walks in, so recording it as a plain
  confirmation would show "Verified" next to an out-of-date suite. The labels were my judgment calls.
- `confirmed-03`: "not accepting new Medicare patients, waitlist only". The parser returned "not stated"
  and I had labeled "no". The note is about Medicare patients only, so the parser's caution is defensible.

**Policy change made after seeing this result.** I then decided that a suite or floor change in the same
building counts as "moved", and wrote that rule into the parser prompt (`api/parser.go`). I relabeled
`confirmed-06` and `tricky-08` as "moved" to match. Because the labels now follow the parser's behavior on
those two notes, the 93% above is the honest first-run figure and any new score on those two notes is not
independent evidence. Second run, after the change: outcome 30/30, accepting_new_patients 29/30 (the
`confirmed-03` Medicare-only note again), everything else unchanged. The 28 notes whose labels did not
change scored exactly as before, so the new rule did not break them. The 30/30 on outcome is partly by
construction (I set the rule and the two labels together) and should not be quoted as accuracy.

Limits: 30 notes written by one person (drafted with AI) is a small sample, so 93% could easily be 85%
or 98% on other notes. The notes are synthetic and tidier than real call notes. Treat it as a smoke test.

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

- **No leakage, and a test that proves it.** Every feature for year *t* uses data from *t* or earlier.
  `pipeline/tests/test_no_leakage.py` rebuilds the dbt models as if the data ended in 2021 and checks that
  every feature for 2021 and earlier is identical to the full build. The backtest trains on earlier
  years and tests on later ones.
- **History years are not training rows.** With data starting in 2017, "years at this address" cannot
  exceed 1 in 2017. The first two years only build history and tenure is capped at 3, so the feature means
  the same thing in every training row.
- **Downloads are checked for completeness.** The CMS API pages by offset, which can silently drop or
  repeat rows. Each landed file must match the row count the API itself reports and contain no repeated
  provider, or it is discarded.
- **Safe to re-run.** Landing skips files that exist and writes via a temp file. Loading merges on
  `(npi, data_year)`; a test loads the same file twice and checks the row count. Scores are replaced in one
  transaction.
- **Address normalization.** "123 Main Street, Suite 4" and "123 MAIN ST STE 4" are the same address;
  a dbt macro normalizes before comparing, so formatting changes do not count as moves.
- **A person's check outranks the model.** A check from the last 180 days that reached the office decides
  what members see and removes the listing from the queue. "Moved" shows members the corrected address;
  "no longer practicing" removes the provider from member search. "Could not reach the office" settles
  nothing, so the listing returns to the queue after 7 days.
- **Reasons are facts, not model internals.** "Patient volume down 52% vs last year" is something a
  reviewer can check. They are rules written by hand, so they describe the listing; they are not an
  explanation of why the model gave that exact score.
- **Claude only proposes.** The note parser (`api/parser.go`) turns free-text call notes into form fields
  using a strict tool schema. The reviewer confirms before anything is saved.

## Status: what is verified and what is not

| Piece | Status |
|---|---|
| Ingestion, dbt (6 models, 14 data tests), backtest, scoring | Run end to end on real data |
| Go API | Run against real data; unit tests and a database-backed test of the check outcomes pass |
| React app | Queue, record-a-check, and results page exercised in a browser |
| Airflow DAG | Parses on Airflow 3.4 with the expected task order; not yet executed by a scheduler |
| Claude note parser | Run against the live API on 30 hand-written notes: outcome 28/30 (93%), see "Note parser eval" below |
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
