"""Ingestion: CMS API -> raw files (local or S3) -> Postgres via dlt.

Two steps, both safe to re-run:

  land  Download one gzipped JSONL file per (year, state) into RAW_URL.
        A file that already exists is skipped, so a re-run downloads nothing.
  load  Read the raw files and merge them into Postgres on (npi, data_year),
        so a re-run never duplicates rows.

Usage:
  python -m directory_truth.ingest land
  python -m directory_truth.ingest load
"""
from __future__ import annotations

import argparse
import gzip
import json
import time
from typing import Iterator

import dlt
import fsspec
import requests

from . import config

# CMS field name -> our column name. Only the fields the models need.
FIELDS = {
    "Rndrng_NPI": "npi",
    "Rndrng_Prvdr_Last_Org_Name": "last_org_name",
    "Rndrng_Prvdr_First_Name": "first_name",
    "Rndrng_Prvdr_Crdntls": "credentials",
    "Rndrng_Prvdr_Ent_Cd": "entity_code",
    "Rndrng_Prvdr_St1": "street1",
    "Rndrng_Prvdr_St2": "street2",
    "Rndrng_Prvdr_City": "city",
    "Rndrng_Prvdr_State_Abrvtn": "state",
    "Rndrng_Prvdr_Zip5": "zip5",
    "Rndrng_Prvdr_RUCA": "ruca",
    "Rndrng_Prvdr_Type": "provider_type",
    "Rndrng_Prvdr_Mdcr_Prtcptg_Ind": "medicare_participating",
    "Tot_HCPCS_Cds": "tot_hcpcs_codes",
    "Tot_Benes": "tot_benes",
    "Tot_Srvcs": "tot_services",
    "Tot_Mdcr_Pymt_Amt": "tot_medicare_payment",
    "Bene_Avg_Age": "bene_avg_age",
    "Bene_Avg_Risk_Scre": "bene_avg_risk_score",
}


def raw_path(year: int, state: str) -> str:
    return f"{config.RAW_URL}/cms_provider/year={year}/state={state}.jsonl.gz"


def fetch_pages(year: int, state: str, session: requests.Session) -> Iterator[list[dict]]:
    """Yield pages of rows for one year and state from the CMS data API."""
    url = config.CMS_API.format(dataset_id=config.CMS_DATASET_IDS[year])
    offset = 0
    while True:
        params = {
            "filter[Rndrng_Prvdr_State_Abrvtn]": state,
            "size": config.PAGE_SIZE,
            "offset": offset,
        }
        for attempt in range(5):
            try:
                resp = session.get(url, params=params, timeout=120)
                resp.raise_for_status()
                page = resp.json()
                break
            except (requests.RequestException, ValueError):
                if attempt == 4:
                    raise
                time.sleep(2**attempt)
        if not page:
            return
        yield page
        if len(page) < config.PAGE_SIZE:
            return
        offset += config.PAGE_SIZE


def land(years: list[int], states: list[str], force: bool = False) -> None:
    session = requests.Session()
    for year in years:
        for state in states:
            path = raw_path(year, state)
            fs, fs_path = fsspec.core.url_to_fs(path)
            if fs.exists(fs_path) and not force:
                print(f"skip {path} (already landed)")
                continue
            fs.makedirs(fs_path.rsplit("/", 1)[0], exist_ok=True)
            n = 0
            # Write to a temp name, then rename, so a crash never leaves a
            # half-written file that a later run would mistake for complete.
            tmp = fs_path + ".tmp"
            with fs.open(tmp, "wb") as raw, gzip.open(raw, "wt") as out:
                for page in fetch_pages(year, state, session):
                    for row in page:
                        out.write(json.dumps(row) + "\n")
                    n += len(page)
            fs.mv(tmp, fs_path)
            print(f"landed {n:>7} rows -> {path}")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


@dlt.resource(
    name="cms_provider_year",
    write_disposition="merge",
    primary_key=("npi", "data_year"),
    columns={
        "npi": {"data_type": "text"},
        "data_year": {"data_type": "bigint"},
        "zip5": {"data_type": "text"},
        "ruca": {"data_type": "text"},
        "street2": {"data_type": "text"},
        "credentials": {"data_type": "text"},
        "tot_benes": {"data_type": "bigint"},
        "tot_services": {"data_type": "double"},
        "tot_hcpcs_codes": {"data_type": "bigint"},
        "tot_medicare_payment": {"data_type": "double"},
        "bene_avg_age": {"data_type": "double"},
        "bene_avg_risk_score": {"data_type": "double"},
    },
)
def cms_provider_year(years: list[int], states: list[str]) -> Iterator[dict]:
    numeric_int = {"tot_benes", "tot_hcpcs_codes"}
    numeric_float = {
        "tot_services",
        "tot_medicare_payment",
        "bene_avg_age",
        "bene_avg_risk_score",
    }
    for year in years:
        for state in states:
            with fsspec.open(raw_path(year, state), "rt", compression="gzip") as f:
                for line in f:
                    src = json.loads(line)
                    row: dict = {"data_year": year}
                    for cms_name, col in FIELDS.items():
                        value = _clean(src.get(cms_name))
                        if value is not None and col in numeric_int:
                            value = int(float(value))
                        elif value is not None and col in numeric_float:
                            value = float(value)
                        row[col] = value
                    yield row


def load(years: list[int], states: list[str]) -> None:
    pipeline = dlt.pipeline(
        pipeline_name="directory_truth",
        destination=dlt.destinations.postgres(credentials=config.DATABASE_URL),
        dataset_name="raw",
    )
    info = pipeline.run(cms_provider_year(years, states))
    print(info)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=["land", "load", "all"])
    parser.add_argument("--force", action="store_true", help="re-download existing files")
    args = parser.parse_args()
    if args.step in ("land", "all"):
        land(config.YEARS, config.STATES, force=args.force)
    if args.step in ("load", "all"):
        load(config.YEARS, config.STATES)


if __name__ == "__main__":
    main()
