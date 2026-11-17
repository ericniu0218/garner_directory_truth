"""Directory Truth pipeline.

  land -> load -> dbt build (models + tests) -> backtest -> score

Every task is safe to re-run: land skips files it already has, load merges on
(npi, data_year), dbt rebuilds tables, and scoring replaces scores in one
transaction. `dbt build` is the data-quality gate: if a test fails (duplicate
keys, a year with half the expected rows, ...) the DAG stops before any new
scores are published, so the API keeps serving the last good run.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow import DAG

try:  # Airflow 3
    from airflow.providers.standard.operators.bash import BashOperator
except ImportError:  # Airflow 2
    from airflow.operators.bash import BashOperator

PROJECT_DIR = os.environ.get("DT_PROJECT_DIR", "/opt/directory-truth")
PIPELINE = f"cd {PROJECT_DIR}/pipeline && python -m"
DBT = f"cd {PROJECT_DIR}/dbt && dbt"

default_args = {
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="directory_truth",
    description="Ingest CMS provider data, build features, score stale listings",
    # CMS publishes a new data year roughly once a year. A weekly run costs
    # almost nothing because landing skips files that already exist.
    schedule="@weekly",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["directory-truth"],
) as dag:
    land = BashOperator(
        task_id="land_raw",
        bash_command=f"{PIPELINE} directory_truth.ingest land",
        execution_timeout=timedelta(hours=2),
    )
    load = BashOperator(
        task_id="load_postgres",
        bash_command=f"{PIPELINE} directory_truth.ingest load",
    )
    dbt_build = BashOperator(
        task_id="dbt_build_and_test",
        bash_command=f"{DBT} build --profiles-dir .",
        retries=0,  # a failed data test will not pass on retry
    )
    backtest = BashOperator(
        task_id="backtest",
        bash_command=f"{PIPELINE} directory_truth.model backtest",
    )
    score = BashOperator(
        task_id="score_current_listings",
        bash_command=f"{PIPELINE} directory_truth.model score",
    )

    land >> load >> dbt_build >> backtest >> score
