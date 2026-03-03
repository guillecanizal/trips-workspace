"""Tests for DAL persistence and retrieval functions."""

from __future__ import annotations

import pytest

from app import dal
from app.models import Activity, Day, Trip
from tests.conftest import make_trip


def test_get_trip_compact_returns_expected_structure(app, db_session):
    trip = make_trip(db_session, start="2026-06-01", end="2026-06-02")
    result = dal.get_trip_compact(trip.id)

    assert result["id"] == trip.id
    assert result["name"] == "Test Trip"
    assert result["start_date"] == "2026-06-01"
    assert result["end_date"] == "2026-06-02"
    assert len(result["days"]) == 2
    assert "hotel" in result["days"][0]
    assert "activities" in result["days"][0]


def test_get_trip_compact_days_ordered_by_date(app, db_session):
    trip = make_trip(db_session, start="2026-06-01", end="2026-06-03")
    result = dal.get_trip_compact(trip.id)

    dates = [d["date"] for d in result["days"]]
    assert dates == sorted(dates)


def test_get_trip_compact_not_found_raises(app):
    with pytest.raises(ValueError, match="Trip not found"):
        dal.get_trip_compact(9999)


def test_update_day_tagline_persists(app, db_session):
    trip = make_trip(db_session, start="2026-06-01", end="2026-06-01")
    trip_id, day_id = trip.id, trip.days[0].id  # capture before dal closes the scoped session

    dal.update_day_tagline(day_id, "Markets & tapas")

    result = dal.get_trip_compact(trip_id)
    assert result["days"][0]["tagline"] == "Markets & tapas"


def test_update_day_tagline_truncates_at_100_chars(app, db_session):
    trip = make_trip(db_session, start="2026-06-01", end="2026-06-01")
    trip_id, day_id = trip.id, trip.days[0].id  # capture before dal closes the scoped session
    long_tagline = "x" * 200

    dal.update_day_tagline(day_id, long_tagline)

    result = dal.get_trip_compact(trip_id)
    assert len(result["days"][0]["tagline"]) == 100


def test_apply_hotel_saves_all_fields(app, db_session):
    trip = make_trip(db_session, start="2026-06-01", end="2026-06-01")
    day_date = "2026-06-01"
    hotel = {
        "name": "Hotel Ibis",
        "location": "Madrid Centro",
        "description": "Budget hotel near Atocha",
        "price": 89.0,
        "cancelable": True,
    }

    result = dal.apply_hotel(trip.id, day_date, hotel)

    assert result["hotel"]["name"] == "Hotel Ibis"
    assert result["hotel"]["location"] == "Madrid Centro"
    assert result["hotel"]["price"] == 89.0
    assert result["hotel"]["cancelable"] is True


def test_apply_hotel_notes_field_as_description(app, db_session):
    """apply_hotel accepts 'notes' as a fallback for description."""
    trip = make_trip(db_session, start="2026-06-01", end="2026-06-01")
    hotel = {"name": "Pension Sol", "location": "Madrid", "notes": "Tiny but central"}

    result = dal.apply_hotel(trip.id, "2026-06-01", hotel)
    assert result["hotel"]["description"] == "Tiny but central"


def test_apply_activity_adds_to_day(app, db_session):
    trip = make_trip(db_session, start="2026-06-01", end="2026-06-01")
    activity = {
        "name": "Prado Museum",
        "location": "Madrid",
        "price": 15.0,
    }

    result = dal.apply_activity(trip.id, "2026-06-01", activity)

    assert len(result["activities"]) == 1
    assert result["activities"][0]["name"] == "Prado Museum"
    assert result["activities"][0]["price"] == 15.0


def test_apply_activity_uses_details_summary_description_fallback(app, db_session):
    trip = make_trip(db_session, start="2026-06-01", end="2026-06-01")
    trip_id = trip.id  # capture before dal closes the scoped session

    dal.apply_activity(trip_id, "2026-06-01", {"name": "A1", "details": "From details"})
    dal.apply_activity(trip_id, "2026-06-01", {"name": "A2", "summary": "From summary"})
    dal.apply_activity(trip_id, "2026-06-01", {"name": "A3", "description": "From desc"})

    result = dal.get_trip_compact(trip_id)
    activities = {a["name"]: a for a in result["days"][0]["activities"]}
    assert activities["A1"]["description"] == "From details"
    assert activities["A2"]["description"] == "From summary"
    assert activities["A3"]["description"] == "From desc"


def test_get_day_compact_returns_correct_day_index(app, db_session):
    trip = make_trip(db_session, start="2026-06-01", end="2026-06-03")
    days_sorted = sorted(trip.days, key=lambda d: d.date)

    result_day1 = dal.get_day_compact(days_sorted[0].id)
    result_day3 = dal.get_day_compact(days_sorted[2].id)

    assert result_day1["day_index"] == 1
    assert result_day3["day_index"] == 3


def test_get_day_compact_includes_trip_context(app, db_session):
    trip = make_trip(db_session, name="Paris Trip", start="2026-06-01", end="2026-06-02")
    day_id = sorted(trip.days, key=lambda d: d.date)[0].id

    result = dal.get_day_compact(day_id)

    assert result["trip_name"] == "Paris Trip"
    assert result["trip_id"] == trip.id


def test_get_day_compact_not_found_raises(app):
    with pytest.raises(ValueError, match="Day not found"):
        dal.get_day_compact(9999)
