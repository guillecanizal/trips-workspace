"""CSV export functions for trip planner."""

from __future__ import annotations

import csv
from io import StringIO
from typing import Any


def generate_trip_csv(trip: Any, ordered_days: Any, general_items: Any, stats: Any) -> str:
    """Generate CSV content for a trip."""
    output = StringIO()
    writer = csv.writer(output)

    # Trip header
    writer.writerow(["Trip Name", trip.name])
    writer.writerow(["Description", trip.description or ""])
    writer.writerow(["Start Date", trip.start_date or ""])
    writer.writerow(["End Date", trip.end_date or ""])
    writer.writerow(["Total Days", stats["day_count"]])
    writer.writerow(["Total Activities", stats["activity_count"]])
    writer.writerow(["Total Distance (km)", stats["total_distance_km"] or 0])
    writer.writerow(["Total Cost", f"{stats['total_price'] or 0:.2f}"])
    writer.writerow([])  # Blank row

    # General Items section
    writer.writerow(["GENERAL ITEMS"])
    writer.writerow(
        ["Name", "Description", "Reservation ID", "Price", "Link", "Maps Link", "Cancelable"]
    )
    for item in general_items:
        writer.writerow(
            [
                item.name,
                item.description or "",
                item.reservation_id or "",
                f"{item.price:.2f}" if item.price is not None else "",
                item.link or "",
                item.maps_link or "",
                item.cancelable if item.cancelable is not None else "",
            ]
        )
    writer.writerow([])  # Blank row

    # Days and Activities section
    writer.writerow(["ITINERARY"])
    writer.writerow(
        [
            "Day",
            "Date",
            "Type",
            "Name",
            "Location",
            "Description",
            "Price",
            "Reservation ID",
            "Link",
            "Maps Link",
            "Cancelable",
            "Distance (km)",
            "Travel Time",
        ]
    )

    for index, day in enumerate(ordered_days, start=1):
        day_date = day.date.isoformat() if day.date else "Unscheduled"

        # Add hotel as first "activity" for the day
        if day.hotel_name:
            travel_time = ""
            if day.distance_hours is not None or day.distance_minutes is not None:
                hours = day.distance_hours or 0
                minutes = day.distance_minutes or 0
                travel_time = f"{hours}h {minutes}m"

            writer.writerow(
                [
                    index,
                    day_date,
                    "Hotel",
                    day.hotel_name,
                    day.hotel_location or "",
                    day.hotel_description or "",
                    f"{day.hotel_price:.2f}" if day.hotel_price is not None else "",
                    day.hotel_reservation_id or "",
                    day.hotel_link or "",
                    day.hotel_maps_link or "",
                    day.hotel_cancelable if day.hotel_cancelable is not None else "",
                    day.distance_km or "",
                    travel_time,
                ]
            )

        # Add activities for the day
        for activity in day.activities:
            writer.writerow(
                [
                    index,
                    day_date,
                    "Activity",
                    activity.name,
                    activity.location or "",
                    activity.description or "",
                    f"{activity.price:.2f}" if activity.price is not None else "",
                    activity.reservation_id or "",
                    activity.link or "",
                    activity.maps_link or "",
                    activity.cancelable if activity.cancelable is not None else "",
                    "",  # Distance only on hotel row
                    "",  # Travel time only on hotel row
                ]
            )

    return output.getvalue()
