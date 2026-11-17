# How AI was used

This project was built with Claude Code. This file records what it did and how its output was checked,
because code I did not type is still code I am responsible for.

## What Claude Code did

- Researched public data sources and checked, before any code was written, that the yearly CMS files
  carry different addresses per year (the plan depended on it).
- Wrote the first version of every component: dlt ingestion, dbt models, the model code, the Go API,
  the React app, the Airflow DAG and the deployment files.

## How the output was checked

| Claim | Check |
|---|---|
| Loads do not duplicate rows | `pipeline/tests/test_ingest_idempotent.py` loads a file twice |
| Train years precede test years; the scored year is never trained on | `pipeline/tests/test_model.py` |
| One row per provider per year; labels missing only in the latest year; no partial downloads | dbt tests in `dbt/tests/` |
| API validation and confidence labels | `api/handlers_test.go` |
| The UI flow works | Clicked through in a browser: open a listing, save a check, confirm it leaves the queue and shows as verified |
| The DAG is valid | Loaded in Airflow 3.4 |

## Where the AI's first answer was wrong or weak

- The first model predicted "address changed" and was only 1.8x better than random. That number is in
  the README rather than hidden. The served label was broadened and the limits are stated next to it.
- Adding practice-level features was expected to help and did not. They remain in the model; the README
  says they did not move the result.
- A queue ordered purely by patients affected was dominated by large labs. The queue now covers
  clinicians in the riskiest 30% of listings. That policy is a judgment call and has not been backtested.
- A dbt macro had unbalanced parentheses and a database credential was missing; both were caught by
  running the pipeline, not by reading the code.

## Not yet verified

See the status table in the README. In particular the Claude note parser has not been run against the
API, so its accuracy is unknown.

## To do before presenting this as my own

- Read every file and be able to explain each design decision without notes.
- Run the note-parser eval and record the score.
- Review the 30 eval labels by hand; they were drafted by AI.
