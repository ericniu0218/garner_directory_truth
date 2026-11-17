"""Loading the same raw file twice must not duplicate rows."""
import gzip
import json

import psycopg
import pytest

from directory_truth import config, ingest


def _db_available() -> bool:
    try:
        psycopg.connect(config.DATABASE_URL, connect_timeout=2).close()
        return True
    except psycopg.Error:
        return False


@pytest.mark.skipif(not _db_available(), reason="Postgres is not running")
def test_load_twice_gives_same_rows(tmp_path, monkeypatch):
    import dlt

    monkeypatch.setattr(config, "RAW_URL", f"file://{tmp_path}")
    path = tmp_path / "cms_provider" / "year=2099"
    path.mkdir(parents=True)
    rows = [
        {"Rndrng_NPI": "T000000001", "Rndrng_Prvdr_St1": "1 Test St", "Rndrng_Prvdr_Zip5": "10001", "Tot_Benes": "40"},
        {"Rndrng_NPI": "T000000002", "Rndrng_Prvdr_St1": "2 Test St", "Rndrng_Prvdr_Zip5": "10002", "Tot_Benes": "55"},
    ]
    with gzip.open(path / "state=ZZ.jsonl.gz", "wt") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    # A throwaway dataset, so the test never touches real tables.
    dataset = "test_idempotent"
    pipeline = dlt.pipeline(
        pipeline_name="directory_truth_test",
        destination=dlt.destinations.postgres(credentials=config.DATABASE_URL),
        dataset_name=dataset,
        pipelines_dir=str(tmp_path / "dlt"),
    )
    try:
        for _ in range(2):
            pipeline.run(ingest.cms_provider_year([2099], ["ZZ"]))
        with psycopg.connect(config.DATABASE_URL) as conn:
            count, patients = conn.execute(
                f"select count(*), sum(tot_benes) from {dataset}.cms_provider_year"
            ).fetchone()
        assert count == 2
        assert patients == 95
    finally:
        with psycopg.connect(config.DATABASE_URL) as conn:
            conn.execute(f"drop schema if exists {dataset} cascade")
