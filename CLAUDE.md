# Directory Truth: conventions

- Public data only. Never scrape sites or contact real provider offices; verification outcomes in the demo are `source = 'simulated'`.
- Never state a metric that was not produced by `make model`. Report weak results as they are.
- Features for year t may use data from year t or earlier only. Add a test when adding a feature that could leak.
- Every pipeline step must be safe to re-run.
- dbt owns `staging` and `marts`; the scoring job and API own `app.*` (`api/schema.sql`).
- Run `make test` before finishing a change. UI changes are checked in a browser.
- The Claude note parser only proposes values; a person confirms before anything is saved.
