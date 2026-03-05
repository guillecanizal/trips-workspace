"""MCP server exposing the Trip Planner as AI-accessible tools.

Run via stdio (spawned by Claude Code / OpenCode automatically).
Flask must be running at TRIP_API_URL (default http://localhost:5000).

Usage (smoke test):
    python agent/mcp_server.py

Configuration for OpenCode (opencode.json):
    {
      "mcp": {
        "trip-planner": {
          "type": "local",
          "command": ["python", "agent/mcp_server.py"],
          "enabled": true,
          "environment": { "TRIP_API_URL": "http://localhost:5000" },
          "timeout": 30000
        }
      }
    }

Configuration for Claude Code:
    claude mcp add trip-planner -- python agent/mcp_server.py
"""

from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

from .schemas import ActivityInput, CreateTripInput, GeneralItemInput, HotelInput, PlanDayInput, UpdateTripInput
from . import tools

mcp = FastMCP(
    name="trip-planner",
    instructions=(
        "Tools for managing travel itineraries. "
        "Flask must be running at http://localhost:5000 (or TRIP_API_URL). "
        "Use list_trips to explore, create_trip to start a new trip, "
        "then plan_day for each day to build a complete itinerary."
    ),
)


@mcp.tool()
def list_trips() -> list[dict]:
    """List all trips with a short summary (id, name, destination, dates, day count, total budget).
    Use this first to discover existing trips and their IDs."""
    return tools.list_trips()


@mcp.tool()
def get_trip(trip_id: int) -> dict:
    """Get full details of a trip: all days with their hotel, activities, and computed KPIs.
    Days are returned with a day_number field (1-based) for use with plan_day and other tools.
    Always call this after create_trip to see the day structure before planning."""
    return tools.get_trip(trip_id)


@mcp.tool()
def create_trip(
    name: str,
    destination: str,
    start_date: str,
    end_date: str,
    description: str | None = None,
) -> dict:
    """Create a new trip. Days are auto-created (one per calendar day).
    Returns the full trip including day_number for each day — use these with plan_day.

    Args:
        name: Trip name, e.g. 'Kyoto Autumn 2026'
        destination: Main destination, e.g. 'Kyoto, Japan'
        start_date: ISO format YYYY-MM-DD
        end_date: ISO format YYYY-MM-DD
        description: Optional extra notes
    """
    return tools.create_trip(
        CreateTripInput(
            name=name,
            destination=destination,
            start_date=start_date,
            end_date=end_date,
            description=description,
        )
    )


