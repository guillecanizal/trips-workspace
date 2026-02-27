"""Minimal data access helpers for the AI agent endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict

from flask import current_app

from .models import Activity, Day, GeneralItem, Trip


def _get_session():
    Session = current_app.session_factory  # type: ignore[attr-defined]
    return Session()


def _serialize_activity(activity: Activity) -> Dict[str, Any]:
    return {
        "id": activity.id,
        "name": activity.name,
        "location": activity.location,
        "description": activity.description,
        "price": activity.price,
        "reservation_id": activity.reservation_id,
        "link": activity.link,
        "maps_link": activity.maps_link,
        "cancelable": activity.cancelable,
    }


def _serialize_day(day: Day) -> Dict[str, Any]:
    return {
        "id": day.id,
        "date": day.date.isoformat() if day.date else None,
        "hotel": {
            "name": day.hotel_name,
            "location": day.hotel_location,
            "description": day.hotel_description,
            "reservation_id": day.hotel_reservation_id,
            "price": day.hotel_price,
            "link": day.hotel_link,
            "maps_link": day.hotel_maps_link,
            "cancelable": day.hotel_cancelable,
        },
        "activities": [_serialize_activity(activity) for activity in day.activities],
    }


def get_trip_compact(trip_id: int) -> Dict[str, Any]:
    session = _get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            raise ValueError("Trip not found")
        ordered_days = sorted(
            trip.days,
            key=lambda item: (item.date or date.max, item.id),
        )
        return {
            "id": trip.id,
            "name": trip.name,
            "description": trip.description,
            "start_date": trip.start_date.isoformat() if trip.start_date else None,
            "end_date": trip.end_date.isoformat() if trip.end_date else None,
            "days": [_serialize_day(day) for day in ordered_days],
        }
    finally:
        session.close()


def _get_day_by_date(trip: Trip, day_iso: str) -> Day:
    for day in trip.days:
        if day.date and day.date.isoformat() == day_iso:
            return day
    raise ValueError("Day not found for given date")


def apply_hotel(trip_id: int, day: str, hotel: Dict[str, Any]) -> Dict[str, Any]:
    session = _get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            raise ValueError("Trip not found")
        target_day = _get_day_by_date(trip, day)
        target_day.hotel_name = hotel.get("name")
        target_day.hotel_location = hotel.get("location")
        description = hotel.get("description") or hotel.get("notes")
        if description is not None:
            target_day.hotel_description = description
        target_day.hotel_reservation_id = hotel.get("reservation_id")
        target_day.hotel_price = hotel.get("price")
        target_day.hotel_link = hotel.get("link")
        target_day.hotel_maps_link = hotel.get("maps_link")
        target_day.hotel_cancelable = hotel.get("cancelable")
        session.commit()
        session.refresh(target_day)
        return _serialize_day(target_day)
    finally:
        session.close()


def apply_activity(trip_id: int, day: str, activity: Dict[str, Any]) -> Dict[str, Any]:
    session = _get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            raise ValueError("Trip not found")
        target_day = _get_day_by_date(trip, day)
        details = activity.get("details") or activity.get("summary") or activity.get("description")
        new_activity = Activity(
            day=target_day,
            name=activity.get("name"),
            location=activity.get("location"),
            description=details,
            price=activity.get("price"),
            reservation_id=activity.get("reservation_id"),
            link=activity.get("link"),
            maps_link=activity.get("maps_link"),
        )
        session.add(new_activity)
        session.commit()
        session.refresh(target_day)
        return _serialize_day(target_day)
    finally:
        session.close()


def get_trip_cost_summary(trip_id: int) -> Dict[str, Any]:
    """Aggregate prices across hotels, activities and general items."""
    session = _get_session()
    try:
        trip = session.get(Trip, trip_id)
        if not trip:
            raise ValueError("trip_not_found")
        ordered_days = sorted(
            trip.days,
            key=lambda d: (d.date or date.max, d.id),
        )
        days_breakdown: list[Dict[str, Any]] = []
        total_hotels = 0.0
        total_activities = 0.0
        for day in ordered_days:
            hotel_cost = day.hotel_price or 0.0
            act_cost = sum(a.price or 0.0 for a in day.activities)
            total_hotels += hotel_cost
            total_activities += act_cost
            days_breakdown.append({
                "date": day.date.isoformat() if day.date else None,
                "hotel": day.hotel_name,
                "hotel_cost": hotel_cost,
                "activities_cost": act_cost,
                "day_total": hotel_cost + act_cost,
            })
        general_items = (
            session.query(GeneralItem)
            .filter(GeneralItem.trip_id == trip_id)
            .all()
        )
        total_general = sum(gi.price or 0.0 for gi in general_items)
        general_breakdown = [
            {"name": gi.name, "cost": gi.price or 0.0}
            for gi in general_items
            if gi.price
        ]
        return {
            "trip_name": trip.name,
            "days": days_breakdown,
            "general_items": general_breakdown,
            "totals": {
                "hotels": total_hotels,
                "activities": total_activities,
                "general_items": total_general,
                "grand_total": total_hotels + total_activities + total_general,
            },
        }
    finally:
        session.close()
