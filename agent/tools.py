"""MCP tool implementations — call Flask HTTP API, never touch DB directly."""

from __future__ import annotations

import os
from typing import Any

import httpx

import urllib.parse

from .schemas import ActivityInput, CreateTripInput, GeneralItemInput, HotelInput, PlanDayInput, UpdateTripInput

API_BASE = os.environ.get("TRIP_API_URL", "http://localhost:5000")
_TIMEOUT = 30.0


def _get(path: str) -> dict | list:
    r = httpx.get(f"{API_BASE}{path}", timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict) -> dict:
    r = httpx.post(f"{API_BASE}{path}", json=body, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _put(path: str, body: dict) -> dict:
    r = httpx.put(f"{API_BASE}{path}", json=body, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _delete(path: str) -> None:
    r = httpx.delete(f"{API_BASE}{path}", timeout=_TIMEOUT)
    r.raise_for_status()


def _resolve_day_id(trip_id: int, day_number: int) -> int:
    """Convert 1-based day_number to the internal day_id."""
    trip = _get(f"/api/trips/{trip_id}")
    days: list[dict] = sorted(
        trip["days"],  # type: ignore[index]
        key=lambda d: (d.get("date") or "", d["id"]),
    )
    if day_number < 1 or day_number > len(days):
        raise ValueError(
            f"day_number {day_number} out of range — trip has {len(days)} days"
        )
    return days[day_number - 1]["id"]


def _maps_url(name: str | None, location: str | None) -> str | None:
    """Generate a Google Maps search URL from name and location."""
    if not name or not location:
        return None
    query = f"{name}, {location}"
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(query)


def _summarise_trip(trip: dict[str, Any]) -> dict[str, Any]:
    """Return a lightweight trip summary (no raw day/activity lists)."""
    days: list[dict] = trip.get("days", [])
    total_cost = sum(
        (d.get("hotel_price") or 0) + sum(a.get("price") or 0 for a in d.get("activities", []))
        for d in days
    )
    total_cost += sum(gi.get("price") or 0 for gi in trip.get("general_items", []))
    return {
        "id": trip["id"],
        "name": trip["name"],
        "destination": trip.get("description") or "",
        "start_date": trip.get("start_date"),
        "end_date": trip.get("end_date"),
        "day_count": len(days),
        "total_budget_eur": round(total_cost, 2),
    }


def _enrich_trip(trip: dict[str, Any]) -> dict[str, Any]:
    """Return full trip with day_number injected and KPIs computed."""
    days: list[dict] = sorted(
        trip.get("days", []),
        key=lambda d: (d.get("date") or "", d["id"]),
    )
    total_hotel = 0.0
    total_activities = 0.0
    for i, day in enumerate(days):
        day["day_number"] = i + 1
        total_hotel += day.get("hotel_price") or 0
        total_activities += sum(a.get("price") or 0 for a in day.get("activities", []))

    general_items: list[dict] = trip.get("general_items", [])
    total_general = sum(gi.get("price") or 0 for gi in general_items)

    trip["days"] = days
    trip["kpis"] = {
        "total_eur": round(total_hotel + total_activities + total_general, 2),
        "hotel_eur": round(total_hotel, 2),
        "activities_eur": round(total_activities, 2),
        "general_items_eur": round(total_general, 2),
        "day_count": len(days),
        "activity_count": sum(len(d.get("activities", [])) for d in days),
    }
    return trip


# ---------------------------------------------------------------------------
# Public tool functions (called by mcp_server.py)
# ---------------------------------------------------------------------------


def list_trips() -> list[dict[str, Any]]:
    """Return a summary list of all trips."""
    trips: list[dict] = _get("/api/trips")  # type: ignore[assignment]
    return [_summarise_trip(t) for t in trips]


def get_trip(trip_id: int) -> dict[str, Any]:
    """Return full trip with days, activities, and computed KPIs.
    Days include a day_number field (1-based) for use with other tools."""
    trip: dict = _get(f"/api/trips/{trip_id}")  # type: ignore[assignment]
    return _enrich_trip(trip)


def create_trip(data: CreateTripInput) -> dict[str, Any]:
    """Create a new trip. Flask auto-creates one Day per calendar day.
    Returns the full trip so the agent can see day_numbers before calling plan_day."""
    payload = {
        "name": data.name,
        "description": data.destination,
        "start_date": data.start_date,
        "end_date": data.end_date,
    }
    if data.description:
        payload["description"] = f"{data.destination} — {data.description}"
    trip = _post("/api/trips", payload)
    return _enrich_trip(trip)


def update_trip(data: UpdateTripInput) -> dict[str, Any]:
    """Update trip metadata (name, description, dates)."""
    payload: dict[str, Any] = {}
    if data.name is not None:
        payload["name"] = data.name
    if data.description is not None:
        payload["description"] = data.description
    if data.start_date is not None:
        payload["start_date"] = data.start_date
    if data.end_date is not None:
        payload["end_date"] = data.end_date
    trip = _put(f"/api/trips/{data.trip_id}", payload)
    return _enrich_trip(trip)


def plan_day(data: PlanDayInput) -> dict[str, Any]:
    """Configure a complete day: set hotel AND add all activities in one call.
    Existing activities on the day are preserved; hotel is replaced if provided.
    Returns the updated day with day_number and running trip KPIs."""
    day_id = _resolve_day_id(data.trip_id, data.day_number)

    # Set distance fields
    if any(v is not None for v in (data.distance_km, data.distance_hours, data.distance_minutes)):
        dist_payload: dict[str, Any] = {}
        if data.distance_km is not None:
            dist_payload["distance_km"] = data.distance_km
        if data.distance_hours is not None:
            dist_payload["distance_hours"] = data.distance_hours
        if data.distance_minutes is not None:
            dist_payload["distance_minutes"] = data.distance_minutes
        _put(f"/api/days/{day_id}", dist_payload)

    # Set hotel
    if data.hotel is not None:
        _set_hotel_by_id(day_id, data.hotel)

    # Add activities
    added: list[dict] = []
    for activity in data.activities:
        result = _post(f"/api/days/{day_id}/activities", _activity_payload(activity))
        added.append(result)

    # Return enriched trip for budget visibility
    trip = _enrich_trip(_get(f"/api/trips/{data.trip_id}"))  # type: ignore[arg-type]
    days: list[dict] = trip["days"]
    day_detail = next((d for d in days if d["day_number"] == data.day_number), {})
    return {
        "day": day_detail,
        "trip_kpis": trip["kpis"],
    }


def set_hotel(trip_id: int, day_number: int, hotel: HotelInput) -> dict[str, Any]:
    """Replace or set the hotel for a specific day."""
    day_id = _resolve_day_id(trip_id, day_number)
    return _set_hotel_by_id(day_id, hotel)


def add_activity(trip_id: int, day_number: int, activity: ActivityInput) -> dict[str, Any]:
    """Add a single activity to a specific day."""
    day_id = _resolve_day_id(trip_id, day_number)
    return _post(f"/api/days/{day_id}/activities", _activity_payload(activity))


def remove_activity(trip_id: int, day_number: int, activity_name: str) -> dict[str, Any]:
    """Remove an activity by name from a specific day.
    If multiple activities share the same name, the first match is removed."""
    day_id = _resolve_day_id(trip_id, day_number)
    day: dict = _get(f"/api/days/{day_id}")  # type: ignore[assignment]
    activities: list[dict] = day.get("activities", [])
    match = next((a for a in activities if a["name"].lower() == activity_name.lower()), None)
    if match is None:
        raise ValueError(
            f"Activity '{activity_name}' not found on day {day_number}. "
            f"Available: {[a['name'] for a in activities]}"
        )
    _delete(f"/api/activities/{match['id']}")
    return {"removed": match["name"], "day_number": day_number}


def export_trip(trip_id: int, format: str = "pdf") -> dict[str, str]:
    """Return the URL to download the trip export plus web and Maps links.
    Flask must be running for the links to be accessible."""
    fmt = format.lower()
    if fmt not in ("pdf", "csv"):
        raise ValueError("format must be 'pdf' or 'csv'")
    ext = "pdf" if fmt == "pdf" else "csv"
    export_url = f"{API_BASE}/trips/{trip_id}/export.{ext}"
    web_url = f"{API_BASE}/trips/{trip_id}"

    maps_url: str | None = None
    try:
        maps_resp = httpx.get(f"{API_BASE}/trips/{trip_id}/maps-itinerary", timeout=_TIMEOUT)
        if maps_resp.status_code == 200:
            maps_url = maps_resp.json().get("url")
    except Exception:
        pass

    result: dict[str, str] = {"url": export_url, "format": fmt, "trip_id": str(trip_id), "web_url": web_url}
    if maps_url:
        result["maps_url"] = maps_url
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _set_hotel_by_id(day_id: int, hotel: HotelInput) -> dict[str, Any]:
    payload: dict[str, Any] = {"hotel_name": hotel.name}
    if hotel.price is not None:
        payload["hotel_price"] = hotel.price
    if hotel.location is not None:
        payload["hotel_location"] = hotel.location
    if hotel.description is not None:
        payload["hotel_description"] = hotel.description
    if hotel.reservation_id is not None:
        payload["hotel_reservation_id"] = hotel.reservation_id
    if hotel.link is not None:
        payload["hotel_link"] = hotel.link
    if hotel.cancelable is not None:
        payload["hotel_cancelable"] = hotel.cancelable
    maps_link = _maps_url(hotel.name, hotel.location)
    if maps_link is not None:
        payload["hotel_maps_link"] = maps_link
    return _put(f"/api/days/{day_id}", payload)


def _activity_payload(a: ActivityInput) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": a.name}
    if a.price is not None:
        payload["price"] = a.price
    if a.location is not None:
        payload["location"] = a.location
    if a.description is not None:
        payload["description"] = a.description
    if a.reservation_id is not None:
        payload["reservation_id"] = a.reservation_id
    if a.link is not None:
        payload["link"] = a.link
    if a.cancelable is not None:
        payload["cancelable"] = a.cancelable
    maps_link = _maps_url(a.name, a.location)
    if maps_link is not None:
        payload["maps_link"] = maps_link
    return payload


def add_general_item(trip_id: int, item: GeneralItemInput) -> dict[str, Any]:
    """Add a trip-level general item (flight, car rental, insurance, etc.)."""
    payload: dict[str, Any] = {"name": item.name}
    if item.price is not None:
        payload["price"] = item.price
    if item.description is not None:
        payload["description"] = item.description
    if item.reservation_id is not None:
        payload["reservation_id"] = item.reservation_id
    if item.link is not None:
        payload["link"] = item.link
    if item.cancelable is not None:
        payload["cancelable"] = item.cancelable
    return _post(f"/api/trips/{trip_id}/general-items", payload)


def save_tagline(trip_id: int, day_number: int, tagline: str) -> dict[str, Any]:
    """Save a tagline for a specific day."""
    day_id = _resolve_day_id(trip_id, day_number)
    return _post(f"/api/days/{day_id}/tagline", {"tagline": tagline})


def remove_general_item(trip_id: int, item_name: str) -> dict[str, Any]:
    """Remove a general item by name from a trip."""
    items: list[dict] = _get(f"/api/trips/{trip_id}/general-items")  # type: ignore[assignment]
    match = next((i for i in items if i["name"].lower() == item_name.lower()), None)
    if match is None:
        raise ValueError(
            f"General item '{item_name}' not found. "
            f"Available: {[i['name'] for i in items]}"
        )
    _delete(f"/api/general-items/{match['id']}")
    return {"removed": match["name"], "trip_id": trip_id}
