"""Features for year t must not change when later years of data are removed.

Rebuilds the dbt models as if the data ended in a cutoff year (into separate
schemas), then compares every feature column for years <= cutoff with the real
build. Any difference means a feature looked at the future.
"""
import subprocess

import psycopg
import pytest

from directory_truth import config

CUTOFF = 2021
SUFFIX = f"_asof{CUTOFF}"
LABELS = {"moved_next_year", "gone_next_year", "moved_zip_next_year"}


def _ready() -> bool:
    try:
        with psycopg.connect(config.DATABASE_URL, connect_timeout=2) as conn:
            years = conn.execute("select count(distinct data_year) from marts.provider_features").fetchone()[0]
            return years >= 3
    except psycopg.Error:
        return False


@pytest.mark.skipif(not _ready(), reason="needs Postgres with the dbt marts built")
def test_features_do_not_depend_on_later_years():
    dbt_dir = config.REPO_ROOT / "dbt"
    try:
        subprocess.run(
            ["dbt", "run", "--profiles-dir", ".", "--target-path", f"target{SUFFIX}",
             "--vars", f"{{max_data_year: {CUTOFF}, schema_suffix: {SUFFIX}}}"],
            cwd=dbt_dir, check=True, capture_output=True, text=True,
        )
        with psycopg.connect(config.DATABASE_URL) as conn:
            cols = [
                r[0] for r in conn.execute(
                    "select column_name from information_schema.columns "
                    "where table_schema = 'marts' and table_name = 'provider_features'"
                )
            ]
            features = [c for c in cols if c not in LABELS]
            assert "tenure_years" in features and "address_departure_rate" in features

            full = f"select {', '.join(features)} from marts.provider_features where data_year <= {CUTOFF}"
            asof = f"select {', '.join(features)} from marts{SUFFIX}.provider_features"
            n_rows = conn.execute(f"select count(*) from ({asof}) t").fetchone()[0]
            diff = conn.execute(
                f"select count(*) from (({full} except {asof}) union all ({asof} except {full})) d"
            ).fetchone()[0]
            assert n_rows > 0
            assert diff == 0, f"{diff} feature rows change when years after {CUTOFF} are removed"

            # Sanity check that the comparison can fail: labels for the cutoff year
            # DO depend on the next year, so they must differ between the builds.
            known_full, known_asof = conn.execute(
                f"""select
                      (select count(*) from marts.provider_features where data_year = {CUTOFF} and gone_next_year is not null),
                      (select count(*) from marts{SUFFIX}.provider_features where data_year = {CUTOFF} and gone_next_year is not null)"""
            ).fetchone()
            assert known_full > 0 and known_asof == 0
    finally:
        with psycopg.connect(config.DATABASE_URL) as conn:
            conn.execute(f"drop schema if exists marts{SUFFIX} cascade")
            conn.execute(f"drop schema if exists staging{SUFFIX} cascade")
