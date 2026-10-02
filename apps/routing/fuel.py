"""Cheapest refuelling plan along a fixed route (the "gas station problem").

Minimizes fuel cost + `stop_cost` per stop. `stop_cost` stands for the time a stop takes, so the
plan doesn't stop to save a few cents; it isn't included in the reported fuel cost.

Exact dynamic program based on Khuller, Malekian & Mestre, "To fill or not to fill: the gas
station problem" (2011). In an optimal plan, leaving stop i for next stop j, the truck either
fills the tank at i (when i is cheaper than j) or buys just enough to reach j (otherwise). So
it arrives at j either empty or with `range - distance(i, j)` left, which keeps the state space
small: O(n * m log m) for n stations with at most m of them within range of each other.

Assumption: the truck starts with an empty tank, so every mile of the trip is paid for. The first
station along the route is the first stop, and the fuel for the short drive from the start to it
is priced at that station.
"""

import bisect
import math
from dataclasses import dataclass, field
from typing import Any


class NoFuelPlan(Exception):
    pass


@dataclass(frozen=True)
class Candidate:
    mile: float  # distance from the start along the route
    price: float  # USD per gallon
    ref: Any  # caller's object (e.g. the station), passed through untouched


@dataclass(frozen=True)
class Purchase:
    candidate: Candidate
    gallons: float

    @property
    def cost(self) -> float:
        return self.gallons * self.candidate.price


@dataclass(frozen=True)
class FuelPlan:
    purchases: list[Purchase]
    initial_gallons: float  # fuel to reach the first stop, priced at the first stop
    initial_cost: float
    total_gallons: float = field(init=False)
    total_cost: float = field(init=False)

    def __post_init__(self):
        object.__setattr__(
            self, "total_gallons", self.initial_gallons + sum(p.gallons for p in self.purchases)
        )
        object.__setattr__(
            self, "total_cost", self.initial_cost + sum(p.cost for p in self.purchases)
        )


def plan_fuel_stops(
    candidates: list[Candidate],
    trip_miles: float,
    range_miles: float,
    mpg: float,
    stop_cost: float = 0.0,
) -> FuelPlan:
    """`candidates` must be sorted by mile. Inside the planner, fuel is counted in miles."""
    stations = [c for c in candidates if c.mile < trip_miles]
    if not stations:
        raise NoFuelPlan("No fuel stations found along the route.")
    _check_gaps(stations, trip_miles, range_miles)

    planner = _Planner(stations, trip_miles, range_miles, mpg, stop_cost)
    first = stations[0]
    initial_gallons = first.mile / mpg
    return FuelPlan(planner.purchases(), initial_gallons, initial_gallons * first.price)


def _check_gaps(stations: list[Candidate], trip_miles: float, range_miles: float) -> None:
    if stations[0].mile > range_miles:
        raise NoFuelPlan(f"No fuel station within {range_miles:.0f} miles of the start.")
    next_miles = [c.mile for c in stations[1:]] + [trip_miles]
    for here, next_mile in zip(stations, next_miles, strict=True):
        if next_mile - here.mile > range_miles:
            raise NoFuelPlan(
                f"No fuel station within {range_miles:.0f} miles after mile {here.mile:.0f}."
            )


@dataclass
class _Options:
    """Moves out of one station that don't depend on the fuel left on arrival."""

    can_finish: bool = False
    # Best "fill up here, next stop is a pricier j": stop_cost + cost_to_go(j, range - d).
    fill_cost: float = math.inf
    fill_next: int | None = None
    # "Buy just enough to reach a cheaper-or-equal j", sorted by distance d to j, as suffix
    # minima of d * unit_price + stop_cost + cost_to_go(j, 0); arrival fuel g only requires d > g.
    just_dist: list[float] = field(default_factory=list)
    just_best: list[tuple[float, int]] = field(default_factory=list)


class _Planner:
    def __init__(self, stations, trip_miles, range_miles, mpg, stop_cost):
        self.stations = stations
        self.trip = trip_miles
        self.range = range_miles
        self.mpg = mpg
        self.stop_cost = stop_cost
        self.unit = [c.price / mpg for c in stations]  # USD per mile of range
        self.options = [_Options() for _ in stations]
        for i in reversed(range(len(stations))):
            self._build_options(i)

    def _build_options(self, i: int) -> None:
        here, opt = self.stations[i], self.options[i]
        opt.can_finish = self.trip - here.mile <= self.range
        just = []
        for j in range(i + 1, len(self.stations)):
            d = self.stations[j].mile - here.mile
            if d > self.range:
                break
            if self.stations[j].price > here.price:
                cost = self.stop_cost + self.cost_to_go(j, self.range - d)[0]
                if cost < opt.fill_cost:
                    opt.fill_cost, opt.fill_next = cost, j
            else:
                cost = d * self.unit[i] + self.stop_cost + self.cost_to_go(j, 0.0)[0]
                just.append((d, cost, j))

        opt.just_dist = [d for d, _, _ in just]
        opt.just_best = [(math.inf, -1)] * len(just)
        best = (math.inf, -1)
        for k in reversed(range(len(just))):
            best = min(best, (just[k][1], just[k][2]))
            opt.just_best[k] = best

    def cost_to_go(self, i: int, g: float) -> tuple[float, str, int | None]:
        """Cheapest cost from station i arriving with g miles of fuel: (cost, move, next)."""
        opt, unit = self.options[i], self.unit[i]
        best = (math.inf, "none", None)
        if opt.can_finish:
            best = (max(0.0, self.trip - self.stations[i].mile - g) * unit, "finish", None)
        if opt.fill_next is not None:
            cost = (self.range - g) * unit + opt.fill_cost
            if cost < best[0]:
                best = (cost, "fill", opt.fill_next)
        k = bisect.bisect_right(opt.just_dist, g)
        if k < len(opt.just_best):
            value, j = opt.just_best[k]
            if value - g * unit < best[0]:
                best = (value - g * unit, "just", j)
        return best

    def purchases(self) -> list[Purchase]:
        purchases, i, g = [], 0, 0.0
        while True:
            cost, move, j = self.cost_to_go(i, g)
            if math.isinf(cost):
                raise NoFuelPlan("No feasible refuelling plan along the route.")
            here = self.stations[i]
            if move == "finish":
                buy, g_next = self.trip - here.mile - g, 0.0
            elif move == "fill":
                buy, g_next = self.range - g, self.range - (self.stations[j].mile - here.mile)
            else:
                buy, g_next = self.stations[j].mile - here.mile - g, 0.0
            if buy > 1e-9:
                purchases.append(Purchase(here, buy / self.mpg))
            if j is None:
                return purchases
            i, g = j, g_next
