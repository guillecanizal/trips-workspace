"""Helpers for generating Google Maps search URLs for itinerary data."""

from __future__ import annotations

import urllib.parse
from typing import Any


def maps_search_url(name: str | None, location: str | None) -> str | None:
    """Return a Google Maps search link for the given name/location."""
    if not name or not location:
        return None
    query = f"{name}, {location}"
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(query)


def enrich_with_maps_links(payload: dict[str, Any]) -> dict[str, Any]:
    """Add maps_link fields to hotels/activities within the LLM payload."""
    if not isinstance(payload, dict):
        return payload

    days = payload.get("days") or []
    for day in days:
        if not isinstance(day, dict):
            continue
        hotel = day.get("hotel")
        if isinstance(hotel, dict):
            hotel["maps_link"] = maps_search_url(
                (hotel.get("name") or "").strip() or None,
                (hotel.get("location") or "").strip() or None,
            )

        activities = day.get("activities") or []
        for activity in activities:
            if not isinstance(activity, dict):
                continue
            activity["maps_link"] = maps_search_url(
                (activity.get("name") or "").strip() or None,
                (activity.get("location") or "").strip() or None,
            )

    return payload


def _clean_point(name: str | None, location: str | None) -> str | None:
    """Return a Maps-ready string. Name is optional — location alone is enough."""
    location = (location or "").strip()
    if not location:
        return None
    name = (name or "").strip()
    return f"{name}, {location}" if name else location


def build_itinerary_maps_url(data: dict[str, Any]) -> str | None:
    """Return a Maps Directions URL using hotel locations, falling back to activity locations."""
    if not isinstance(data, dict):
        return None

    days = data.get("days") or []
    if not isinstance(days, list):
        return None

    points: list[str] = []
    last_point: str | None = None
    for day in days:
        if not isinstance(day, dict):
            continue

        # Prefer hotel location
        hotel = day.get("hotel") or {}
        point = _clean_point(hotel.get("name"), hotel.get("location"))

        # Fall back to first activity with a location
        if not point:
            for activity in day.get("activities") or []:
                if not isinstance(activity, dict):
                    continue
                point = _clean_point(activity.get("name"), activity.get("location"))
                if point:
                    break

        if not point or point == last_point:
            continue
        points.append(point)
        last_point = point

    if len(points) < 2:
        return None

    origin = urllib.parse.quote(points[0])
    destination = urllib.parse.quote(points[-1])
    waypoints_segment = ""
    if len(points) > 2:
        waypoint_str = "|".join(points[1:-1])
        waypoints_segment = "&waypoints=" + urllib.parse.quote(waypoint_str, safe="|, ")

    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={origin}"
        f"&destination={destination}"
        f"{waypoints_segment}"
    )
