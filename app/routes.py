"""Flask routes for the Trip Planner API and basic HTML UI."""

from __future__ import annotations

from datetime import date, timedelta

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)
from sqlalchemy import select

from .models import Activity, Day, GeneralItem, Trip
from .services.ai import AIGenerationError, generate_itinerary


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


def trip_is_empty(trip: Trip) -> bool:
    if trip.general_items:
        return False
    for day in trip.days:
        has_hotel_info = any(
            [
                day.hotel_name,
                day.hotel_reservation_id,
                day.hotel_price,
                day.hotel_link,
                day.hotel_maps_link,
            ]
        )
        if has_hotel_info or day.activities:
            return False
    return True


def _safe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
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
                price=_safe_float(activity_info.get("price")),
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
            link=item.get("link") or None,
        )
        session.add(general_item)
        summary["general_items"] += 1

    return summary


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
                elif attr in {"description", "reservation_id", "link", "maps_link"}:
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

            trip_summaries.append(
                {
                    "trip": trip,
                    "days": ordered_days,
                    "general_items": general_items,
                    "stats": {
                        "total_price": total_price,
                        "total_distance_km": total_distance_km,
                        "day_count": len(ordered_days),
                        "activity_count": total_activities,
                        "general_item_count": total_general_items,
                    },
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
        return render_template(
            "trip_detail.html",
            trip=trip,
            days=ordered_days,
            general_items=general_items,
            can_generate_ai=trip_is_empty(trip),
        )
    finally:
        session.close()


@bp.post("/trips/<int:trip_id>/generate-ai")
def generate_trip_ai(trip_id: int):
    session = get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            abort(404, "Trip not found")

        if not trip_is_empty(trip):
            flash("AI generation is only available for empty trips.", "error")
            return redirect(url_for("main.view_trip_page", trip_id=trip.id))

        day_dates = sorted(day.date for day in trip.days if day.date)
        if not day_dates:
            flash("Trip needs dated days before generating.", "error")
            return redirect(url_for("main.view_trip_page", trip_id=trip.id))

        current_app.logger.info(
            "AI generation requested", extra={"trip_id": trip.id, "days": len(day_dates)}
        )

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
