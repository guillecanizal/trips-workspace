"""Minimal data access helpers for the AI agent endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict

from flask import current_app

from .models import Activity, Day, Trip


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
