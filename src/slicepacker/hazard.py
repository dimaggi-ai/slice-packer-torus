"""When to punch a chip out before it fails, measured on a fleet that existed.

Everything else in this repository prices what a failure costs *after* it
happens: the cordon, the shrink, the re-embed, the reconstitution plan. This
module asks the question that comes before those: given what a fleet's real
failure history says about a chip's cohort, is it cheaper to evict it now, on
purpose, or to ride until it fails on its own schedule?

The data is the Titan GPU lifetime dataset (Ostrouchov et al., SC '20): one
record per GPU for 30,207 units and just over 100,000 collective GPU-years,
released publicly by OLCF. Three of its facts carry the module:

1. **Hazard is not flat.** The old batch dies at ~0.001 per GPU-year in its
   first year and ~0.13 per GPU-year after year two --- a two-orders-of-magnitude
   climb, and explicitly *not* a bathtub: the paper reports no infant-mortality
   spike, just a slope that steepens mid-life. A fleet-uniform failure rate
   misprices almost every chip in the pod.
2. **Position is a covariate.** Within the old batch, deaths per GPU-year
   order by cage --- the machine's vertical cooling position --- at roughly
   3x between the bottom of the airflow path and the top. The paper's own
   conclusion is that cooling-air transport explains the ordering. That is the
   telemetry-fusion claim of W10 in miniature: where a chip sits in the
   thermal path predicts when it leaves.
3. **Ranking worked in production.** Titan's operators did not evict GPUs
   ahead of failure; they re-cut the job mix so larger jobs landed on more
   reliable nodes. :func:`split_rank_recall` reproduces the shape of that
   decision on held-out data: rank by cohort hazard estimated on one half of
   the fleet, and the top of the ranking on the other half captures far more
   of the deaths than its share of the chips.

And one negative result, stated up front because it is the honest headline:
at Titan's measured hazard levels, **per-chip preemptive eviction almost never
pays.** :func:`evict_or_ride` breaks even where the hazard over the decision
window times the unplanned cost equals the planned cost; even the worst cohort
here (old batch, top cage, past year two) sits well below that line unless a
planned drain is nearly free relative to an unplanned reconstitution. The
model's advice on this data is the advice Titan's operators took: spend the
hazard estimate on *placement* (which slice gets the risky chips), not on
*eviction*. The ledger says so; it did not have to.

Nothing here claims transfer of the rates. Titan was an air-cooled Cray XK7
with K20X parts and a known board defect driving the old batch's slope; a
liquid-cooled pod with different silicon earns different numbers. What is
claimed to transfer is the *shape*: cohort hazard beats fleet-uniform hazard,
and the decision inequality does not care where the hazard came from.
ASSUMPTIONS.md A12 records the boundary.

The CSV itself is fetched, not vendored: the upstream repository publishes the
data with a citation request and no license grant, so redistribution is not
ours to decide. ``make data`` pulls it from the canonical URL and verifies the
SHA-256 before anything reads it.
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Hashable, List, Sequence, Tuple

__all__ = [
    "Gpu",
    "Rate",
    "AgeBucket",
    "Verdict",
    "RankResult",
    "load_titan",
    "cohort_rates",
    "age_hazard",
    "hazard_threshold",
    "evict_or_ride",
    "split_rank_recall",
]

#: Canonical source for the dataset this module reads.
TITAN_URL = (
    "https://raw.githubusercontent.com/olcf/TitanGPULife/master/data/"
    "gc_summary_loc.csv"
)
#: SHA-256 of the file as fetched on 2026-09-02. ``make data`` verifies it.
TITAN_SHA256 = "07ece0f04e2bf20eb7c9e7eba05f6cd772ea89da08af5761be403635d3490ada"

#: Columns the loader insists on. The upstream file has more; these are the
#: ones the module reads, and a file missing any of them is not the dataset.
_REQUIRED = ("batch", "cage", "years", "dead")


@dataclass(frozen=True)
class Gpu:
    """One GPU's whole observed life, as the summary file records it."""

    batch: str  #: ``"old"`` or ``"new"`` --- which rework cohort installed it.
    cage: int   #: Vertical position in the cabinet's airflow path: 0, 1 or 2.
    years: float  #: Observed lifetime in years (censored if still in service).
    dead: bool  #: True if removed after a DBE or OTB event.


