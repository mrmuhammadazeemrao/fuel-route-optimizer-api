import math
import random

import numpy as np
import pytest
from scipy.optimize import linprog

from apps.routing.fuel import Candidate, NoFuelPlan, plan_fuel_stops

RANGE, MPG = 500, 10


def stations(*mile_price):
    return [Candidate(mile, price, ref=f"S{mile}") for mile, price in mile_price]


def stops(plan):
    return [(p.candidate.ref, round(p.gallons, 6)) for p in plan.purchases]


def test_short_trip_buys_only_what_is_needed():
    plan = plan_fuel_stops(stations((0, 3.0), (100, 3.5)), 300, RANGE, MPG)
    assert stops(plan) == [("S0", 30)]
    assert plan.total_cost == pytest.approx(90)


def test_buys_just_enough_to_reach_a_cheaper_station():
    plan = plan_fuel_stops(stations((0, 4.0), (200, 3.0), (450, 3.5)), 600, RANGE, MPG)
    # 20 gal to reach the cheaper station, then 40 gal there for the remaining 400 miles.
    assert stops(plan) == [("S0", 20), ("S200", 40)]
    assert plan.total_cost == pytest.approx(20 * 4.0 + 40 * 3.0)


def test_fills_up_when_nothing_cheaper_is_in_range():
    plan = plan_fuel_stops(stations((0, 3.0), (300, 3.6), (450, 3.4), (800, 3.9)), 900, RANGE, MPG)
    # Fill up (500 mi) at the cheap start, top up at the cheapest in range (mile 450)
    # just enough to finish: 900 - 450 = 450 mi needed, 50 mi left in the tank.
    assert stops(plan) == [("S0", 50), ("S450", 40)]


def test_skips_expensive_stations_when_a_cheaper_one_is_further_ahead():
    plan = plan_fuel_stops(stations((0, 3.5), (100, 3.9), (300, 3.8), (450, 3.0)), 900, RANGE, MPG)
    assert stops(plan) == [("S0", 45), ("S450", 45)]


def test_initial_leg_is_priced_at_the_first_station():
    plan = plan_fuel_stops(stations((20, 3.0)), 220, RANGE, MPG)
    assert plan.initial_gallons == pytest.approx(2)
    assert stops(plan) == [("S20", 20)]
    assert plan.total_gallons == pytest.approx(22)  # whole trip / MPG
    assert plan.total_cost == pytest.approx(66)


def test_gap_longer_than_range_is_reported():
    with pytest.raises(NoFuelPlan, match="after mile 0"):
        plan_fuel_stops(stations((0, 3.0), (600, 3.0)), 1000, RANGE, MPG)


def test_no_stations_is_reported():
    with pytest.raises(NoFuelPlan, match="No fuel stations"):
        plan_fuel_stops([], 100, RANGE, MPG)


def optimal_cost_lp(cands, trip):
    """Exact minimum via linear programming: x_i = miles of fuel bought at station i."""
    d = np.array([c.mile for c in cands]) - cands[0].mile
    p = np.array([c.price for c in cands])
    n, total = len(cands), trip - cands[0].mile
    lower = np.tril(np.ones((n, n)))  # row k sums purchases at stations 0..k
    # Arrive at station k (k >= 1) and at the finish with non-negative fuel.
    a_reach = -np.vstack([lower[:-1], np.ones(n)])
    b_reach = -np.append(d[1:], total)
    # Never exceed the tank after buying at station k.
    a_cap, b_cap = lower, d + RANGE
    result = linprog(
        p / MPG,
        A_ub=np.vstack([a_reach, a_cap]),
        b_ub=np.concatenate([b_reach, b_cap]),
        bounds=(0, None),
    )
    assert result.status == 0
    return result.fun + cands[0].mile / MPG * cands[0].price


@pytest.mark.parametrize("seed", range(300))
def test_greedy_matches_linear_programming_optimum(seed):
    rng = random.Random(seed)
    trip = rng.uniform(50, 3000)
    miles = sorted({0.0, *(rng.uniform(0, trip) for _ in range(rng.randint(1, 60)))})
    cands = stations(*((m, round(rng.uniform(2.7, 4.5), 3)) for m in miles))
    try:
        plan = plan_fuel_stops(cands, trip, RANGE, MPG)
    except NoFuelPlan:
        gaps = np.diff([c.mile for c in cands] + [trip])
        assert gaps.max() > RANGE
        return

    assert plan.total_gallons == pytest.approx(trip / MPG)
    assert all(p.gallons <= RANGE / MPG + 1e-9 for p in plan.purchases)
    assert plan.total_cost == pytest.approx(optimal_cost_lp(cands, trip), rel=1e-6)


def test_stop_cost_avoids_tiny_purchases():
    cands = stations((0, 3.50), (10, 3.45), (20, 3.40), (300, 3.0))
    assert len(plan_fuel_stops(cands, 600, RANGE, MPG).purchases) == 4
    plan = plan_fuel_stops(cands, 600, RANGE, MPG, stop_cost=10)
    # Saving 5 cents/gal on a 1-gallon top-up isn't worth a stop.
    assert stops(plan) == [("S0", 30), ("S300", 30)]


def brute_force_cost(cands, trip, stop_cost):
    """Try every subset of stations (first one is mandatory); zero-cost stops are optimal per
    subset, then charge stop_cost for each stop actually used."""
    best = math.inf
    rest = cands[1:]
    for mask in range(1 << len(rest)):
        subset = [cands[0]] + [c for k, c in enumerate(rest) if mask >> k & 1]
        try:
            plan = plan_fuel_stops(subset, trip, RANGE, MPG)
        except NoFuelPlan:
            continue
        used = {id(p.candidate) for p in plan.purchases} | {id(cands[0])}
        best = min(best, plan.total_cost + stop_cost * len(used))
    return best


@pytest.mark.parametrize("seed", range(150))
def test_stop_cost_plan_matches_brute_force(seed):
    rng = random.Random(seed)
    trip = rng.uniform(100, 1800)
    miles = sorted({0.0, *(rng.uniform(0, trip) for _ in range(rng.randint(1, 11)))})
    cands = stations(*((m, round(rng.uniform(2.7, 4.5), 3)) for m in miles))
    stop_cost = rng.choice([1, 5, 15, 40])
    try:
        plan = plan_fuel_stops(cands, trip, RANGE, MPG, stop_cost=stop_cost)
    except NoFuelPlan:
        assert math.isinf(brute_force_cost(cands, trip, stop_cost))
        return

    used = {id(p.candidate) for p in plan.purchases} | {id(cands[0])}
    assert plan.total_gallons == pytest.approx(trip / MPG)
    assert plan.total_cost + stop_cost * len(used) == pytest.approx(
        brute_force_cost(cands, trip, stop_cost), rel=1e-9
    )
