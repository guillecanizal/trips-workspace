# Trip Planner Scaffold

Minimal Flask + SQLite starter for the personal vacation planner.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the dev server

```bash
flask --app run:app --debug run
```

Visit http://127.0.0.1:5000/ to confirm you see `Hello Trip Planner`.
Then head to http://127.0.0.1:5000/trips for the minimal HTML UI.

## Project structure

```
app/
  __init__.py      # Flask app factory + DB bootstrap
  database.py      # SQLAlchemy engine + session helpers
  models.py        # Trip/Day/Activity/GeneralItem tables + serializers
  routes.py        # JSON CRUD API + simple HTML views
  templates/       # Minimal Jinja templates for manual testing
run.py             # Entry point for `flask --app run:app run`
requirements.txt   # Minimal dependencies
```

## API cheat sheet

- `GET /api/trips` → list trips with nested days/activities
- `POST /api/trips` → create a trip (JSON body with `name`, optional fields)
- Trips require `start_date` and `end_date`; the API auto-creates one Day per calendar date within the range so you can fill them later.
- `PUT /api/trips/<id>` / `DELETE /api/trips/<id>` → update/remove a trip
- `POST /api/trips/<id>/days` → create a day for a trip
- `POST /api/days/<id>/activities` → create an activity for a day
- `POST /api/trips/<id>/general-items` → add a flight/rental/etc. to a trip
  (each entity also has `GET/PUT/DELETE` endpoints)

Activities and general items now track `link`, `maps_link`, and `cancelable` flags, so you can keep booking links and cancellation info handy. General items also support an optional `description`. Days support hotel metadata (`hotel_link`, `hotel_maps_link`, `hotel_cancelable`), plus `distance_hours`/`distance_minutes` alongside `distance_km` to record drive time.

Use the HTML UI at `/trips` for quick manual testing—create a trip (dates are required so the planner seeds each day automatically), edit details, add/edit/delete days and activities, manage general items, and (optionally) let the AI helper pre-fill empty trips (see below).

## Optional AI itinerary generator

- Install [Ollama](https://ollama.com/) locally and pull a chat model (default `llama3.1`).
- Install `langchain-ollama` (already listed in `requirements.txt`).
- (Optional) set `OLLAMA_MODEL` to point at a different local model name.
- On an empty trip, click **Generate itinerary with AI** to have the model suggest daily stay ideas plus multiple activities; the raw JSON response is saved under `logs/` and the Flask console logs will show success/error summaries.