@dataclass(frozen=True)
class Rate:
    """Deaths per GPU-year for one cohort, with the exposure that backs it."""

    deaths: int
    gpu_years: float
    per_year: float


@dataclass(frozen=True)
class AgeBucket:
    """Hazard within one age interval, exposure-corrected.

    A GPU contributes exposure to a bucket only for the part of its life that
    fell inside the interval, and its death is counted in the bucket its life
    ended in. Skipping that correction inflates late-life hazard, because only
    survivors reach the late buckets at all.
    """

    lo_days: float
    hi_days: float
    deaths: int
    gpu_years: float
    per_year: float


@dataclass(frozen=True)
class Verdict:
    """What the eviction inequality says about one chip over one window."""

    action: str  #: ``"evict"`` or ``"ride"``.
    p_fail: float  #: Probability the chip fails inside the window.
    ride_cost: float  #: Expected cost of riding: ``p_fail * unplanned``.
    evict_cost: float  #: Cost of acting now: the planned drain, paid for sure.
    threshold_per_year: float  #: Hazard at which the two costs are equal.


@dataclass(frozen=True)
class RankResult:
    """How much of the held-out deaths the top of a hazard ranking captured."""

    budget_frac: float  #: Share of the held-out fleet the ranking may take.
    recall: float  #: Share of held-out deaths inside that budget.
    lift: float  #: ``recall / budget_frac``; 1.0 is a random pick.
    taken: int  #: Chips the ranking actually took.
    eval_deaths: int  #: Deaths in the whole held-out half.


def load_titan(path: str | Path) -> List[Gpu]:
    """Read the per-GPU summary file, strictly.

    Raises ``FileNotFoundError`` if the file is absent (run ``make data``) and
    ``ValueError`` if the header does not carry the columns this module reads
    --- a wrong file should fail loudly, not parse as an empty fleet.
    """
    path = Path(path)
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        missing = [c for c in _REQUIRED if c not in header]
        if missing:
            raise ValueError(
                f"{path} is not the Titan per-GPU summary: missing column(s) "
                f"{', '.join(missing)}"
            )
        fleet = [
            Gpu(
                batch=row["batch"],
                cage=int(row["cage"]),
                years=float(row["years"]),
                dead=row["dead"] == "TRUE",
            )
            for row in reader
        ]
    if not fleet:
        raise ValueError(f"{path} parsed to an empty fleet")
    return fleet


def cohort_rates(
    fleet: Sequence[Gpu], key: Callable[[Gpu], Hashable]
) -> Dict[Hashable, Rate]:
    """Deaths per GPU-year for each cohort ``key`` puts a GPU into.

    This is a whole-life rate: total deaths over total exposure. It is the
    right number for ranking cohorts against each other and deliberately not
    an age-resolved hazard --- :func:`age_hazard` exists for that.
    """
    deaths: Dict[Hashable, int] = {}
    exposure: Dict[Hashable, float] = {}
    for gpu in fleet:
        k = key(gpu)
        deaths[k] = deaths.get(k, 0) + (1 if gpu.dead else 0)
        exposure[k] = exposure.get(k, 0.0) + gpu.years
    return {
        k: Rate(deaths[k], exposure[k], deaths[k] / exposure[k] if exposure[k] else 0.0)
        for k in deaths
    }


def age_hazard(
    fleet: Sequence[Gpu], buckets_days: Sequence[Tuple[float, float]]
) -> List[AgeBucket]:
    """Exposure-corrected hazard per age interval, in deaths per GPU-year."""
    out: List[AgeBucket] = []
    for lo, hi in buckets_days:
        if hi <= lo:
            raise ValueError(f"bucket ({lo}, {hi}) is empty or inverted")
        exposure_years = 0.0
        deaths = 0
        for gpu in fleet:
            days = gpu.years * 365.25
            if days > lo:
                exposure_years += (min(days, hi) - lo) / 365.25
                if gpu.dead and lo < days <= hi:
                    deaths += 1
        per_year = deaths / exposure_years if exposure_years else 0.0
        out.append(AgeBucket(lo, hi, deaths, exposure_years, per_year))
    return out


