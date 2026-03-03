"""Tests for get_trip_cost_summary — the KPI aggregation logic in dal.py."""

from __future__ import annotations

import pytest

from app import dal
from app.models import Activity, Day, GeneralItem, Trip
from tests.conftest import make_trip


def test_empty_trip_grand_total_is_zero(app, db_session):
    trip = make_trip(db_session)
    result = dal.get_trip_cost_summary(trip.id)
    assert result["totals"]["grand_total"] == 0.0


def test_hotel_costs_are_summed(app, db_session):
    trip = make_trip(db_session, start="2026-06-01", end="2026-06-02")
    days = sorted(trip.days, key=lambda d: d.date)
    days[0].hotel_price = 100.0
    days[1].hotel_price = 150.0
    db_session.commit()

    result = dal.get_trip_cost_summary(trip.id)
    assert result["totals"]["hotels"] == 250.0
    assert result["totals"]["activities"] == 0.0
    assert result["totals"]["grand_total"] == 250.0


def test_activity_costs_are_summed(app, db_session):
    trip = make_trip(db_session, start="2026-06-01", end="2026-06-01")
    day = trip.days[0]
    db_session.add(Activity(day=day, name="Museum", price=15.0))
    db_session.add(Activity(day=day, name="Park", price=0.0))
    db_session.add(Activity(day=day, name="Tour", price=35.0))
    db_session.commit()

    result = dal.get_trip_cost_summary(trip.id)
    assert result["totals"]["activities"] == 50.0
    assert result["totals"]["hotels"] == 0.0


def test_general_items_are_summed(app, db_session):
    trip = make_trip(db_session)
    db_session.add(GeneralItem(trip=trip, name="Flights", price=400.0))
    db_session.add(GeneralItem(trip=trip, name="Insurance", price=60.0))
    db_session.commit()

    result = dal.get_trip_cost_summary(trip.id)
    assert result["totals"]["general_items"] == 460.0


def test_none_prices_treated_as_zero(app, db_session):
    trip = make_trip(db_session, start="2026-06-01", end="2026-06-01")
    day = trip.days[0]
    day.hotel_price = None
    db_session.add(Activity(day=day, name="Free walk", price=None))
    db_session.add(GeneralItem(trip=trip, name="Free entry", price=None))
    db_session.commit()

    result = dal.get_trip_cost_summary(trip.id)
    assert result["totals"]["grand_total"] == 0.0


def test_grand_total_is_hotels_plus_activities_plus_general(app, db_session):
    trip = make_trip(db_session, start="2026-06-01", end="2026-06-01")
    day = trip.days[0]
    day.hotel_price = 120.0
    db_session.add(Activity(day=day, name="Concert", price=80.0))
    db_session.add(GeneralItem(trip=trip, name="Train", price=50.0))
    db_session.commit()

    result = dal.get_trip_cost_summary(trip.id)
    totals = result["totals"]
    assert totals["hotels"] == 120.0
    assert totals["activities"] == 80.0
    assert totals["general_items"] == 50.0
    assert totals["grand_total"] == 250.0


def test_days_breakdown_per_day_total(app, db_session):
    trip = make_trip(db_session, start="2026-06-01", end="2026-06-01")
    day = trip.days[0]
    day.hotel_price = 100.0
    db_session.add(Activity(day=day, name="Activity", price=40.0))
    db_session.commit()

    result = dal.get_trip_cost_summary(trip.id)
    assert len(result["days"]) == 1
    assert result["days"][0]["day_total"] == 140.0


def test_trip_not_found_raises(app):
    with pytest.raises(ValueError, match="trip_not_found"):
        dal.get_trip_cost_summary(9999)
