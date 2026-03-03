"""Tests for the REST API endpoints and input-parsing helpers."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Trips CRUD
# ---------------------------------------------------------------------------


def _create_trip(client, *, name="Test Trip", start="2026-06-01", end="2026-06-03"):
    return client.post(
        "/api/trips",
        json={"name": name, "start_date": start, "end_date": end},
    )


class TestCreateTrip:
    def test_returns_201_and_trip_data(self, client):
        resp = _create_trip(client)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Test Trip"
        assert data["start_date"] == "2026-06-01"
        assert data["end_date"] == "2026-06-03"

    def test_auto_creates_sequential_days(self, client):
        resp = _create_trip(client, start="2026-06-01", end="2026-06-03")
        data = resp.get_json()
        assert len(data["days"]) == 3
        dates = [d["date"] for d in data["days"]]
        assert "2026-06-01" in dates
        assert "2026-06-03" in dates

    def test_missing_name_returns_400(self, client):
        resp = client.post(
            "/api/trips", json={"start_date": "2026-06-01", "end_date": "2026-06-03"}
        )
        assert resp.status_code == 400

    def test_end_before_start_returns_400(self, client):
        resp = _create_trip(client, start="2026-06-10", end="2026-06-01")
        assert resp.status_code == 400

    def test_invalid_date_format_returns_400(self, client):
        resp = client.post(
            "/api/trips",
            json={"name": "Bad", "start_date": "June 1st", "end_date": "2026-06-03"},
        )
        assert resp.status_code == 400


class TestListTrips:
    def test_empty_database_returns_empty_list(self, client):
        resp = client.get("/api/trips")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_returns_created_trips(self, client):
        _create_trip(client, name="Trip A")
        _create_trip(client, name="Trip B")
        resp = client.get("/api/trips")
        names = [t["name"] for t in resp.get_json()]
        assert "Trip A" in names
        assert "Trip B" in names


class TestGetTrip:
    def test_returns_trip_by_id(self, client):
        trip_id = _create_trip(client).get_json()["id"]
        resp = client.get(f"/api/trips/{trip_id}")
        assert resp.status_code == 200
        assert resp.get_json()["id"] == trip_id

    def test_unknown_id_returns_404(self, client):
        resp = client.get("/api/trips/9999")
        assert resp.status_code == 404


class TestDeleteTrip:
    def test_delete_returns_204(self, client):
        trip_id = _create_trip(client).get_json()["id"]
        resp = client.delete(f"/api/trips/{trip_id}")
        assert resp.status_code == 204

    def test_deleted_trip_is_gone(self, client):
        trip_id = _create_trip(client).get_json()["id"]
        client.delete(f"/api/trips/{trip_id}")
        assert client.get(f"/api/trips/{trip_id}").status_code == 404

    def test_delete_unknown_returns_404(self, client):
        assert client.delete("/api/trips/9999").status_code == 404


class TestUpdateTrip:
    def test_rename_trip(self, client):
        trip_id = _create_trip(client, name="Old Name").get_json()["id"]
        resp = client.put(f"/api/trips/{trip_id}", json={"name": "New Name"})
        assert resp.status_code == 200
        assert resp.get_json()["name"] == "New Name"

    def test_empty_name_returns_400(self, client):
        trip_id = _create_trip(client).get_json()["id"]
        resp = client.put(f"/api/trips/{trip_id}", json={"name": ""})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Parse helpers — exercised through real route calls
# ---------------------------------------------------------------------------


class TestParseBool:
    def _update_day(self, client, value):
        trip = _create_trip(client, start="2026-06-01", end="2026-06-01").get_json()
        day_id = trip["days"][0]["id"]
        return client.put(f"/api/days/{day_id}", json={"hotel_cancelable": value})

    def test_true_string_values(self, client):
        for val in ("true", "1", "yes", "y", "on"):
            resp = self._update_day(client, val)
            assert resp.status_code == 200
            assert resp.get_json()["hotel_cancelable"] is True

    def test_false_string_values(self, client):
        for val in ("false", "0", "no", "n", "off"):
            resp = self._update_day(client, val)
            assert resp.status_code == 200
            assert resp.get_json()["hotel_cancelable"] is False

    def test_invalid_bool_returns_400(self, client):
        resp = self._update_day(client, "maybe")
        assert resp.status_code == 400

    def test_none_value_clears_field(self, client):
        resp = self._update_day(client, None)
        assert resp.status_code == 200
        assert resp.get_json()["hotel_cancelable"] is None


class TestParseFloat:
    def _create_day_with_price(self, client, price):
        trip_id = _create_trip(client).get_json()["id"]
        return client.post(f"/api/trips/{trip_id}/days", json={"hotel_price": price})

    def test_numeric_string_accepted(self, client):
        resp = self._create_day_with_price(client, "89.5")
        assert resp.status_code == 201
        assert resp.get_json()["hotel_price"] == 89.5

    def test_integer_value_accepted(self, client):
        resp = self._create_day_with_price(client, 100)
        assert resp.status_code == 201
        assert resp.get_json()["hotel_price"] == 100.0

    def test_invalid_string_returns_400(self, client):
        resp = self._create_day_with_price(client, "not-a-number")
        assert resp.status_code == 400


class TestParseInt:
    def _create_day_with_minutes(self, client, minutes):
        trip_id = _create_trip(client).get_json()["id"]
        return client.post(
            f"/api/trips/{trip_id}/days", json={"distance_minutes": minutes}
        )

    def test_valid_minutes_accepted(self, client):
        resp = self._create_day_with_minutes(client, 45)
        assert resp.status_code == 201
        assert resp.get_json()["distance_minutes"] == 45

    def test_minutes_above_59_returns_400(self, client):
        resp = self._create_day_with_minutes(client, 60)
        assert resp.status_code == 400

    def test_negative_minutes_returns_400(self, client):
        resp = self._create_day_with_minutes(client, -1)
        assert resp.status_code == 400

    def test_non_integer_string_returns_400(self, client):
        resp = self._create_day_with_minutes(client, "abc")
        assert resp.status_code == 400
