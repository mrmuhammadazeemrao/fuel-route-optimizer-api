# Fuel Route Optimizer API

Django REST API that takes a start and finish location in the USA and returns the route, the most cost-effective fuel stops along it (500-mile range, 10 MPG), and the total fuel cost.

## Stack

- Python 3.14.8, Django 6.1.1, Django REST Framework 3.18.1
- PostgreSQL 18
- [OSRM](https://project-osrm.org/) for routing (free, no API key)

## Setup

Requires [pyenv](https://github.com/pyenv/pyenv) and Docker (or any local PostgreSQL).

```bash
pyenv install 3.14.8
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env            # then set SECRET_KEY
docker compose up -d db

python manage.py migrate
python manage.py load_stations
python manage.py runserver
```

## Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/route/` | Route between `start` and `finish` (`"City, ST"` or `"lat,lon"`) with the cheapest fuel stops and total fuel cost |
| GET | `/api/v1/route/map/?start=...&finish=...` | HTML map of the route and fuel stops (the `map_url` in the response) |
| GET | `/api/v1/health/` | Health check |
| GET | `/api/docs/` | Swagger UI |
| GET | `/api/schema/` | OpenAPI schema |

```bash
curl -X POST http://localhost:8000/api/v1/route/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Chicago, IL", "finish": "Houston, TX"}'
```

The response has the route distance, each fuel stop (name, address, price, gallons, cost), the total gallons and total fuel cost, the route as GeoJSON, and a `map_url`.

A Postman collection with example requests and tests is in `postman/`.

## Station data

`data/fuel_prices.csv` holds the fuel prices. It has no coordinates, so stations were geocoded once, using OpenStreetMap interstate exits where the address names an exit and city centres otherwise. The results are stored in `data/station_coordinates.csv`, and `load_stations` imports both files. To regenerate the coordinates:

```bash
python manage.py geocode_stations --all
```

## Tests

```bash
pytest
```
