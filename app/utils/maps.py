"""Helpers for generating Google Maps search URLs for itinerary data."""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict


def maps_search_url(name: str | None, location: str | None) -> str | None:
    """Return a Google Maps search link for the given name/location."""
    if not name or not location:
        return None
    query = f"{name}, {location}"
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(query)


def enrich_with_maps_links(payload: Dict[str, Any]) -> Dict[str, Any]:
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
