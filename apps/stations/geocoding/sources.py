"""Download (and cache) the public datasets used for geocoding."""

import io
import zipfile
from pathlib import Path

import requests
from django.conf import settings

_GAZETTEER_BASE = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2026_Gazetteer/"
GAZETTEER_PLACES_URL = _GAZETTEER_BASE + "2026_Gaz_place_national.zip"
GAZETTEER_COUSUBS_URL = _GAZETTEER_BASE + "2026_Gaz_cousubs_national.zip"  # townships
STATE_BOUNDARIES_URL = "https://www2.census.gov/geo/tiger/GENZ2025/kml/cb_2025_us_state_5m.zip"
GNIS_URL = (
    "https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/"
    "DomesticNames/DomesticNames_National_Text.zip"
)
USER_AGENT = "fuel-route-optimizer/1.0 (one-time station geocoding)"


def cached_zip_member(url: str, suffix: str) -> Path:
    """Download a zip once into the cache dir and return the extracted member ending in `suffix`."""
    cache_dir: Path = settings.GEOCODING_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / url.rsplit("/", 1)[-1].replace(".zip", suffix[-4:])
    if target.exists():
        return target

    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=300)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        member = next(n for n in archive.namelist() if n.endswith(suffix))
        target.write_bytes(archive.read(member))
    return target
