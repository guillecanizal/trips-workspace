"""Flask routes for the Trip Planner API and basic HTML UI."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    stream_with_context,
    url_for,
)
from flask import session as flask_session
from sqlalchemy import select

from . import dal
from .models import Activity, Day, GeneralItem, Trip
from .services.agent import clear_thread, hybrid_chat_stream, suggest_day_tagline
from .services.ai import (
    AIGenerationError,
    build_full_prompt_text,
    generate_itinerary,
    stream_itinerary_generation,
)
from .utils.csv_export import generate_trip_csv
from .utils.maps import build_itinerary_maps_url, enrich_with_maps_links
from .utils.pdf_export import generate_trip_pdf

bp = Blueprint("main", __name__)


def get_session():
    Session = current_app.session_factory
    return Session()


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        abort(400, "Dates must use YYYY-MM-DD format")


def parse_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    value = str(value).strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        abort(400, "Invalid number format")


def optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_bool(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    value = str(value).strip().lower()
    if value in {"", "none"}:
        return None
    if value in {"true", "1", "yes", "y", "on"}:
        return True
    if value in {"false", "0", "no", "n", "off"}:
        return False
    abort(400, "Invalid boolean value")


def parse_int(value, *, min_value: int | None = None, max_value: int | None = None):
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        abort(400, "Invalid integer value")
    if min_value is not None and number < min_value:
        abort(400, "Integer value below allowed range")
    if max_value is not None and number > max_value:
        abort(400, "Integer value above allowed range")
    return number


def calculate_trip_stats(days: list[Day], general_items: list[GeneralItem]):
    total_distance_km = sum(
        distance for distance in (day.distance_km for day in days) if distance is not None
    )
    total_activities = sum(len(day.activities) for day in days)
    total_general_items = len(general_items)
    total_price = sum(
        value
        for value in [
            *(day.hotel_price for day in days),
            *(
                activity.price
                for day in days
                for activity in day.activities
            ),
            *(item.price for item in general_items),
        ]
        if value is not None
    )
    return {
        "total_price": total_price,
        "total_distance_km": total_distance_km,
        "day_count": len(days),
        "activity_count": total_activities,
        "general_item_count": total_general_items,
    }


def require_dates(start_raw, end_raw):
    start = parse_date(start_raw)
    end = parse_date(end_raw)
    if not start or not end:
        abort(400, "Trips require start and end dates")
    if end < start:
        abort(400, "Trip end date must be on or after the start date")
    return start, end


def ensure_sequential_days(session, trip: Trip, start: date, end: date) -> None:
    existing_dates = {day.date for day in trip.days if day.date}
    current = start
    while current <= end:
        if current not in existing_dates:
            session.add(Day(trip=trip, date=current))
        current += timedelta(days=1)


def enforce_trip_date_range(trip: Trip) -> tuple[date, date]:
    if not trip.start_date or not trip.end_date:
        abort(400, "Trips must keep a start and end date")
    if trip.end_date < trip.start_date:
        abort(400, "Trip end date must be on or after the start date")
    return trip.start_date, trip.end_date


def _safe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_bool(value):
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    return None


def apply_ai_payload(session, trip: Trip, payload: dict) -> dict[str, int]:
    summary = {"days": 0, "activities": 0, "general_items": 0}
    day_lookup = {day.date.isoformat(): day for day in trip.days if day.date}

    for day_info in payload.get("days", []) or []:
        date_str = day_info.get("date")
        day = day_lookup.get(date_str)
        if not day:
            continue
        hotel = day_info.get("hotel") or {}
        if hotel.get("name"):
            day.hotel_name = hotel.get("name")
        if hotel.get("location"):
            day.hotel_location = hotel.get("location")
        if hotel.get("notes") or hotel.get("description"):
            day.hotel_description = hotel.get("notes") or hotel.get("description")
        if hotel.get("reservation_id"):
            day.hotel_reservation_id = hotel.get("reservation_id")
        if hotel.get("price") is not None or hotel.get("price_per_night") is not None:
            price_value = hotel.get("price")
            if price_value is None:
                price_value = hotel.get("price_per_night")
            day.hotel_price = _safe_float(price_value)
        day.hotel_link = optional_str(hotel.get("link"))
        day.hotel_maps_link = optional_str(hotel.get("maps_link"))
        day.hotel_cancelable = _safe_bool(hotel.get("cancelable"))

        day.distance_km = _safe_float(day_info.get("distance_km"))
        day.distance_hours = _safe_int(day_info.get("distance_hours"))
        day.distance_minutes = _safe_int(day_info.get("distance_minutes"))

        for activity_info in day_info.get("activities", []) or []:
            name = (activity_info.get("name") or "").strip()
            if not name:
                continue
            activity = Activity(
                day=day,
                name=name,
                description=(
                    activity_info.get("details")
                    or activity_info.get("summary")
                    or activity_info.get("description")
                    or None
                ),
                location=optional_str(activity_info.get("location")),
                price=_safe_float(activity_info.get("price")),
                reservation_id=optional_str(activity_info.get("reservation_id")),
                link=optional_str(activity_info.get("link")),
                maps_link=optional_str(activity_info.get("maps_link")),
                cancelable=_safe_bool(activity_info.get("cancelable")),
            )
            session.add(activity)
            summary["activities"] += 1
        summary["days"] += 1

    for item in payload.get("general_items", []) or []:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        general_item = GeneralItem(
            trip=trip,
            name=name,
            description=item.get("description") or None,
            reservation_id=item.get("reservation_id") or None,
            price=_safe_float(item.get("price")),
            link=optional_str(item.get("link")),
            maps_link=optional_str(item.get("maps_link")),
            cancelable=_safe_bool(item.get("cancelable")),
        )
        session.add(general_item)
        summary["general_items"] += 1

    knowledge = payload.get("knowledge_general")
    if isinstance(knowledge, str) and knowledge.strip():
        trip.knowledge_general = knowledge.strip()

    return summary


def reset_trip_content(session, trip: Trip) -> None:
    for item in list(trip.general_items):
        session.delete(item)

    for day in trip.days:
        for activity in list(day.activities):
            session.delete(activity)
        day.hotel_name = None
        day.hotel_location = None
        day.hotel_description = None
        day.hotel_reservation_id = None
        day.hotel_price = None
        day.hotel_link = None
        day.hotel_maps_link = None
        day.hotel_cancelable = None
        day.distance_km = None
        day.distance_hours = None
        day.distance_minutes = None


def load_latest_ai_log(trip_id: int) -> dict[str, str] | None:
    logs_dir = Path("logs") / f"trip_{trip_id}"
    if not logs_dir.exists():
        return None
    response_files = sorted(
        logs_dir.glob("*_response.json"), key=lambda p: p.name, reverse=True
    )
    if not response_files:
        return None
    response_file = response_files[0]
    timestamp = response_file.name.split("_response.json")[0]
    prompt_file = logs_dir / f"{timestamp}_prompt.txt"
    prompt_text = prompt_file.read_text() if prompt_file.exists() else ""
    response_text = response_file.read_text()
    return {
        "prompt": prompt_text,
        "response": response_text,
        "prompt_file": str(prompt_file),
        "response_file": str(response_file),
    }


def _pending_key(trip_id: int) -> str:
    return f"pending_patch_{trip_id}"


@bp.route("/")
def home():
    """Redirect root to trip list."""
    return redirect(url_for("main.list_trips_page"))


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------


@bp.get("/api/trips")
def api_list_trips():
    session = get_session()
    try:
        stmt = select(Trip).order_by(Trip.start_date, Trip.id)
        trips = session.execute(stmt).scalars().all()
        return jsonify([trip.to_dict(include_children=True) for trip in trips])
    finally:
        session.close()


@bp.post("/api/trips")
def api_create_trip():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        abort(400, "Trip name is required")

    start_date, end_date = require_dates(
        payload.get("start_date"), payload.get("end_date")
    )

    session = get_session()
    try:
        trip = Trip(
            name=name,
            description=payload.get("description"),
            start_date=start_date,
            end_date=end_date,
        )
        session.add(trip)
        session.flush()
        ensure_sequential_days(session, trip, start_date, end_date)
        session.commit()
        return jsonify(trip.to_dict(include_children=True)), 201
    finally:
        session.close()


@bp.get("/api/trips/<int:trip_id>")
def api_get_trip(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")
        return jsonify(trip.to_dict(include_children=True))
    finally:
        session.close()


@bp.put("/api/trips/<int:trip_id>")
def api_update_trip(trip_id: int):
    payload = request.get_json(silent=True) or {}
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")

        if "name" in payload:
            name = (payload.get("name") or "").strip()
            if not name:
                abort(400, "Trip name cannot be empty")
            trip.name = name
        trip.description = payload.get("description", trip.description)
        if "start_date" in payload:
            new_start = parse_date(payload.get("start_date"))
            if not new_start:
                abort(400, "Trips require a start date")
            trip.start_date = new_start
        if "end_date" in payload:
            new_end = parse_date(payload.get("end_date"))
            if not new_end:
                abort(400, "Trips require an end date")
            trip.end_date = new_end

        start, end = enforce_trip_date_range(trip)
        ensure_sequential_days(session, trip, start, end)

        session.commit()
        session.refresh(trip)
        return jsonify(trip.to_dict(include_children=True))
    finally:
        session.close()


@bp.delete("/api/trips/<int:trip_id>")
def api_delete_trip(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")
        session.delete(trip)
        session.commit()
        return "", 204
    finally:
        session.close()


@bp.get("/api/trips/<int:trip_id>/days")
def api_list_days(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")
        return jsonify([day.to_dict(include_children=True) for day in trip.days])
    finally:
        session.close()


@bp.post("/api/trips/<int:trip_id>/days")
def api_create_day(trip_id: int):
    payload = request.get_json(silent=True) or {}
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")

        day = Day(
            trip=trip,
            date=parse_date(payload.get("date")),
            hotel_name=optional_str(payload.get("hotel_name")),
            hotel_reservation_id=optional_str(payload.get("hotel_reservation_id")),
            hotel_price=parse_float(payload.get("hotel_price")),
            hotel_link=optional_str(payload.get("hotel_link")),
            hotel_maps_link=optional_str(payload.get("hotel_maps_link")),
            hotel_cancelable=parse_bool(payload.get("hotel_cancelable")),
            distance_km=parse_float(payload.get("distance_km")),
            distance_hours=parse_int(payload.get("distance_hours"), min_value=0),
            distance_minutes=parse_int(
                payload.get("distance_minutes"), min_value=0, max_value=59
            ),
        )
        session.add(day)
        session.commit()
        session.refresh(day)
        return jsonify(day.to_dict(include_children=True)), 201
    finally:
        session.close()


@bp.get("/api/days/<int:day_id>")
def api_get_day(day_id: int):
    session = get_session()
    try:
        day = session.get(Day, day_id)
        if not day:
            abort(404, "Day not found")
        return jsonify(day.to_dict(include_children=True))
    finally:
        session.close()


@bp.put("/api/days/<int:day_id>")
def api_update_day(day_id: int):
    payload = request.get_json(silent=True) or {}
    session = get_session()
    try:
        day = session.get(Day, day_id)
        if not day:
            abort(404, "Day not found")

        if "date" in payload:
            day.date = parse_date(payload.get("date"))
        for attr in [
            "hotel_name",
            "hotel_reservation_id",
            "hotel_price",
            "hotel_link",
            "hotel_maps_link",
            "hotel_cancelable",
            "distance_km",
            "distance_hours",
            "distance_minutes",
        ]:
            if attr in payload:
                value = payload.get(attr)
                if attr in {"hotel_price", "distance_km"}:
                    value = parse_float(value)
                elif attr == "distance_hours":
                    value = parse_int(value, min_value=0)
                elif attr == "distance_minutes":
                    value = parse_int(value, min_value=0, max_value=59)
                elif attr in {"hotel_name", "hotel_reservation_id", "hotel_link", "hotel_maps_link"}:
                    value = optional_str(value)
                elif attr == "hotel_cancelable":
                    value = parse_bool(value)
                setattr(day, attr, value)

        session.commit()
        session.refresh(day)
        return jsonify(day.to_dict(include_children=True))
    finally:
        session.close()


@bp.delete("/api/days/<int:day_id>")
def api_delete_day(day_id: int):
    session = get_session()
    try:
        day = session.get(Day, day_id)
        if not day:
            abort(404, "Day not found")
        session.delete(day)
        session.commit()
        return "", 204
    finally:
        session.close()


@bp.post("/api/days/<int:day_id>/activities")
def api_create_activity(day_id: int):
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        abort(400, "Activity name is required")

    session = get_session()
    try:
        day = session.get(Day, day_id)
        if not day:
            abort(404, "Day not found")

        activity = Activity(
            day=day,
            name=name,
            description=optional_str(payload.get("description")),
            location=optional_str(payload.get("location")),
            price=parse_float(payload.get("price")),
            reservation_id=optional_str(payload.get("reservation_id")),
            link=optional_str(payload.get("link")),
            maps_link=optional_str(payload.get("maps_link")),
            cancelable=parse_bool(payload.get("cancelable")),
        )
        session.add(activity)
        session.commit()
        session.refresh(activity)
        return jsonify(activity.to_dict()), 201
    finally:
        session.close()


@bp.get("/api/activities/<int:activity_id>")
def api_get_activity(activity_id: int):
    session = get_session()
    try:
        activity = session.get(Activity, activity_id)
        if not activity:
            abort(404, "Activity not found")
        return jsonify(activity.to_dict())
    finally:
        session.close()


@bp.put("/api/activities/<int:activity_id>")
def api_update_activity(activity_id: int):
    payload = request.get_json(silent=True) or {}
    session = get_session()
    try:
        activity = session.get(Activity, activity_id)
        if not activity:
            abort(404, "Activity not found")

        if "name" in payload:
            name = (payload.get("name") or "").strip()
            if not name:
                abort(400, "Activity name cannot be empty")
            activity.name = name
        for attr in [
            "description",
            "location",
            "price",
            "reservation_id",
            "link",
            "maps_link",
            "cancelable",
        ]:
            if attr in payload:
                value = payload.get(attr)
                if attr == "price":
                    value = parse_float(value)
                elif attr in {"description", "location", "reservation_id", "link", "maps_link"}:
                    value = optional_str(value)
                elif attr == "cancelable":
                    value = parse_bool(value)
                setattr(activity, attr, value)

        session.commit()
        session.refresh(activity)
        return jsonify(activity.to_dict())
    finally:
        session.close()


@bp.delete("/api/activities/<int:activity_id>")
def api_delete_activity(activity_id: int):
    session = get_session()
    try:
        activity = session.get(Activity, activity_id)
        if not activity:
            abort(404, "Activity not found")
        session.delete(activity)
        session.commit()
        return "", 204
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Minimal HTML UI
# ---------------------------------------------------------------------------


@bp.get("/trips")
def list_trips_page():
    session = get_session()
    try:
        stmt = select(Trip).order_by(Trip.start_date, Trip.id)
        trips = session.execute(stmt).scalars().all()
        trip_summaries = []
        for trip in trips:
            ordered_days = sorted(
                trip.days,
                key=lambda d: (d.date or date.max, d.id),
            )
            general_items = sorted(
                trip.general_items,
                key=lambda item: (item.name or "").lower(),
            )
            stats = calculate_trip_stats(ordered_days, general_items)

            trip_summaries.append(
                {
                    "trip": trip,
                    "days": ordered_days,
                    "general_items": general_items,
                    "stats": stats,
                }
            )

        return render_template("pages/trip_list.html", trip_summaries=trip_summaries)
    finally:
        session.close()


@bp.get("/api/trips/<int:trip_id>/general-items")
def api_list_general_items(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")
        return jsonify([item.to_dict() for item in trip.general_items])
    finally:
        session.close()


@bp.post("/api/trips/<int:trip_id>/general-items")
def api_create_general_item(trip_id: int):
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        abort(400, "Item name is required")

    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")

        item = GeneralItem(
            trip=trip,
            name=name,
            description=optional_str(payload.get("description")),
            reservation_id=optional_str(payload.get("reservation_id")),
            price=parse_float(payload.get("price")),
            link=optional_str(payload.get("link")),
            maps_link=optional_str(payload.get("maps_link")),
            cancelable=parse_bool(payload.get("cancelable")),
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return jsonify(item.to_dict()), 201
    finally:
        session.close()


@bp.get("/api/general-items/<int:item_id>")
def api_get_general_item(item_id: int):
    session = get_session()
    try:
        item = session.get(GeneralItem, item_id)
        if not item:
            abort(404, "Item not found")
        return jsonify(item.to_dict())
    finally:
        session.close()


@bp.put("/api/general-items/<int:item_id>")
def api_update_general_item(item_id: int):
    payload = request.get_json(silent=True) or {}
    session = get_session()
    try:
        item = session.get(GeneralItem, item_id)
        if not item:
            abort(404, "Item not found")

        if "name" in payload:
            name = (payload.get("name") or "").strip()
            if not name:
                abort(400, "Item name cannot be empty")
            item.name = name
        if "description" in payload:
            item.description = optional_str(payload.get("description"))
        if "reservation_id" in payload:
            item.reservation_id = optional_str(payload.get("reservation_id"))
        if "price" in payload:
            item.price = parse_float(payload.get("price"))
        if "link" in payload:
            item.link = optional_str(payload.get("link"))
        if "maps_link" in payload:
            item.maps_link = optional_str(payload.get("maps_link"))
        if "cancelable" in payload:
            item.cancelable = parse_bool(payload.get("cancelable"))

        session.commit()
        session.refresh(item)
        return jsonify(item.to_dict())
    finally:
        session.close()


@bp.delete("/api/general-items/<int:item_id>")
def api_delete_general_item(item_id: int):
    session = get_session()
    try:
        item = session.get(GeneralItem, item_id)
        if not item:
            abort(404, "Item not found")
        session.delete(item)
        session.commit()
        return "", 204
    finally:
        session.close()


@bp.post("/trips")
def create_trip_page():
    session = get_session()
    try:
        name = (request.form.get("name") or "").strip()
        if not name:
            abort(400, "Trip name is required")
        start_date, end_date = require_dates(
            request.form.get("start_date"), request.form.get("end_date")
        )
        trip = Trip(
            name=name,
            description=request.form.get("description") or None,
            start_date=start_date,
            end_date=end_date,
        )
        session.add(trip)
        session.flush()
        ensure_sequential_days(session, trip, start_date, end_date)
        session.commit()
        return redirect(url_for("main.view_trip_page", trip_id=trip.id))
    finally:
        session.close()


@bp.get("/trips/<int:trip_id>")
def view_trip_page(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")
        ordered_days = sorted(
            trip.days,
            key=lambda d: (d.date or date.max, d.id),
        )
        general_items = sorted(
            trip.general_items,
            key=lambda item: ((item.name or "").lower(), item.id),
        )
        stats = calculate_trip_stats(ordered_days, general_items)
        ai_log = load_latest_ai_log(trip.id)
        manual_prompt = flask_session.pop("manual_ai_prompt", None)
        prompt_text = manual_prompt or (ai_log["prompt"] if ai_log else "")
        return render_template(
            "pages/trip_overview.html",
            trip=trip,
            days=ordered_days,
            general_items=general_items,
            stats=stats,
            ai_prompt_text=prompt_text,
        )
    finally:
        session.close()


@bp.get("/trips/<int:trip_id>/days/<int:day_id>")
def view_day_page(trip_id: int, day_id: int):
    session = get_session()
    try:
        day = session.get(Day, day_id)
        if not day or day.trip_id != trip_id:
            abort(404, "Day not found")
        trip = day.trip
        ordered_days = sorted(
            trip.days,
            key=lambda d: (d.date or date.max, d.id),
        )
        day_index = next(
            (i + 1 for i, d in enumerate(ordered_days) if d.id == day_id), 0
        )
        return render_template(
            "pages/day_detail.html",
            trip=trip,
            day=day,
            day_index=day_index,
            activities=day.activities,
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# HTMX Partials
# ---------------------------------------------------------------------------


@bp.get("/partials/trips/<int:trip_id>/overview")
def partial_trip_overview(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")
        ordered_days = sorted(
            trip.days, key=lambda d: (d.date or date.max, d.id)
        )
        general_items = sorted(
            trip.general_items,
            key=lambda item: ((item.name or "").lower(), item.id),
        )
        stats = calculate_trip_stats(ordered_days, general_items)
        return render_template(
            "partials/trip_overview_content.html",
            trip=trip,
            days=ordered_days,
            general_items=general_items,
            stats=stats,
        )
    finally:
        session.close()


@bp.get("/partials/days/<int:day_id>/hotel")
def partial_day_hotel(day_id: int):
    session = get_session()
    try:
        day = session.get(Day, day_id)
        if not day:
            abort(404, "Day not found")
        return render_template("partials/day_hotel.html", day=day)
    finally:
        session.close()


@bp.get("/partials/days/<int:day_id>/activities")
def partial_day_activities(day_id: int):
    session = get_session()
    try:
        day = session.get(Day, day_id)
        if not day:
            abort(404, "Day not found")
        return render_template(
            "partials/day_activities.html", day=day, activities=day.activities
        )
    finally:
        session.close()


@bp.get("/partials/trips/<int:trip_id>/general-items")
def partial_general_items(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")
        general_items = sorted(
            trip.general_items,
            key=lambda item: ((item.name or "").lower(), item.id),
        )
        return render_template(
            "partials/general_items.html",
            trip=trip,
            general_items=general_items,
        )
    finally:
        session.close()


@bp.get("/partials/trips/<int:trip_id>/kpis")
def partial_kpis(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")
        ordered_days = sorted(
            trip.days, key=lambda d: (d.date or date.max, d.id)
        )
        general_items = sorted(
            trip.general_items,
            key=lambda item: ((item.name or "").lower(), item.id),
        )
        stats = calculate_trip_stats(ordered_days, general_items)
        return render_template("partials/kpis.html", trip=trip, stats=stats)
    finally:
        session.close()


@bp.get("/trips/<int:trip_id>/export.pdf")
def export_trip_pdf(trip_id: int):
    """Export trip data as PDF file."""
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")

        ordered_days = sorted(
            trip.days,
            key=lambda d: (d.date or date.max, d.id),
        )
        general_items = sorted(
            trip.general_items,
            key=lambda item: ((item.name or "").lower(), item.id),
        )
        stats = calculate_trip_stats(ordered_days, general_items)

        # Generate PDF content using utility module
        pdf_bytes = generate_trip_pdf(trip, ordered_days, general_items, stats)

        # Prepare file for download
        buffer = BytesIO(pdf_bytes)

        base_name = (trip.name or "trip").strip().lower()
        base_name = re.sub(r"[^a-z0-9]+", "-", base_name) or "trip"
        filename = f"{base_name}-guide.pdf"

        return send_file(
            buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    finally:
        session.close()


@bp.get("/trips/<int:trip_id>/export.csv")
def export_trip_csv(trip_id: int):
    """Export trip data as CSV file."""
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")

        ordered_days = sorted(
            trip.days,
            key=lambda d: (d.date or date.max, d.id),
        )
        general_items = sorted(
            trip.general_items,
            key=lambda item: ((item.name or "").lower(), item.id),
        )
        stats = calculate_trip_stats(ordered_days, general_items)

        # Generate CSV content
        csv_content = generate_trip_csv(trip, ordered_days, general_items, stats)

        # Prepare file for download
        buffer = BytesIO(csv_content.encode('utf-8-sig'))  # UTF-8 with BOM for Excel compatibility

        base_name = (trip.name or "trip").strip().lower()
        base_name = re.sub(r"[^a-z0-9]+", "-", base_name) or "trip"
        filename = f"{base_name}-export.csv"

        return send_file(
            buffer,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename,
        )
    finally:
        session.close()





@bp.post("/agent/stream")
def agent_chat_stream():
    payload = request.get_json(silent=True) or {}
    trip_id = payload.get("trip_id")
    message = (payload.get("message") or "").strip()
    day_id = payload.get("day_id")  # optional — scopes chat to a specific day
    if not trip_id or not message:
        return jsonify({"error": "trip_id and message are required"}), 400

    # Isolated thread key per trip or per day
    if day_id:
        thread_key = f"agent_thread_{trip_id}_day_{day_id}"
    else:
        thread_key = f"agent_thread_{trip_id}"
    thread_id = flask_session.get(thread_key)
    if not thread_id:
        import uuid
        thread_id = str(uuid.uuid4())
        flask_session[thread_key] = thread_id

    def generate():
        try:
            for event in hybrid_chat_stream(
                trip_id, message, thread_id=thread_id, day_id=day_id
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        yield "data: [DONE]\n\n"

    return current_app.response_class(stream_with_context(generate()), mimetype="text/event-stream")


@bp.delete("/agent/history/<int:trip_id>")
def clear_agent_history(trip_id: int):
    day_id = request.args.get("day_id", type=int)
    if day_id:
        thread_key = f"agent_thread_{trip_id}_day_{day_id}"
    else:
        thread_key = f"agent_thread_{trip_id}"
    thread_id = flask_session.pop(thread_key, None)
    if thread_id:
        clear_thread(thread_id)
    return jsonify({"ok": True})


@bp.get("/api/days/<int:day_id>/suggest-tagline")
def suggest_tagline(day_id: int):
    """Generate a tagline suggestion via LLM (called async from the day page)."""
    tagline = suggest_day_tagline(day_id)
    return jsonify({"tagline": tagline})


@bp.post("/api/days/<int:day_id>/tagline")
def save_tagline(day_id: int):
    """Persist the tagline the user accepted."""
    payload = request.get_json(silent=True) or {}
    tagline = (payload.get("tagline") or "").strip()[:100]
    if not tagline:
        return jsonify({"error": "tagline required"}), 400
    dal.update_day_tagline(day_id, tagline)
    return jsonify({"ok": True})


@bp.post("/api/trips/<int:trip_id>/generate-taglines")
def generate_all_taglines(trip_id: int):
    """SSE endpoint — generate and save a tagline for every day that has content."""

    def stream():
        session = get_session()
        try:
            trip = session.get(Trip, trip_id)
            if not trip:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Trip not found'})}\n\n"
                return
            days = sorted(
                [d for d in trip.days if d.hotel_name or d.activities],
                key=lambda d: (d.date or date.max, d.id),
            )
            total = len(days)
            if not total:
                yield f"data: {json.dumps({'type': 'done', 'updated': 0})}\n\n"
                return
            for n, day in enumerate(days, 1):
                tagline = suggest_day_tagline(day.id)
                if tagline:
                    dal.update_day_tagline(day.id, tagline)
                evt = {
                    "type": "progress",
                    "n": n,
                    "total": total,
                    "date": day.date.isoformat() if day.date else "?",
                    "tagline": tagline,
                }
                yield f"data: {json.dumps(evt)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'updated': total})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        finally:
            session.close()

    return current_app.response_class(
        stream_with_context(stream()),
        mimetype="text/event-stream",
    )


@bp.post("/apply/hotel")
def apply_hotel_endpoint():
    payload = request.get_json(silent=True) or {}
    trip_id = payload.get("trip_id")
    day = payload.get("day")
    hotel = payload.get("hotel")
    if not trip_id or not day:
        return jsonify({"error": "trip_id and day are required"}), 400
    if not isinstance(hotel, dict):
        return jsonify({"error": "Hotel payload missing"}), 400
    try:
        snapshot = dal.apply_hotel(trip_id, day, hotel)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    flask_session.pop(_pending_key(trip_id), None)
    return jsonify({"day": snapshot})


@bp.post("/apply/activity")
def apply_activity_endpoint():
    payload = request.get_json(silent=True) or {}
    trip_id = payload.get("trip_id")
    day = payload.get("day")
    activity = payload.get("activity")
    if not trip_id or not day:
        return jsonify({"error": "trip_id and day are required"}), 400
    if not isinstance(activity, dict):
        return jsonify({"error": "Activity payload missing"}), 400
    try:
        snapshot = dal.apply_activity(trip_id, day, activity)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    flask_session.pop(_pending_key(trip_id), None)
    return jsonify({"day": snapshot})


@bp.get("/itinerary/url")
def itinerary_url():
    trip_id = request.args.get("trip_id", type=int)
    if not trip_id:
        return jsonify({"error": "trip_id is required"}), 400
    try:
        compact = dal.get_trip_compact(trip_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    url = build_itinerary_maps_url({"days": compact.get("days", [])})
    return jsonify({"url": url})


@bp.post("/trips/<int:trip_id>/generate-ai")
def generate_trip_ai(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")

        day_dates = sorted(day.date for day in trip.days if day.date)
        if not day_dates:
            flash("Trip needs dated days before generating.", "error")
            return redirect(url_for("main.view_trip_page", trip_id=trip.id))

        generate_only = request.form.get("generate_only") == "true"

        current_app.logger.info(
            "AI generation requested",
            extra={"trip_id": trip.id, "days": len(day_dates), "apply": not generate_only},
        )

        if generate_only:
            prompt = build_full_prompt_text(trip.name, trip.description, day_dates)
            flask_session["manual_ai_prompt"] = prompt
            current_app.logger.info(
                "Manual prompt generated",
                extra={"trip_id": trip.id},
            )
            flash("Prompt ready. Review it in the sidebar before calling any LLM.", "success")
            return redirect(url_for("main.view_trip_page", trip_id=trip.id, show_ai="1"))

        try:
            payload, log_file = generate_itinerary(
                trip.id,
                trip.name,
                trip.description,
                day_dates,
            )
        except AIGenerationError as exc:
            current_app.logger.error(
                "AI generation failed", extra={"trip_id": trip.id, "error": str(exc)}
            )
            flash(f"AI generation failed: {exc}", "error")
            return redirect(url_for("main.view_trip_page", trip_id=trip.id))

        payload = enrich_with_maps_links(payload)

        reset_trip_content(session, trip)
        summary = apply_ai_payload(session, trip, payload)
        session.commit()
        current_app.logger.info(
            "AI itinerary applied",
            extra={
                "trip_id": trip.id,
                "days": summary["days"],
                "activities": summary["activities"],
                "general_items": summary["general_items"],
                "log_file": str(log_file),
            },
        )
        flash(
            "AI itinerary added: "
            f"{summary['days']} days, {summary['activities']} activities, {summary['general_items']} general items.",
            "success",
        )
        return redirect(url_for("main.view_trip_page", trip_id=trip.id))
    finally:
        session.close()


@bp.post("/api/trips/<int:trip_id>/generate_stream")
def generate_trip_stream(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")

        # Sort days to ensure order
        days_list = sorted(trip.days, key=lambda d: (d.date or date.max))
        trips_dates = [d.date for d in days_list if d.date]

        def generate():
            try:
                # Use the new streaming generator
                iterator = stream_itinerary_generation(
                    trip_name=trip.name,
                    description=trip.description,
                    days=trips_dates
                )
                for chunk in iterator:
                    # Send chunk as a JSON object in an SSE event
                    payload = json.dumps({"chunk": chunk})
                    yield f"data: {payload}\n\n"

                # Signal completion
                yield "data: [DONE]\n\n"
            except Exception as e:
                err_payload = json.dumps({"error": str(e)})
                yield f"data: {err_payload}\n\n"

        return current_app.response_class(generate(), mimetype='text/event-stream')
    finally:
        session.close()


@bp.post("/trips/<int:trip_id>/apply-ai-response")
def apply_ai_response(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")

        raw_response = request.form.get("ai_response_text") or ""
        if not raw_response.strip():
            flash("Paste a JSON response before saving.", "error")
            return redirect(url_for("main.view_trip_page", trip_id=trip.id))

        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            flash(f"Invalid JSON: {exc}", "error")
            return redirect(url_for("main.view_trip_page", trip_id=trip.id))

        payload = enrich_with_maps_links(payload)
        reset_trip_content(session, trip)
        summary = apply_ai_payload(session, trip, payload)
        session.commit()
        flash(
            "AI itinerary applied: "
            f"{summary['days']} days, {summary['activities']} activities, {summary['general_items']} general items.",
            "success",
        )
        return redirect(url_for("main.view_trip_page", trip_id=trip.id))
    finally:
        session.close()


@bp.post("/trips/<int:trip_id>")
def update_trip_page(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")

        name = (request.form.get("name") or "").strip()
        if name:
            trip.name = name
        trip.description = request.form.get("description") or None
        start_date, end_date = require_dates(
            request.form.get("start_date"), request.form.get("end_date")
        )
        trip.start_date = start_date
        trip.end_date = end_date

        ensure_sequential_days(session, trip, start_date, end_date)

        session.commit()
        return redirect(url_for("main.view_trip_page", trip_id=trip.id))
    finally:
        session.close()


@bp.post("/trips/<int:trip_id>/delete")
def delete_trip_page(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")
        session.delete(trip)
        session.commit()
        flash("Trip deleted.", "success")
        return redirect(url_for("main.list_trips_page"))
    finally:
        session.close()


@bp.post("/trips/<int:trip_id>/days")
def create_day_page(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")

        day = Day(
            trip=trip,
            date=parse_date(request.form.get("date")),
            hotel_name=optional_str(request.form.get("hotel_name")),
            hotel_location=optional_str(request.form.get("hotel_location")),
            hotel_description=optional_str(request.form.get("hotel_description")),
            hotel_reservation_id=optional_str(request.form.get("hotel_reservation_id")),
            hotel_price=parse_float(request.form.get("hotel_price")),
            hotel_link=optional_str(request.form.get("hotel_link")),
            hotel_maps_link=optional_str(request.form.get("hotel_maps_link")),
            hotel_cancelable=parse_bool(request.form.get("hotel_cancelable")),
            distance_km=parse_float(request.form.get("distance_km")),
            distance_hours=parse_int(request.form.get("distance_hours"), min_value=0),
            distance_minutes=parse_int(
                request.form.get("distance_minutes"), min_value=0, max_value=59
            ),
        )
        session.add(day)
        session.commit()
        return redirect(url_for("main.view_trip_page", trip_id=trip_id))
    finally:
        session.close()


@bp.post("/trips/<int:trip_id>/general-items")
def create_general_item_page(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")

        name = (request.form.get("name") or "").strip()
        if not name:
            abort(400, "Item name is required")

        item = GeneralItem(
            trip=trip,
            name=name,
            description=optional_str(request.form.get("description")),
            reservation_id=optional_str(request.form.get("reservation_id")),
            price=parse_float(request.form.get("price")),
            link=optional_str(request.form.get("link")),
            maps_link=optional_str(request.form.get("maps_link")),
            cancelable=parse_bool(request.form.get("cancelable")),
        )
        session.add(item)
        session.commit()
        if request.headers.get("HX-Request"):
            general_items = sorted(
                trip.general_items,
                key=lambda gi: ((gi.name or "").lower(), gi.id),
            )
            return render_template(
                "partials/general_items.html",
                trip=trip,
                general_items=general_items,
            )
        return redirect(url_for("main.view_trip_page", trip_id=trip_id))
    finally:
        session.close()


@bp.post("/days/<int:day_id>")
def update_day_page(day_id: int):
    session = get_session()
    try:
        day = session.get(Day, day_id)
        if not day:
            abort(404, "Day not found")

        day.date = parse_date(request.form.get("date"))
        day.tagline = optional_str(request.form.get("tagline"))
        day.hotel_name = optional_str(request.form.get("hotel_name"))
        day.hotel_location = optional_str(request.form.get("hotel_location"))
        day.hotel_description = optional_str(request.form.get("hotel_description"))
        day.hotel_reservation_id = optional_str(
            request.form.get("hotel_reservation_id")
        )
        day.hotel_price = parse_float(request.form.get("hotel_price"))
        day.hotel_link = optional_str(request.form.get("hotel_link"))
        day.hotel_maps_link = optional_str(request.form.get("hotel_maps_link"))
        day.hotel_cancelable = parse_bool(request.form.get("hotel_cancelable"))
        day.distance_km = parse_float(request.form.get("distance_km"))
        day.distance_hours = parse_int(request.form.get("distance_hours"), min_value=0)
        day.distance_minutes = parse_int(
            request.form.get("distance_minutes"), min_value=0, max_value=59
        )

        session.commit()
        if request.headers.get("HX-Request"):
            session.refresh(day)
            return render_template("partials/day_hotel.html", day=day)
        return redirect(url_for("main.view_trip_page", trip_id=day.trip_id))
    finally:
        session.close()


@bp.post("/general-items/<int:item_id>")
def update_general_item_page(item_id: int):
    session = get_session()
    try:
        item = session.get(GeneralItem, item_id)
        if not item:
            abort(404, "Item not found")

        name = (request.form.get("name") or "").strip()
        if name:
            item.name = name
        item.description = optional_str(request.form.get("description"))
        item.reservation_id = optional_str(request.form.get("reservation_id"))
        item.price = parse_float(request.form.get("price"))
        item.link = optional_str(request.form.get("link"))
        item.maps_link = optional_str(request.form.get("maps_link"))
        item.cancelable = parse_bool(request.form.get("cancelable"))

        session.commit()
        if request.headers.get("HX-Request"):
            trip = item.trip
            general_items = sorted(
                trip.general_items,
                key=lambda gi: ((gi.name or "").lower(), gi.id),
            )
            return render_template(
                "partials/general_items.html",
                trip=trip,
                general_items=general_items,
            )
        return redirect(url_for("main.view_trip_page", trip_id=item.trip_id))
    finally:
        session.close()


@bp.post("/days/<int:day_id>/delete")
def delete_day_page(day_id: int):
    session = get_session()
    try:
        day = session.get(Day, day_id)
        if not day:
            abort(404, "Day not found")
        trip_id = day.trip_id
        session.delete(day)
        session.commit()
        if request.headers.get("HX-Request"):
            resp = make_response("")
            resp.headers["HX-Redirect"] = url_for(
                "main.view_trip_page", trip_id=trip_id
            )
            return resp
        return redirect(url_for("main.view_trip_page", trip_id=trip_id))
    finally:
        session.close()


@bp.post("/general-items/<int:item_id>/delete")
def delete_general_item_page(item_id: int):
    session = get_session()
    try:
        item = session.get(GeneralItem, item_id)
        if not item:
            abort(404, "Item not found")
        trip_id = item.trip_id
        trip = item.trip
        session.delete(item)
        session.commit()
        if request.headers.get("HX-Request"):
            general_items = sorted(
                trip.general_items,
                key=lambda gi: ((gi.name or "").lower(), gi.id),
            )
            return render_template(
                "partials/general_items.html",
                trip=trip,
                general_items=general_items,
            )
        return redirect(url_for("main.view_trip_page", trip_id=trip_id))
    finally:
        session.close()


@bp.post("/days/<int:day_id>/activities")
def create_activity_page(day_id: int):
    session = get_session()
    try:
        day = session.get(Day, day_id)
        if not day:
            abort(404, "Day not found")

        name = (request.form.get("name") or "").strip()
        if not name:
            abort(400, "Activity name is required")

        activity = Activity(
            day=day,
            name=name,
            description=optional_str(request.form.get("description")),
            location=optional_str(request.form.get("location")),
            price=parse_float(request.form.get("price")),
            reservation_id=optional_str(request.form.get("reservation_id")),
            link=optional_str(request.form.get("link")),
            maps_link=optional_str(request.form.get("maps_link")),
            cancelable=parse_bool(request.form.get("cancelable")),
        )
        session.add(activity)
        session.commit()
        if request.headers.get("HX-Request"):
            session.refresh(day)
            return render_template(
                "partials/day_activities.html", day=day, activities=day.activities
            )
        return redirect(url_for("main.view_trip_page", trip_id=day.trip_id))
    finally:
        session.close()


@bp.post("/activities/<int:activity_id>")
def update_activity_page(activity_id: int):
    session = get_session()
    try:
        activity = session.get(Activity, activity_id)
        if not activity:
            abort(404, "Activity not found")

        name = (request.form.get("name") or "").strip()
        if name:
            activity.name = name
        activity.description = optional_str(request.form.get("description"))
        activity.location = optional_str(request.form.get("location"))
        activity.price = parse_float(request.form.get("price"))
        activity.reservation_id = optional_str(request.form.get("reservation_id"))
        activity.link = optional_str(request.form.get("link"))
        activity.maps_link = optional_str(request.form.get("maps_link"))
        activity.cancelable = parse_bool(request.form.get("cancelable"))

        session.commit()
        if request.headers.get("HX-Request"):
            day = activity.day
            session.refresh(day)
            return render_template(
                "partials/day_activities.html", day=day, activities=day.activities
            )
        return redirect(url_for("main.view_trip_page", trip_id=activity.day.trip_id))
    finally:
        session.close()


@bp.post("/activities/<int:activity_id>/delete")
def delete_activity_page(activity_id: int):
    session = get_session()
    try:
        activity = session.get(Activity, activity_id)
        if not activity:
            abort(404, "Activity not found")
        trip_id = activity.day.trip_id
        day = activity.day
        session.delete(activity)
        session.commit()
        if request.headers.get("HX-Request"):
            session.refresh(day)
            return render_template(
                "partials/day_activities.html", day=day, activities=day.activities
            )
        return redirect(url_for("main.view_trip_page", trip_id=trip_id))
    finally:
        session.close()
@bp.get("/trips/<int:trip_id>/maps-itinerary")
def itinerary_maps_url(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")
        ordered_days = sorted(
            trip.days,
            key=lambda d: (d.date or date.max, d.id),
        )
        payload_like = {
            "days": [
                {
                    "date": day.date.isoformat() if day.date else None,
                    "hotel": {
                        "name": day.hotel_name,
                        "location": day.hotel_location,
                    },
                    "activities": [
                        {"name": a.name, "location": a.location}
                        for a in day.activities
                        if a.location
                    ],
                }
                for day in ordered_days
            ]
        }
        maps_url = build_itinerary_maps_url(payload_like)
        if not maps_url:
            return jsonify({"url": None, "error": "Need at least 2 days with a location (hotel or activity)"}), 404
        return jsonify({"url": maps_url})
    finally:
        session.close()
