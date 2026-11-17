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
| Features never use future data | `pipeline/tests/test_no_leakage.py` rebuilds the models with later years removed and compares |
| Downloads are complete | Each file is compared with the row count the CMS API reports |
| Check outcomes behave correctly (moved, closed, unreachable) | `api/handlers_test.go`, against the real database |
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

## Flaws found in a later review pass

A second pass, reading the project as an interviewer would, found these and fixed them:

- A check with outcome "moved" still showed members the old address, and "no longer practicing" providers
  still appeared in search.
- "Could not reach the office" removed a listing from the queue for 180 days although nothing was settled.
- The "no leakage" claim rested on reading the SQL; there was no test.
- The download had no completeness check, although offset paging can drop rows.
- The README said "20 data tests"; there are 14 (plus 6 models).

## Not yet verified

See the status table in the README. The Docker, Kubernetes and Terraform files have not been run.

## Note parser eval

Run once against the live API: outcome 28/30, accepting-new-patients 29/30, no invented values. Two of the
three misses are the same-building suite-change case, where my labels were a judgment call, and the third
is a Medicare-only note. I did not edit the labels after seeing the result; the README reports the raw score
and explains each miss. The labels were drafted by AI, so the eval measures agreement with AI-drafted
labels, not with real call notes.

After that run I made the suite-change rule explicit in the parser prompt and relabeled the two
suite-change notes to match (history kept in `evals/call_notes.jsonl`). That is a policy decision made
after seeing the result, so a re-run on those two notes does not count as independent evidence. The
eval was re-run after the change: outcome 30/30, and the 28 unchanged notes scored as before, so nothing
regressed. The 30/30 is partly by construction and is not a measure of accuracy on new notes.

## To do before presenting this as my own

- Read every file and be able to explain each design decision without notes.
- Review the 30 eval labels by hand and decide the suite-change policy on its merits.
- The two eval runs did not record which model was used (the runner now saves it for future runs).
