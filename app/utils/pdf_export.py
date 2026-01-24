"""PDF export functions for trip planner."""

from __future__ import annotations

import textwrap
from io import BytesIO
from datetime import date

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def generate_trip_pdf(trip, ordered_days, general_items, stats) -> bytes:
    """
    Generate PDF content for a trip.
    
    Args:
        trip: Trip model instance
        ordered_days: List of Day instances sorted by date
        general_items: List of GeneralItem instances
        stats: Dictionary with trip statistics
        
    Returns:
        PDF content as bytes
    """
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

    # Trip header
    add_line(trip.name, font="Helvetica-Bold", size=18)
    add_line(f"{trip.start_date or '?'} → {trip.end_date or '?'}", size=12)
    add_line()
    
    # Trip overview
    add_line("Trip Overview", font="Helvetica-Bold", size=14)
    add_line(f"Days: {stats['day_count']}")
    add_line(f"Activities: {stats['activity_count']}")
    add_line(f"General items: {stats['general_item_count']}")
    add_line(f"Total distance: {stats['total_distance_km'] or 0} km")
    add_line(f"Estimated cost: {('%.2f' % (stats['total_price'] or 0))}")
    add_line()

    # General items section
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

    # Days and activities section
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
    return buffer.getvalue()
