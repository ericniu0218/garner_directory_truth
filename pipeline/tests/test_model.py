import numpy as np
import pandas as pd
import pytest

from directory_truth import model


def test_split_keeps_train_before_test_and_skips_history_years():
    split = model.make_split([2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024])
    assert split.train_years == [2019, 2020, 2021]
    assert split.test_years == [2022, 2023]
    assert split.score_year == 2024
    assert max(split.train_years) < min(split.test_years)
    # The score year has no label, so it must never be trained or tested on.
    assert split.score_year not in split.train_years + split.test_years


def test_split_rejects_too_few_years():
    with pytest.raises(ValueError):
        model.make_split([2020, 2021, 2022, 2023])


def test_targets():
    df = pd.DataFrame(
        {
            "gone_next_year": [False, False, True, None],
            "moved_next_year": [False, True, None, None],
        }
    )
    out = model.add_targets(df)
    # stayed, moved, gone, latest year (unknown)
    assert out["y_stale"].tolist()[:3] == [0.0, 1.0, 1.0]
    assert np.isnan(out["y_stale"].iloc[3])
    assert out["y_moved"].tolist()[:2] == [0.0, 1.0]
    # A provider who is gone has no "moved" label: we cannot see their address.
    assert np.isnan(out["y_moved"].iloc[2])


def _row(**overrides):
    base = {
        "tenure_years": 8, "moves_last_2y": 0, "is_first_year": False, "has_suite": True,
        "providers_at_address": 4, "tot_benes": 300, "tot_services": 900.0, "tot_hcpcs_codes": 20,
        "bene_avg_age": 72.0, "bene_avg_risk_score": 1.1, "benes_yoy": 0.02,
        "address_departure_rate": 0.0, "address_arrivals": 0, "address_is_new": False,
        "zip3_move_rate": 0.03, "entity_code": "I", "provider_type": "Cardiology",
        "ruca": "1", "medicare_participating": "Y", "prev_residents_still_billing": 4,
    }
    base.update(overrides)
    return base


def test_tenure_is_capped_so_it_means_the_same_in_every_year():
    df = pd.DataFrame([_row(tenure_years=3), _row(tenure_years=8)])
    x = model.build_matrix(df, ["Cardiology"])
    assert x["tenure_capped"].tolist() == [3.0, 3.0]


def test_missing_history_is_flagged_not_treated_as_zero_change():
    df = pd.DataFrame([_row(benes_yoy=None, address_departure_rate=None)])
    x = model.build_matrix(df, ["Cardiology"])
    assert x["benes_yoy_missing"].iloc[0] == 1.0
    assert x["address_departure_missing"].iloc[0] == 1.0


def test_reasons_are_plain_facts_about_the_listing():
    moved = pd.Series(_row(moves_last_2y=2, benes_yoy=-0.4))
    codes = [r["code"] for r in model.explain(moved)]
    assert codes[:2] == ["moved_recently", "volume_drop"]
    stable = pd.Series(_row())
    assert [r["code"] for r in model.explain(stable)] == ["stable"]
    assert len(model.explain(pd.Series(_row(moves_last_2y=1, is_first_year=True, tot_benes=12, benes_yoy=-0.9)))) <= 3


def test_perfect_ranking_scores_perfectly():
    y = np.array([1] * 10 + [0] * 90)
    p = np.linspace(1, 0, 100)
    m = model.ranking_metrics(y, p, np.ones(100))
    top10 = next(c for c in m["capture"] if c["review_fraction"] == 0.10)
    assert top10["precision"] == 1.0 and top10["recall"] == 1.0
    assert top10["lift"] == pytest.approx(10.0)
