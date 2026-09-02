"""Unit tests for the hazard module.

Everything above the Titan marker runs on constructed fleets and needs no
data file. The tests below the marker read the fetched dataset and are
skipped when it is absent --- skipping is fine *here* because the validation
registry refuses to skip: a missing file turns its Titan points red, so a
green registry still guarantees the anchor was measured. A unit test may be
polite; the registry may not.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "src")

from slicepacker.hazard import (  # noqa: E402
    Gpu,
    age_hazard,
    cohort_rates,
    evict_or_ride,
    hazard_threshold,
    load_titan,
    split_rank_recall,
)

TITAN = Path(__file__).resolve().parent.parent / "data" / "titan_gc_summary_loc.csv"


def make(batch: str, cage: int, years: float, dead: bool) -> Gpu:
    return Gpu(batch=batch, cage=cage, years=years, dead=dead)


# --- loader ----------------------------------------------------------------


def test_a_wrong_file_fails_loudly_not_as_an_empty_fleet(tmp_path):
    wrong = tmp_path / "wrong.csv"
    wrong.write_text("serial,lifetime\nx,1\n")
    with pytest.raises(ValueError, match="missing column"):
        load_titan(wrong)


def test_an_empty_fleet_is_refused(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("batch,cage,years,dead\n")
    with pytest.raises(ValueError, match="empty fleet"):
        load_titan(empty)


def test_a_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_titan(tmp_path / "absent.csv")


# --- cohort rates ----------------------------------------------------------


def test_cohort_rates_recover_a_constructed_rate():
    fleet = [make("old", 0, 2.0, True) for _ in range(3)] + [
        make("old", 0, 2.0, False) for _ in range(7)
    ]
    rate = cohort_rates(fleet, key=lambda g: g.batch)["old"]
    assert rate.deaths == 3
    assert rate.gpu_years == pytest.approx(20.0)
    assert rate.per_year == pytest.approx(0.15)


def test_cohorts_do_not_leak_into_each_other():
    fleet = [make("old", 0, 1.0, True), make("new", 0, 1.0, False)]
    rates = cohort_rates(fleet, key=lambda g: g.batch)
    assert rates["old"].per_year == pytest.approx(1.0)
    assert rates["new"].per_year == pytest.approx(0.0)


# --- age hazard ------------------------------------------------------------


def test_exposure_stops_at_the_bucket_boundary():
    # One GPU that lives exactly two years and dies at the end of them
    # contributes one GPU-year to each bucket and its death to the second.
    fleet = [make("old", 0, 730.0 / 365.25, True)]
    b1, b2 = age_hazard(fleet, [(0, 365), (365, 730)])
    assert b1.gpu_years == pytest.approx(1.0, abs=0.01)
    assert b1.deaths == 0
    assert b2.deaths == 1
    # the whole point: without the clamp, b1 would hold two years of exposure
    assert b1.gpu_years < 1.05


def test_survivors_carry_exposure_without_deaths():
    fleet = [make("old", 0, 4.0, False) for _ in range(10)]
    buckets = age_hazard(fleet, [(0, 365), (365, 730)])
    assert all(b.deaths == 0 and b.per_year == 0.0 for b in buckets)
    assert all(b.gpu_years == pytest.approx(10.0, rel=0.01) for b in buckets)


def test_an_inverted_bucket_is_refused():
    with pytest.raises(ValueError, match="inverted"):
        age_hazard([], [(365, 365)])


# --- the eviction inequality -----------------------------------------------


def test_the_threshold_is_where_the_two_costs_meet():
    t = hazard_threshold(90.0, 256.0, 8192.0)
    v = evict_or_ride(t, 90.0, 256.0, 8192.0)
    assert v.ride_cost == pytest.approx(v.evict_cost, rel=1e-9)


def test_a_drain_as_dear_as_the_rebuild_never_evicts():
    assert hazard_threshold(90.0, 8192.0, 8192.0) == math.inf
    assert evict_or_ride(100.0, 90.0, 8192.0, 8192.0).action == "ride"


def test_bad_inputs_are_refused():
    with pytest.raises(ValueError):
        hazard_threshold(0.0, 1.0, 2.0)
    with pytest.raises(ValueError):
        hazard_threshold(90.0, -1.0, 2.0)
    with pytest.raises(ValueError):
        evict_or_ride(-0.1, 90.0, 1.0, 2.0)


def test_zero_hazard_always_rides():
    v = evict_or_ride(0.0, 90.0, 1.0, 8192.0)
    assert v.action == "ride" and v.p_fail == 0.0


# --- ranking ---------------------------------------------------------------


def test_ranking_finds_a_constructed_bad_cohort():
    # Cohort ('old', 2) dies at 50%, everything else at 2%. A 25% budget
    # should capture far more than 25% of the deaths.
    fleet = []
    for i in range(400):
        fleet.append(make("old", 2, 2.0, i % 2 == 0))
    for i in range(1200):
        fleet.append(make("new", i % 3, 2.0, i % 50 == 0))
    rr = split_rank_recall(fleet, budget_frac=0.25, seed=7)
    assert rr.lift > 1.5


def test_the_split_is_deterministic_for_a_seed():
    fleet = [make("old", i % 3, 1.0 + i % 5, i % 4 == 0) for i in range(500)]
    a = split_rank_recall(fleet, budget_frac=0.3, seed=11)
    b = split_rank_recall(fleet, budget_frac=0.3, seed=11)
    assert a == b


def test_a_budget_outside_the_unit_interval_is_refused():
    with pytest.raises(ValueError):
        split_rank_recall([make("old", 0, 1.0, False)], budget_frac=1.0)


# --- Titan (skipped politely here; the registry is the impolite one) --------


needs_titan = pytest.mark.skipif(not TITAN.exists(), reason="run `make data`")


@needs_titan
def test_the_fetched_fleet_is_the_one_the_numbers_were_written_against():
    fleet = load_titan(TITAN)
    assert len(fleet) == 30_207
    assert sum(g.years for g in fleet) == pytest.approx(100_889, abs=5)


@needs_titan
def test_the_readme_ranking_figures_reproduce():
    fleet = load_titan(TITAN)
    rr = split_rank_recall(fleet, budget_frac=0.3, seed=20260902)
    assert rr.recall == pytest.approx(0.551, abs=0.005)
    assert rr.lift == pytest.approx(1.84, abs=0.02)
