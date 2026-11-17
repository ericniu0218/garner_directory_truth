"""Central configuration. Everything is overridable by environment variable."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://dt:dt@localhost:5433/directory_truth"
)

# Where raw API pages are landed before loading. A local path by default;
# set RAW_URL=s3://bucket/prefix (or point S3 at MinIO) to land in object storage.
RAW_URL = os.environ.get("RAW_URL", f"file://{REPO_ROOT / 'data' / 'raw'}")

STATES = os.environ.get("DT_STATES", "NY").split(",")

# CMS "Medicare Physician & Other Practitioners - by Provider", one dataset id per
# data year. Source: https://data.cms.gov/data.json (checked 2026-11-16).
CMS_DATASET_IDS = {
    2017: "44ea2789-993f-4d55-ac44-ed7f160b58fa",
    2018: "900850df-c9a9-47ce-a9e0-d0ceae5a811f",
    2019: "6a53afe5-1cbc-4b33-9dc8-926ee532dc66",
    2020: "29d799aa-c660-44fe-a51a-72c4b3e661ac",
    2021: "44e0a489-666c-4ea4-a1a2-360b6cdc19db",
    2022: "21555c17-ec1b-4e74-b2c6-925c6cbb3147",
    2023: "8ba584c6-a43a-4b0b-a35a-eb9a59e3a571",
    2024: "4d0b2df0-1e99-4db7-a574-a571d99217f1",
}
YEARS = [
    int(y) for y in os.environ.get("DT_YEARS", ",".join(map(str, CMS_DATASET_IDS))).split(",")
]

CMS_API = "https://data.cms.gov/data-api/v1/dataset/{dataset_id}/data"
PAGE_SIZE = 5000

ARTIFACTS_DIR = REPO_ROOT / "artifacts"
