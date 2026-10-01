# Fuel Route Optimizer API

Django REST API that takes a start and finish location in the USA and returns the driving route, the most cost-effective fuel stops along it (500-mile range, 10 MPG), and the total fuel cost.

## Stack

- Python 3.14.8, Django 6.1.1, Django REST Framework 3.18.1
- PostgreSQL 18 (psycopg 3)
- [OSRM](https://project-osrm.org/) for routing (free, no API key). One call per route.
- numpy / scipy for matching stations to the route
- drf-spectacular for OpenAPI / Swagger docs

## Setup

Requires [pyenv](https://github.com/pyenv/pyenv) and Docker (or any local PostgreSQL).

```bash
pyenv install 3.14.8            # version is pinned in .python-version
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env            # then set SECRET_KEY
docker compose up -d db         # PostgreSQL on localhost:5432

python manage.py migrate
python manage.py load_stations  # imports data/fuel_prices.csv
python manage.py runserver
```

If port 5432 is already taken, set `POSTGRES_PORT` (for example `POSTGRES_PORT=5433 docker compose up -d db`) and update `DATABASE_URL` in `.env` to match.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/health/` | Database status and station counts |
| GET | `/api/docs/` | Swagger UI |
| GET | `/api/schema/` | OpenAPI schema (can be imported into Postman) |

## Configuration (`.env`)

| Variable | Default | |
|---|---|---|
| `SECRET_KEY` | (none, required) | Django secret key |
| `DEBUG` | `False` | |
| `DATABASE_URL` | (none, required) | e.g. `postgres://fuel:fuel@localhost:5432/fuel_route` |
| `ROUTING_BASE_URL` | `https://router.project-osrm.org` | Any OSRM-compatible server |
| `VEHICLE_RANGE_MILES` | `500` | |
| `VEHICLE_MPG` | `10` | |

## Fuel price data

`data/fuel_prices.csv` lists about 8.1k rows covering 6,738 unique truck stops. `load_stations` merges rows that share an OPIS ID, keeping the lowest price. Re-running it updates prices and keeps any stored coordinates.

## Development

```bash
pytest
ruff check . && ruff format --check .
```
