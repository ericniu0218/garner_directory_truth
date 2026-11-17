# Local development without Docker. Needs: uv, Go, Node, Postgres 16 (brew install go postgresql@16).
PG_BIN ?= /opt/homebrew/opt/postgresql@16/bin
PG_DATA := data/pg
export LC_ALL := en_US.UTF-8

.PHONY: db-init db-start db-stop ingest transform model pipeline api web test eval

db-init:  ## create a project-local Postgres on port 5433
	$(PG_BIN)/initdb -D $(PG_DATA) -U dt --auth=trust -E UTF8
	$(MAKE) db-start
	$(PG_BIN)/createdb -h localhost -p 5433 -U dt directory_truth

db-start:
	$(PG_BIN)/pg_ctl -D $(PG_DATA) -o "-p 5433 -k /tmp" -l data/pg.log start

db-stop:
	$(PG_BIN)/pg_ctl -D $(PG_DATA) stop

ingest:  ## download CMS data (skips files already landed) and load to Postgres
	cd pipeline && uv run python -m directory_truth.ingest all

transform:  ## build dbt models and run data tests
	cd dbt && uv run --project ../pipeline dbt build --profiles-dir .

model:  ## backtest, then score current listings
	cd pipeline && uv run python -m directory_truth.model all

pipeline: ingest transform model

api:  ## Go API on :8080
	cd api && go run .

web:  ## React dev server on :5173 (proxies /api to :8080)
	cd web && npm run dev

test:
	cd api && go test ./...
	cd pipeline && uv run pytest -q
	cd web && npx tsc -b

eval:  ## score the Claude note parser (API must be running with ANTHROPIC_API_KEY)
	python3 evals/run_eval.py