@mcp.tool()
def update_trip(
    trip_id: int,
    name: str | None = None,
    description: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Update trip metadata. Only provided fields are changed."""
    return tools.update_trip(
        UpdateTripInput(
            trip_id=trip_id,
            name=name,
            description=description,
            start_date=start_date,
            end_date=end_date,
        )
    )


@mcp.tool()
def plan_day(
    trip_id: int,
    day_number: int,
    hotel_name: str | None = None,
    hotel_price: float | None = None,
    hotel_location: str | None = None,
    hotel_description: str | None = None,
    hotel_reservation_id: str | None = None,
    hotel_link: str | None = None,
    activities: list[dict] | None = None,
    distance_km: float | None = None,
    distance_hours: int | None = None,
    distance_minutes: int | None = None,
) -> dict:
    """Configure a complete day in one call: set hotel and add all activities.

    This is the primary tool for building itineraries day by day.
    Returns the planned day plus running trip KPIs so you can track budget after each day.

    Args:
        trip_id: Trip ID
        day_number: 1-based day number (1 = first day)
        hotel_name: Hotel name. Omit if same hotel as previous day or no overnight stay.
        hotel_price: Price per night in euros
        hotel_location: Hotel neighborhood or address
        hotel_description: Short description
        hotel_reservation_id: Booking reference
        hotel_link: Booking URL
        activities: List of activity dicts with keys: name (required), price, location,
                    description, reservation_id, link, cancelable
        distance_km: Driving distance to this day's destination in km
        distance_hours: Drive time hours component
        distance_minutes: Drive time minutes component (0-59)

    Example activities:
        [
          {"name": "Fushimi Inari Shrine", "price": 0, "location": "Fushimi, Kyoto"},
          {"name": "Nishiki Market visit", "price": 15, "location": "Nakagyo, Kyoto"},
          {"name": "Tea ceremony", "price": 45, "location": "Gion, Kyoto", "cancelable": true}
        ]
    """
    hotel: HotelInput | None = None
    if hotel_name is not None:
        hotel = HotelInput(
            name=hotel_name,
            price=hotel_price,
            location=hotel_location,
            description=hotel_description,
            reservation_id=hotel_reservation_id,
            link=hotel_link,
        )

    activity_inputs: list[ActivityInput] = []
    for a in activities or []:
        activity_inputs.append(
            ActivityInput(
                name=a["name"],
                price=a.get("price"),
                location=a.get("location"),
                description=a.get("description"),
                reservation_id=a.get("reservation_id"),
                link=a.get("link"),
                cancelable=a.get("cancelable"),
            )
        )

    return tools.plan_day(
        PlanDayInput(
            trip_id=trip_id,
            day_number=day_number,
            hotel=hotel,
            activities=activity_inputs,
            distance_km=distance_km,
            distance_hours=distance_hours,
            distance_minutes=distance_minutes,
        )
    )


@mcp.tool()
def set_hotel(
    trip_id: int,
    day_number: int,
    name: str,
    price: float | None = None,
    location: str | None = None,
    description: str | None = None,
    reservation_id: str | None = None,
    link: str | None = None,
    cancelable: bool | None = None,
) -> dict:
    """Set or replace the hotel for a specific day. Use for incremental edits after plan_day."""
    return tools.set_hotel(
        trip_id,
        day_number,
        HotelInput(
            name=name,
            price=price,
            location=location,
            description=description,
            reservation_id=reservation_id,
            link=link,
            cancelable=cancelable,
        ),
    )


@mcp.tool()
def add_activity(
    trip_id: int,
    day_number: int,
    name: str,
    price: float | None = None,
    location: str | None = None,
    description: str | None = None,
    reservation_id: str | None = None,
    link: str | None = None,
    cancelable: bool | None = None,
) -> dict:
    """Add a single activity to a specific day. Use for incremental edits after plan_day."""
    return tools.add_activity(
        trip_id,
        day_number,
        ActivityInput(
            name=name,
            price=price,
            location=location,
            description=description,
            reservation_id=reservation_id,
            link=link,
            cancelable=cancelable,
        ),
    )


@mcp.tool()
def remove_activity(trip_id: int, day_number: int, activity_name: str) -> dict:
    """Remove an activity by name from a specific day.
    Use get_trip first to see the exact activity names on each day.
    If there are duplicates, the first match is removed."""
    return tools.remove_activity(trip_id, day_number, activity_name)


@mcp.tool()
def add_general_item(
    trip_id: int,
    name: str,
    price: float | None = None,
    description: str | None = None,
    reservation_id: str | None = None,
    link: str | None = None,
    cancelable: bool | None = None,
) -> dict:
    """Add a trip-level general item: flights, car rental, travel insurance, visas, etc.
    These are costs that apply to the whole trip rather than a specific day.
    They are included in the total budget shown in the app."""
    return tools.add_general_item(
        trip_id,
        GeneralItemInput(
            name=name,
            price=price,
            description=description,
            reservation_id=reservation_id,
            link=link,
            cancelable=cancelable,
        ),
    )


@mcp.tool()
def remove_general_item(trip_id: int, item_name: str) -> dict:
    """Remove a general item by name from a trip.
    Use get_trip first to see the exact item names."""
    return tools.remove_general_item(trip_id, item_name)


@mcp.tool()
def save_tagline(trip_id: int, day_number: int, tagline: str) -> dict:
    """Save a short evocative tagline for a specific day (2–5 words, no punctuation at the end).
    Call once per day after all days have been planned."""
    return tools.save_tagline(trip_id, day_number, tagline)


@mcp.tool()
def export_trip(trip_id: int, format: str = "pdf") -> dict:
    """Get download and view links for the completed trip.
    Flask must be running for the URLs to be accessible.

    Args:
        trip_id: Trip ID
        format: 'pdf' (formatted guide) or 'csv' (spreadsheet). Defaults to 'pdf'.

    Returns a dict with:
      - url: direct download link for the export file
      - web_url: link to view the trip in the web UI
      - maps_url: Google Maps directions link for the full itinerary (if available)
    Always show all three links to the user in the final summary.
    """
    return tools.export_trip(trip_id, format)


if __name__ == "__main__":
    # Smoke test mode: python agent/mcp_server.py --test
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        import httpx as _httpx
        import os

        api_url = os.environ.get("TRIP_API_URL", "http://localhost:5000")
        try:
            r = _httpx.get(f"{api_url}/api/trips", timeout=5.0)
            r.raise_for_status()
            print(f"Flask OK — {len(r.json())} trips found")
        except Exception as e:
            print(f"Flask not reachable at {api_url}: {e}", file=sys.stderr)
            sys.exit(1)

        registered = [t.name for t in mcp._tool_manager.list_tools()]
        print(f"MCP tools registered: {registered}")
        print("Smoke test passed.")
        sys.exit(0)

    mcp.run()