def hazard_threshold(
    window_days: float, planned_cost: float, unplanned_cost: float
) -> float:
    """The hazard (per GPU-year) at which evicting and riding cost the same.

    Solves ``(1 - exp(-h * w)) * unplanned = planned`` for ``h``. When the
    planned cost is not below the unplanned cost there is no finite break-even
    --- riding can never lose --- and the function returns ``inf``.
    """
    if window_days <= 0:
        raise ValueError("the decision window must be positive")
    if planned_cost < 0 or unplanned_cost <= 0:
        raise ValueError("costs must be positive (planned may be zero)")
    ratio = planned_cost / unplanned_cost
    if ratio >= 1.0:
        return math.inf
    return -math.log(1.0 - ratio) * 365.25 / window_days


def evict_or_ride(
    hazard_per_year: float,
    window_days: float,
    planned_cost: float,
    unplanned_cost: float,
) -> Verdict:
    """Evict now, or ride the window and pay the unplanned price if it fails.

    Costs are in whatever unit the caller keeps their ledger in --- chip-hours
    in this repository's examples --- and only their ratio matters. The
    comparison is expected-value over one window and nothing more: no salvage
    value, no repeated windows, no correlation between chips. DECISIONS.md D16
    records why the one-window form was kept.
    """
    if hazard_per_year < 0:
        raise ValueError("hazard cannot be negative")
    p_fail = 1.0 - math.exp(-hazard_per_year * window_days / 365.25)
    ride = p_fail * unplanned_cost
    action = "evict" if planned_cost < ride else "ride"
    return Verdict(
        action=action,
        p_fail=p_fail,
        ride_cost=ride,
        evict_cost=planned_cost,
        threshold_per_year=hazard_threshold(window_days, planned_cost, unplanned_cost),
    )


def split_rank_recall(
    fleet: Sequence[Gpu],
    budget_frac: float = 0.3,
    seed: int = 20260902,
) -> RankResult:
    """Estimate cohort hazard on half the fleet, rank the other half with it.

    The split is random and seeded; cohorts are ``(batch, cage)``, the two
    fields the SC '20 paper identifies as the load-bearing covariates. The
    ranking takes whole cohorts in descending estimated rate and fills any
    partial cohort by seeded lottery, so the result is deterministic for a
    given seed. Recall is measured against the held-out half only --- the half
    the estimate never saw.

    This is deliberately the *placement* use of the hazard estimate, not the
    eviction use: it answers "which chips should the risk-tolerant job get"
    rather than "which chips should leave the pod".
    """
    if not 0.0 < budget_frac < 1.0:
        raise ValueError("budget_frac must be strictly between 0 and 1")
    rng = random.Random(seed)
    shuffled = list(fleet)
    rng.shuffle(shuffled)
    half = len(shuffled) // 2
    train, held = shuffled[:half], shuffled[half:]

    rates = cohort_rates(train, key=lambda g: (g.batch, g.cage))
    fallback = cohort_rates(train, key=lambda g: g.batch)

    def score(gpu: Gpu) -> float:
        rate = rates.get((gpu.batch, gpu.cage))
        if rate is not None:
            return rate.per_year
        base = fallback.get(gpu.batch)
        return base.per_year if base is not None else 0.0

    budget = int(round(budget_frac * len(held)))
    order = sorted(held, key=lambda g: (-score(g), rng.random()))
    taken = order[:budget]

    eval_deaths = sum(1 for g in held if g.dead)
    captured = sum(1 for g in taken if g.dead)
    recall = captured / eval_deaths if eval_deaths else 0.0
    actual_frac = len(taken) / len(held) if held else 0.0
    lift = recall / actual_frac if actual_frac else 0.0
    return RankResult(
        budget_frac=actual_frac,
        recall=recall,
        lift=lift,
        taken=len(taken),
        eval_deaths=eval_deaths,
    )
