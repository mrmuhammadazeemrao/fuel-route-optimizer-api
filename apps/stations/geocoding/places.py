"""City-name lookup built from the Census Gazetteer (places, then townships) and USGS GNIS
populated places (covers unincorporated communities). Earlier sources win on duplicate names."""

import csv
import re
import unicodedata
from pathlib import Path

from apps.stations.geocoding.geo import haversine_miles, mean_point

Point = tuple[float, float]

# GNIS lists some names several times in one state; points this close are the same town.
SAME_PLACE_MILES = 15

_LSAD_SUFFIX = re.compile(
    r"\s+(city and borough|city|town|village|borough|cdp|municipality|"
    r"(consolidated|metropolitan|unified) government|urban county|county|township|plantation)$"
)
_WORD_ALIASES = [
    (re.compile(r"^n\b\.?"), "north"),
    (re.compile(r"^s\b\.?"), "south"),
    (re.compile(r"^e\b\.?"), "east"),
    (re.compile(r"^w\b\.?"), "west"),
    (re.compile(r"\b(saint|ste?)\b\.?"), "st"),
    (re.compile(r"\bfort\b|\bft\b\.?"), "ft"),
    (re.compile(r"\bmount\b|\bmt\b\.?"), "mt"),
]


def normalize(name: str) -> str:
    """'St. Louis' / 'Saint Louis' -> 'stlouis'; 'Mc Calla' / 'McCalla' -> 'mccalla'."""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.strip().lower()
    for pattern, replacement in _WORD_ALIASES:
        name = pattern.sub(replacement, name)
    return re.sub(r"[^a-z0-9]", "", name)


def _gazetteer_names(raw: str) -> list[str]:
    """'Nashville-Davidson metropolitan government' -> ['nashvilledavidson', 'nashville']."""
    name = raw.lower().replace("(balance)", "").strip()
    name = _LSAD_SUFFIX.sub("", name)
    names = [name]
    if "-" in name:
        names.append(name.split("-", 1)[0])
    return [normalize(n) for n in names]


class PlaceIndex:
    def __init__(self, gazetteer_paths: list[Path], gnis_path: Path):
        self._points: dict[tuple[str, str], Point] = {}
        self._ambiguous: set[tuple[str, str]] = set()
        fips_to_usps = {}
        for path in gazetteer_paths:
            fips_to_usps |= self._load_gazetteer(path)
        self._load_gnis(gnis_path, fips_to_usps)

    def lookup(self, city: str, state: str) -> Point | None:
        return self._points.get((normalize(city), state.upper()))

    def _load_gazetteer(self, path: Path) -> dict[str, str]:
        fips_to_usps = {}
        with path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="|"):
                state = row["USPS"]
                fips_to_usps[row["GEOID"][:2]] = state
                point = (float(row["INTPTLAT"]), float(row["INTPTLONG"]))
                for name in _gazetteer_names(row["NAME"]):
                    self._points.setdefault((name, state), point)
        return fips_to_usps

    def _load_gnis(self, path: Path, fips_to_usps: dict[str, str]) -> None:
        candidates: dict[tuple[str, str], list[Point]] = {}
        with path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="|"):
                if row["feature_class"] != "Populated Place":
                    continue
                state = fips_to_usps.get(row["state_numeric"])
                if not state or not row["prim_lat_dec"]:
                    continue
                key = (normalize(row["feature_name"]), state)
                if key in self._points:
                    continue
                point = (float(row["prim_lat_dec"]), float(row["prim_long_dec"]))
                if point == (0.0, 0.0):  # GNIS uses 0,0 for "unknown location"
                    continue
                candidates.setdefault(key, []).append(point)

        for key, points in candidates.items():
            if all(haversine_miles(*points[0], *p) <= SAME_PLACE_MILES for p in points):
                self._points[key] = mean_point(points)
            else:
                self._ambiguous.add(key)

    def is_ambiguous(self, city: str, state: str) -> bool:
        return (normalize(city), state.upper()) in self._ambiguous
