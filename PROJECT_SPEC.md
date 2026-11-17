# Directory Truth: original plan

> **This is the plan written before the build, kept for the record. The README describes what was built.**
> Main differences: the served label became "moved or no longer in the billing data" because "moved" alone
> was only 1.75x better than random; NPPES was not ingested; recorded checks are stored but not yet used
> for retraining; Docker, Kubernetes and Terraform files exist but have not been run.

> Provider directories are accurate about 27% of the time (Garner's own number). This project estimates which
> provider listings are probably stale, tells a human which ones to verify first, and shows members how much to
> trust each listing.

Independent portfolio project inspired by Garner Health's published writing on directory accuracy. Uses only
public data. Not affiliated with Garner and uses no Garner data or branding.

## Why this project (the three tests)

| Test | How it passes |
|---|---|
| Ships end to end on Garner's stack | dlt -> Airflow -> dbt -> Postgres -> Go API -> React/TypeScript, deployed on Kubernetes, raw data landed in AWS S3, built with Claude Code. Every tool in the posting's "Technologies we use" list is used for a reason. |
| Shows real curiosity about their problem | Garner says it infers provider moves from billing signals (new zip codes, dropped new-patient visit codes) and manually verifies only Top Provider offices. This builds a public-data version of that loop: signals -> score -> prioritized human verification -> feedback. |
| Senior-engineer deep, one-sentence simple | Depth: incremental ingestion, history modeling, leakage-free time-split backtest, calibrated model, idempotent pipelines, human-in-loop. Pitch: "I rank which doctor listings to re-check first, and I can show it beats random." |

It also maps to the posting's own words: "helping our members find top doctors" (member search view),
"measurable outcomes, not just good intentions" (backtested lift number), and "use AI ... accountable for
outcomes" (Claude call-note parser with an eval suite, and an AI-usage log in the repo).

## What it does

1. **Ingest** public provider data with `dlt`:
   - CMS Medicare Physician & Other Practitioners, by Provider, one file per year via the data.cms.gov API.
     Each row has the provider's location (taken from NPPES that year) plus billing volume (`Tot_Benes`, etc.).
     Multiple years give a free address history plus billing trend, the closest public analog of Garner's claims signal.
   - NPPES monthly file (current addresses, last-update date, deactivations), filtered to a few states for dev.
   - Raw files land in S3 (MinIO locally), then load to Postgres. Loads are incremental and idempotent.
2. **Transform** with `dbt`: staging -> `provider_address_history` -> `provider_features` -> marts.
   Tests on every key; docs and lineage graph generated for the demo.
3. **Score**: for each provider-address, estimate P(address changes next year). Features are things like years
   at current address, billing trend, number of locations, specialty, entity type, state. Start with logistic
   regression (explainable), compare with gradient boosting. Each score ships with plain-English reasons
   ("billing down 35% vs last year", "moved twice in 5 years").
4. **Orchestrate** with Airflow: ingest -> dbt build -> dbt test -> train/score -> publish. One DAG, retries,
   data-quality gate that fails the run if row counts or null rates look wrong.
5. **Serve** with a Go API (Postgres via pgx): provider search, provider detail, verification queue, record outcome.
6. **UI** in React + TypeScript with two views:
   - *Member view*: search specialty + zip; each result shows a directory-confidence badge and "last verified".
   - *Verification queue* (the Concierge/ops side): ranked by expected value = P(stale) x member demand proxy
     (Medicare patient volume), with the reasons shown. Reviewer records the call outcome.
7. **Claude call-note parser** (small and bounded): reviewer pastes free-text notes ("front desk said Dr. Lee moved
   to 5th Ave, not taking new patients") and Claude returns structured fields (still at practice, new address,
   new phone, accepting new patients, confidence). The human confirms before anything is saved. An eval set of
   ~40 synthetic notes runs in CI and reports accuracy per field.
8. **Feedback loop**: confirmed outcomes become labels and are used in the next retrain.

## The headline number (this is what makes it credible)

Backtest with a time split: train on year t, predict address change by t+1, evaluate on later years only.
Report:
- Precision / recall in the top 10% of the queue vs random review (lift)
- Calibration plot (predicted vs actual rate)
- "With a reviewer capacity of N calls per week, the queue catches X% of stale listings vs Y% at random"

Do not write any of these numbers anywhere until they are measured. Do not claim the label equals "directory is
wrong"; it means "registered location changed", a proxy. Say so in the README.

## Architecture

```
data.cms.gov API --\                                   /-> Go API --> React/TS
NPPES monthly zip --+--> dlt --> S3 raw --> Postgres --+
                         (Airflow DAG)         |       \-> Claude parser (human-confirmed)
                                               +--> dbt (staging -> features -> marts) --> score job
                                                                                               |
                                    verification outcomes (labels) <---------------------------+
```

Deployment: Go API, React app and Postgres on a local `kind` Kubernetes cluster with manifests; Airflow via
Docker Compose first, moved to the cluster later; S3 bucket defined in Terraform.

## Build order (each step is demoable, so you always have something to show)

1. **Day 0 spike (do first, answers the main risk).** Confirm in the CMS data dictionary that each year's file
   has per-year address fields and that they differ across years; confirm field names (city/zip/street, `Tot_Benes`).
   If addresses are frozen to one snapshot, fall back to: accumulate NPPES monthly snapshots going forward, use
   cross-source disagreement (NPPES vs CMS Doctors & Clinicians file) and NPPES last-update age as features,
   and label with weekly incremental files. The README says which path was used.
2. **Vertical slice (days 1-3).** One state (NY), 2-3 specialties: dlt load -> dbt features -> baseline score ->
   Go `/queue` -> React queue page. Ugly is fine; end to end is the point.
3. **Credibility (days 4-6).** Backtest + calibration, dbt tests/docs, Airflow DAG with quality gate, member
   search view, Claude parser + eval suite.
4. **Polish (day 7+).** kind deployment, Terraform S3, README with architecture diagram, 2-minute screen recording,
   one-page write-up, `AI_USAGE.md` (where Claude Code helped, how each output was verified).

## Rules for the build

- Public data only. No scraping, no calling real offices. Reviewer outcomes in the demo are simulated.
- No fabricated metrics, and nothing in the README that implies Garner uses this or endorses it.
- Idempotent loads: re-running a DAG day must not duplicate rows (unit-test this).
- Keep a `CLAUDE.md` in the repo describing conventions, so the Claude Code workflow is visible.

## Interview material

**30-second pitch:** "Garner wrote that directories are right 27% of the time, and that you infer provider moves from
billing signals and verify only the top offices by hand. I built a public-data version: a pipeline that scores which
listings are probably stale, a queue that tells a human which to call first, and a backtest showing the queue beats
random review by X times."

**Questions a senior engineer will ask, with the honest answers to prepare:**
- *How do you avoid leakage?* Features come only from years <= t; evaluation only on later years.
- *Is "address changed" really "directory wrong"?* No, it is a proxy; with Garner's claims you would label on
  verified call outcomes, which is exactly what the feedback loop collects.
- *What breaks at 100x scale?* Full NPPES is about 7M rows: partition by state, incremental dbt models, and
  swap the batch score for a daily incremental job.
- *Why a human in the loop for the LLM?* Wrong phone numbers hurt members; the parser only proposes, and the eval
  suite measures how often it is right per field.
- *What would you do differently with real claims?* Use claims-derived signals (new billing zip, stopped billing
  new-patient visit codes) directly, calibrate on verified outcomes, and weight the queue by Top Provider status.

**Questions to ask them:** How do you measure whether a directory correction actually reached members? How does the
data platform team decide what runs in Airflow vs streaming? How do you use Claude Code on the data side?
