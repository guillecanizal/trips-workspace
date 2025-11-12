"""Flask routes for the Trip Planner API and basic HTML UI."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from io import BytesIO
import json
import re
import textwrap

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect,
                   render_template, request, send_file, session as flask_session, url_for)
from sqlalchemy import select

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from .models import Activity, Day, GeneralItem, Trip
from .services.ai import AIGenerationError, generate_itinerary, build_full_prompt_text
from .services.agent import run_simple_agent
from .utils.maps import enrich_with_maps_links, build_itinerary_maps_url
from . import dal


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
def health_check() -> str:
    """Simple greeting so we know the app is alive."""

    return "Hello Trip Planner"


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

        return render_template("index.html", trip_summaries=trip_summaries)
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
        total_distance_km = sum(
            distance
            for distance in (day.distance_km for day in ordered_days)
            if distance is not None
        )
        total_activities = sum(len(day.activities) for day in ordered_days)
        total_general_items = len(general_items)
        total_price = sum(
            value
            for value in [
                *(day.hotel_price for day in ordered_days),
                *(
                    activity.price
                    for day in ordered_days
                    for activity in day.activities
                ),
                *(item.price for item in general_items),
            ]
            if value is not None
        )
        ai_log = load_latest_ai_log(trip.id)
        stats = calculate_trip_stats(ordered_days, general_items)
        manual_prompt = flask_session.pop("manual_ai_prompt", None)
        prompt_text = manual_prompt or (ai_log["prompt"] if ai_log else "No prompt available yet.")
        response_text = ai_log["response"] if ai_log else ""
        return render_template(
            "trip_detail.html",
            trip=trip,
            days=ordered_days,
            general_items=general_items,
            ai_log=ai_log,
            stats=stats,
            show_ai_sidebar=request.args.get("show_ai") == "1",
            ai_prompt_text=prompt_text,
            ai_response_text=response_text,
        )
    finally:
        session.close()


@bp.get("/trips/<int:trip_id>/export.pdf")
def export_trip_pdf(trip_id: int):
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

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=letter)
        _, height = letter
        left_margin = 50
        line_height = 14
        current_y = height - 60

        def ensure_space(lines: int = 1):
            nonlocal current_y
            if current_y - (line_height * lines) < 40:
                pdf.showPage()
                current_y = height - 60

        def add_line(content: str = "", *, font: str = "Helvetica", size: int = 11, wrap: int = 90):
            nonlocal current_y
            pdf.setFont(font, size)
            if not content:
                ensure_space()
                current_y -= line_height
                return
            segments = textwrap.wrap(content, wrap) or [content]
            for segment in segments:
                ensure_space()
                pdf.drawString(left_margin, current_y, segment)
                current_y -= line_height

        def add_link_line(label: str, url: str | None, *, font: str = "Helvetica", size: int = 11):
            nonlocal current_y
            if not url:
                return
            text = f"{label}: Open in Google Maps"
            width = pdf.stringWidth(text, font, size)
            ensure_space()
            pdf.setFont(font, size)
            pdf.drawString(left_margin, current_y, text)
            pdf.linkURL(url, (left_margin, current_y - 2, left_margin + width, current_y + 10))
            current_y -= line_height

        add_line(trip.name, font="Helvetica-Bold", size=18)
        add_line(f"{trip.start_date or '?'} → {trip.end_date or '?'}", size=12)
        add_line()
        add_line("Trip Overview", font="Helvetica-Bold", size=14)
        add_line(f"Days: {stats['day_count']}")
        add_line(f"Activities: {stats['activity_count']}")
        add_line(f"General items: {stats['general_item_count']}")
        add_line(f"Total distance: {stats['total_distance_km'] or 0} km")
        add_line(
            f"Estimated cost: {('%.2f' % (stats['total_price'] or 0))}"
        )
        add_line()

        add_line("General Items", font="Helvetica-Bold", size=14)
        if general_items:
            for item in general_items:
                add_line(f"• {item.name}", font="Helvetica-Bold", size=12)
                if item.description:
                    add_line(f"  Description: {item.description}")
                if item.reservation_id:
                    add_line(f"  Reservation: {item.reservation_id}")
                if item.price is not None:
                    add_line(f"  Price: {'%.2f' % item.price}")
                if item.link:
                    add_line(f"  Link: {item.link}")
                add_link_line("  Map", item.maps_link)
                add_line()
        else:
            add_line("No general items recorded.")
            add_line()

        for index, day in enumerate(ordered_days, start=1):
            add_line(f"Day {index} – {day.date or 'Unscheduled day'}", font="Helvetica-Bold", size=14)
            add_line(f"Hotel: {day.hotel_name or '-'}")
            add_line(f"Location: {day.hotel_location or '-'}")
            add_link_line("Map", day.hotel_maps_link)
            if day.hotel_description:
                add_line(f"Description: {day.hotel_description}")
            if day.hotel_reservation_id:
                add_line(f"Reservation: {day.hotel_reservation_id}")
            if day.hotel_price is not None:
                add_line(f"Hotel price: {'%.2f' % day.hotel_price}")
            if day.distance_km is not None:
                add_line(f"Distance: {day.distance_km} km")
            travel_time = []
            if day.distance_hours is not None:
                travel_time.append(f"{day.distance_hours}h")
            if day.distance_minutes is not None:
                travel_time.append(f"{day.distance_minutes}m")
            if travel_time:
                add_line(f"Travel time: {' '.join(travel_time)}")

            if day.activities:
                add_line("Activities:", font="Helvetica-Bold", size=12)
                for activity in day.activities:
                    add_line(f"  • {activity.name}", font="Helvetica-Bold", size=11)
                    if activity.location:
                        add_line(f"    Location: {activity.location}")
                    if activity.description:
                        add_line(f"    {activity.description}")
                    details = []
                    if activity.price is not None:
                        details.append(f"Price {'%.2f' % activity.price}")
                    if activity.reservation_id:
                        details.append(f"Reservation {activity.reservation_id}")
                    if details:
                        add_line("    " + " | ".join(details))
                    if activity.link:
                        add_line(f"    Link: {activity.link}")
                    add_link_line("    Map", activity.maps_link)
                add_line()
            else:
                add_line("No activities planned.")
                add_line()

        pdf.save()
        buffer.seek(0)

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


@bp.post("/agent")
def agent_chat():
    payload = request.get_json(silent=True) or {}
    trip_id = payload.get("trip_id")
    message = (payload.get("message") or "").strip()
    if not trip_id or not message:
        return jsonify({"error": "trip_id and message are required"}), 400
    try:
        result = run_simple_agent(trip_id, message)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    flask_session.pop(_pending_key(trip_id), None)
    return jsonify({"result": result, "pending_patch": None})


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
        session.delete(item)
        session.commit()
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
        session.delete(activity)
        session.commit()
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
                }
                for day in ordered_days
            ]
        }
        maps_url = build_itinerary_maps_url(payload_like)
        if not maps_url:
            return jsonify({"url": None, "error": "Insufficient hotel data"}), 404
        return jsonify({"url": maps_url})
    finally:
        session.close()
