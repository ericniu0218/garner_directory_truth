"""Train, backtest and score the "will this listing go stale?" model.

Two labels, both built from the following year's CMS file:

  stale  the provider's address changed OR the provider is no longer in the
         file (stopped billing Medicare, or fell under CMS's 11-patient
         reporting minimum). This is the label the product ranks by.
  moved  the provider is still in the file but at a different address.
         Stricter and cleaner, reported alongside for comparison.

Both are proxies for "the directory listing is wrong". Neither is ground truth.

Leakage rules:
  * Every feature for year t is built from data of year t or earlier (dbt).
  * The backtest trains on earlier years and evaluates on later years only.
  * The first two data years are used only to build history, never as training
    rows, so "years at this address" means the same thing in every row.

Usage:
  python -m directory_truth.model backtest   # time-split evaluation, writes metrics
  python -m directory_truth.model score      # retrain on all labeled years, score latest
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import psycopg
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from . import config

HISTORY_YEARS = 2  # leading data years used only as history
TEST_YEARS = 2     # most recent labeled years held out for the backtest
TOP_SPECIALTIES = 40

NUMERIC = [
    "tenure_capped",
    "moves_last_2y",
    "is_first_year",
    "has_suite",
    "log_providers_at_address",
    "log_tot_benes",
    "log_tot_services",
    "tot_hcpcs_codes",
    "bene_avg_age",
    "bene_avg_risk_score",
    "benes_yoy",
    "benes_yoy_missing",
    "address_departure_rate",
    "address_departure_missing",
    "log_address_arrivals",
    "address_is_new",
    "zip3_move_rate",
]
CATEGORICAL = ["entity_code", "specialty_group", "ruca_group", "medicare_participating"]


def load_features() -> pd.DataFrame:
    with psycopg.connect(config.DATABASE_URL) as conn:
        cur = conn.execute("select * from marts.provider_features")
        cols = [c.name for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def add_targets(df: pd.DataFrame) -> pd.DataFrame:
    """Add y_stale and y_moved. NaN where the label is not known."""
    df = df.copy()
    known = df["gone_next_year"].notna()
    gone = df["gone_next_year"].fillna(False).astype(bool)
    moved = df["moved_next_year"].fillna(False).astype(bool)
    df["y_stale"] = np.where(known, (gone | moved).astype(float), np.nan)
    df["y_moved"] = np.where(df["moved_next_year"].notna(), moved.astype(float), np.nan)
    return df


TARGETS = {"stale": "y_stale", "moved": "y_moved"}
# Providers with few Medicare patients often drop under CMS's reporting minimum,
# which looks like "gone". Metrics are also reported above this patient count so
# the headline is not just that artifact.
ROBUSTNESS_MIN_PATIENTS = 50


def top_specialties(df: pd.DataFrame) -> list[str]:
    return df["provider_type"].value_counts().head(TOP_SPECIALTIES).index.tolist()


def build_matrix(df: pd.DataFrame, specialties: list[str]) -> pd.DataFrame:
    """Turn mart columns into model inputs. Pure function of its arguments."""
    x = pd.DataFrame(index=df.index)
    # Cap at HISTORY_YEARS + 1 so the value never depends on how many years of
    # data happen to exist before the row's year.
    x["tenure_capped"] = df["tenure_years"].clip(upper=HISTORY_YEARS + 1).astype(float)
    x["moves_last_2y"] = df["moves_last_2y"].astype(float)
    x["is_first_year"] = df["is_first_year"].astype(float)
    x["has_suite"] = df["has_suite"].astype(float)
    x["log_providers_at_address"] = np.log1p(df["providers_at_address"].astype(float))
    x["log_tot_benes"] = np.log1p(df["tot_benes"].astype(float))
    x["log_tot_services"] = np.log1p(df["tot_services"].astype(float))
    x["tot_hcpcs_codes"] = df["tot_hcpcs_codes"].astype(float)
    x["bene_avg_age"] = df["bene_avg_age"].astype(float)
    x["bene_avg_risk_score"] = df["bene_avg_risk_score"].astype(float)
    yoy = df["benes_yoy"].astype(float)
    x["benes_yoy_missing"] = yoy.isna().astype(float)
    x["benes_yoy"] = yoy.clip(-1, 3).fillna(0.0)
    departure = df["address_departure_rate"].astype(float)
    x["address_departure_missing"] = departure.isna().astype(float)
    x["address_departure_rate"] = departure.fillna(0.0)
    x["log_address_arrivals"] = np.log1p(df["address_arrivals"].astype(float))
    x["address_is_new"] = df["address_is_new"].astype(float)
    x["zip3_move_rate"] = df["zip3_move_rate"].astype(float)
    x["entity_code"] = df["entity_code"].fillna("unknown")
    x["specialty_group"] = df["provider_type"].where(df["provider_type"].isin(specialties), "Other")
    x["ruca_group"] = df["ruca"].astype(str).str.split(".").str[0]
    x["medicare_participating"] = df["medicare_participating"].fillna("unknown")
    return x


def make_logistic() -> Pipeline:
    pre = ColumnTransformer(
        [
            ("num", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=50), CATEGORICAL),
        ]
    )
    return Pipeline([("pre", pre), ("clf", LogisticRegression(max_iter=2000, C=1.0))])


def make_boosting() -> Pipeline:
    pre = ColumnTransformer(
        [
            ("num", "passthrough", NUMERIC),
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=50, sparse_output=False), CATEGORICAL),
        ]
    )
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, random_state=0)
    return Pipeline([("pre", pre), ("clf", clf)])


@dataclass
class Split:
    train_years: list[int]
    test_years: list[int]
    score_year: int


def make_split(years: list[int]) -> Split:
    """years: every data year present, ascending. The last one has no label."""
    labeled = years[:-1]
    usable = labeled[HISTORY_YEARS:]
    if len(usable) <= TEST_YEARS:
        raise ValueError(f"need more than {HISTORY_YEARS + TEST_YEARS + 1} data years, got {years}")
    return Split(train_years=usable[:-TEST_YEARS], test_years=usable[-TEST_YEARS:], score_year=years[-1])


def ranking_metrics(y: np.ndarray, p: np.ndarray, weight: np.ndarray) -> dict:
    """How well does sorting by p find the listings that actually went stale?"""
    base = float(y.mean())
    order = np.argsort(-p)
    y_sorted = y[order]
    out = {
        "rows": int(len(y)),
        "positives": int(y.sum()),
        "base_rate": base,
        "roc_auc": float(roc_auc_score(y, p)),
        "average_precision": float(average_precision_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
    }
    capture = []
    for frac in (0.01, 0.05, 0.10, 0.20, 0.30, 0.50):
        k = max(1, int(round(frac * len(y))))
        hits = float(y_sorted[:k].sum())
        capture.append(
            {
                "review_fraction": frac,
                "reviewed": k,
                "precision": hits / k,
                "recall": hits / float(y.sum()),
                "lift": (hits / k) / base,
            }
        )
    out["capture"] = capture

    # The queue ranks by expected patients affected (p x patients). Measure how
    # much of the patient-weighted staleness that ordering finds, against random.
    # The fair comparison is "call the busiest providers first" (volume only),
    # because sorting by patient count alone already finds a lot.
    stale_patients = y * weight
    cum = np.cumsum(stale_patients[np.argsort(-(p * weight))]) / stale_patients.sum()
    cum_volume = np.cumsum(stale_patients[np.argsort(-weight)]) / stale_patients.sum()
    out["patient_weighted_capture"] = []
    for f in (0.01, 0.05, 0.10, 0.20, 0.30, 0.50):
        k = max(1, int(round(f * len(y)))) - 1
        out["patient_weighted_capture"].append(
            {
                "review_fraction": f,
                "share_of_affected_patients": float(cum[k]),
                "volume_only_baseline": float(cum_volume[k]),
                "random_baseline": f,
            }
        )

    # Calibration: within each predicted-risk decile, predicted vs observed rate.
    bins = pd.qcut(p, 10, labels=False, duplicates="drop")
    cal = pd.DataFrame({"bin": bins, "p": p, "y": y}).groupby("bin").agg(
        predicted=("p", "mean"), observed=("y", "mean"), n=("y", "size")
    )
    out["calibration"] = [
        {"predicted": float(r.predicted), "observed": float(r.observed), "n": int(r.n)} for r in cal.itertuples()
    ]
    return out


def backtest(df: pd.DataFrame) -> dict:
    years = sorted(df["data_year"].unique().tolist())
    split = make_split(years)
    df = add_targets(df)
    assert max(split.train_years) < min(split.test_years), "train must precede test"

    out = {
        "states": config.STATES,
        "train_years": split.train_years,
        "test_years": split.test_years,
        "labels": {
            "stale": "address changed, or provider absent from next year's CMS file",
            "moved": "provider present next year at a different address",
        },
        "targets": {},
    }
    for target, col in TARGETS.items():
        labeled = df[df[col].notna()]
        train = labeled[labeled["data_year"].isin(split.train_years)]
        test = labeled[labeled["data_year"].isin(split.test_years)]
        specialties = top_specialties(train)
        x_train, x_test = build_matrix(train, specialties), build_matrix(test, specialties)
        y_test = test[col].to_numpy().astype(int)
        weight = test["tot_benes"].fillna(0).to_numpy(dtype=float)
        robust = weight >= ROBUSTNESS_MIN_PATIENTS

        results = {}
        for name, make in (("logistic_regression", make_logistic), ("gradient_boosting", make_boosting)):
            p = make().fit(x_train, train[col].astype(int)).predict_proba(x_test)[:, 1]
            results[name] = ranking_metrics(y_test, p, weight)
            # Is the result stable, or carried by one test year?
            results[name]["by_test_year"] = []
            for year in split.test_years:
                in_year = (test["data_year"] == year).to_numpy()
                m = ranking_metrics(y_test[in_year], p[in_year], weight[in_year])
                top10 = next(c for c in m["capture"] if c["review_fraction"] == 0.10)
                results[name]["by_test_year"].append(
                    {"year": int(year), "rows": m["rows"], "base_rate": m["base_rate"], "roc_auc": m["roc_auc"],
                     "top10_precision": top10["precision"], "top10_lift": top10["lift"]}
                )
            results[name][f"patients_{ROBUSTNESS_MIN_PATIENTS}_plus"] = {
                k: v
                for k, v in ranking_metrics(y_test[robust], p[robust], weight[robust]).items()
                if k in ("rows", "base_rate", "roc_auc", "capture")
            }

        # One-rule baselines a person might use without a model.
        recent = x_test["moves_last_2y"].to_numpy() + 0.5 * x_test["is_first_year"].to_numpy()
        fewest_patients = -x_test["log_tot_benes"].to_numpy()
        for name, rule in (("baseline_moved_recently", recent), ("baseline_fewest_patients", fewest_patients)):
            rule_p = (rule - rule.min()) / (rule.max() - rule.min())
            results[name] = {
                k: v for k, v in ranking_metrics(y_test, rule_p, weight).items() if k in ("roc_auc", "average_precision", "capture")
            }
        out["targets"][target] = {"train_rows": int(len(train)), "models": results}
    return out


def explain(row: pd.Series) -> list[dict]:
    """Plain-language reasons for a reviewer. These are facts about the listing
    (not model internals), ordered roughly by how strongly each relates to moves."""
    reasons = []
    if row["moves_last_2y"] >= 1:
        n = int(row["moves_last_2y"])
        reasons.append({"code": "moved_recently", "text": f"Changed address {n} time{'s' if n > 1 else ''} in the last 2 years"})
    if row["is_first_year"]:
        reasons.append({"code": "new_to_data", "text": "First year in Medicare billing data"})
    elif row["tenure_years"] == 1 and row["moves_last_2y"] == 0:
        reasons.append({"code": "short_tenure", "text": "Only 1 year seen at this address"})
    if pd.notna(row["tot_benes"]) and row["tot_benes"] < 25:
        reasons.append({"code": "low_volume", "text": f"Only {int(row['tot_benes'])} Medicare patients this year (may stop appearing in billing data)"})
    dep = row["address_departure_rate"]
    if pd.notna(dep) and dep >= 0.2 and row["prev_residents_still_billing"] >= 3:
        reasons.append({"code": "colleagues_left", "text": f"{dep:.0%} of providers at this address last year have since moved"})
    yoy = row["benes_yoy"]
    if pd.notna(yoy) and yoy <= -0.25:
        reasons.append({"code": "volume_drop", "text": f"Patient volume down {abs(yoy):.0%} vs last year"})
    if pd.notna(yoy) and yoy >= 0.5:
        reasons.append({"code": "volume_jump", "text": f"Patient volume up {yoy:.0%} vs last year"})
    if row["providers_at_address"] >= 50:
        reasons.append({"code": "large_site", "text": f"{int(row['providers_at_address'])} providers list this address (large facility or billing address)"})
    if row["providers_at_address"] == 1:
        reasons.append({"code": "solo_address", "text": "No other provider lists this address"})
    if not reasons and row["tenure_years"] >= HISTORY_YEARS + 1:
        reasons.append({"code": "stable", "text": f"At this address for {int(row['tenure_years'])}+ years"})
    return reasons[:3]


def score(df: pd.DataFrame, model_name: str) -> pd.DataFrame:
    years = sorted(df["data_year"].unique().tolist())
    split = make_split(years)
    df = add_targets(df)
    current = df[df["data_year"] == split.score_year]
    make = make_boosting if model_name == "gradient_boosting" else make_logistic

    out = pd.DataFrame({"npi": current["npi"].to_numpy(), "data_year": split.score_year})
    for target, col in TARGETS.items():
        # Final models use every labeled year, including the backtest's test years.
        labeled = df[df[col].notna() & df["data_year"].isin(split.train_years + split.test_years)]
        specialties = top_specialties(labeled)
        fitted = make().fit(build_matrix(labeled, specialties), labeled[col].astype(int))
        out[f"p_{target}"] = fitted.predict_proba(build_matrix(current, specialties))[:, 1]
    out["risk_pct"] = out["p_stale"].rank(pct=True)
    out["expected_patients_affected"] = out["p_stale"] * current["tot_benes"].fillna(0).to_numpy(dtype=float)
    out["reasons"] = [json.dumps(explain(r)) for _, r in current.iterrows()]
    return out


def write_scores(scores: pd.DataFrame, model_version: str) -> None:
    schema_sql = (config.REPO_ROOT / "api" / "schema.sql").read_text()
    with psycopg.connect(config.DATABASE_URL) as conn:
        conn.execute(schema_sql)
        # Replace all scores inside one transaction so readers never see a partial set.
        conn.execute("delete from app.scores")
        with conn.cursor().copy(
            "copy app.scores (npi, data_year, p_stale, p_move, risk_pct, expected_patients_affected, reasons, model_version) from stdin"
        ) as copy:
            for r in scores.itertuples(index=False):
                copy.write_row((r.npi, r.data_year, r.p_stale, r.p_moved, r.risk_pct, r.expected_patients_affected, r.reasons, model_version))


def write_metrics(metrics: dict, model_version: str) -> None:
    config.ARTIFACTS_DIR.mkdir(exist_ok=True)
    (config.ARTIFACTS_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))
    schema_sql = (config.REPO_ROOT / "api" / "schema.sql").read_text()
    with psycopg.connect(config.DATABASE_URL) as conn:
        conn.execute(schema_sql)
        conn.execute(
            "insert into app.model_runs (model_version, metrics) values (%s, %s)",
            (model_version, json.dumps(metrics)),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=["backtest", "score", "all"])
    parser.add_argument("--model", default="gradient_boosting", choices=["gradient_boosting", "logistic_regression"])
    args = parser.parse_args()

    df = load_features()
    version = f"{args.model}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    if args.step in ("backtest", "all"):
        metrics = backtest(df)
        metrics["served_model"] = args.model
        write_metrics(metrics, version)
        for target, block in metrics["targets"].items():
            for name, m in block["models"].items():
                top10 = next(c for c in m["capture"] if c["review_fraction"] == 0.10)
                print(f"{target:6s} {name:26s} AUC={m['roc_auc']:.3f} top-10% precision={top10['precision']:.3f} "
                      f"recall={top10['recall']:.3f} lift={top10['lift']:.2f}x")
    if args.step in ("score", "all"):
        scores = score(df, args.model)
        write_scores(scores, version)
        print(f"scored {len(scores)} listings for {scores['data_year'].iloc[0]} with {version}")


if __name__ == "__main__":
    main()
