"""Tests for Google Maps URL generation helpers in app/utils/maps.py."""

from __future__ import annotations

import urllib.parse

from app.utils.maps import build_itinerary_maps_url, maps_search_url


class TestMapsSearchUrl:
    def test_returns_google_maps_url(self):
        url = maps_search_url("Hotel Ibis", "Madrid")
        assert url is not None
        assert "google.com/maps/search" in url

    def test_query_is_url_encoded(self):
        url = maps_search_url("Sagrada Família", "Barcelona")
        assert url is not None
        assert "Sagrada" in urllib.parse.unquote(url)
        assert "Barcelona" in urllib.parse.unquote(url)

    def test_none_name_returns_none(self):
        assert maps_search_url(None, "Madrid") is None

    def test_none_location_returns_none(self):
        assert maps_search_url("Hotel", None) is None

    def test_both_none_returns_none(self):
        assert maps_search_url(None, None) is None

    def test_empty_name_returns_none(self):
        assert maps_search_url("", "Madrid") is None


class TestBuildItineraryMapsUrl:
    def _day(self, hotel_location: str | None, activity_location: str | None = None) -> dict:
        activities = [{"name": "Act", "location": activity_location}] if activity_location else []
        return {"hotel": {"name": "H", "location": hotel_location}, "activities": activities}

    def test_two_points_returns_directions_url(self):
        data = {"days": [self._day("Madrid"), self._day("Barcelona")]}
        url = build_itinerary_maps_url(data)
        assert url is not None
        assert "google.com/maps/dir" in url

    def test_three_points_includes_waypoints(self):
        data = {"days": [self._day("Madrid"), self._day("Valencia"), self._day("Barcelona")]}
        url = build_itinerary_maps_url(data)
        assert url is not None
        assert "waypoints" in url
        assert "Valencia" in urllib.parse.unquote(url)

    def test_single_point_returns_none(self):
        data = {"days": [self._day("Madrid")]}
        assert build_itinerary_maps_url(data) is None

    def test_empty_days_returns_none(self):
        assert build_itinerary_maps_url({"days": []}) is None

    def test_consecutive_duplicate_locations_are_deduplicated(self):
        data = {
            "days": [
                self._day("Madrid"),
                self._day("Madrid"),  # same — should be skipped
                self._day("Barcelona"),
            ]
        }
        url = build_itinerary_maps_url(data)
        # Only 2 unique consecutive points → no waypoints
        assert url is not None
        assert "waypoints" not in url

    def test_falls_back_to_activity_when_no_hotel_location(self):
        data = {
            "days": [
                {"hotel": {}, "activities": [{"name": "Prado", "location": "Madrid"}]},
                self._day("Barcelona"),
            ]
        }
        url = build_itinerary_maps_url(data)
        assert url is not None
        assert "Madrid" in urllib.parse.unquote(url)

    def test_non_dict_input_returns_none(self):
        assert build_itinerary_maps_url("not a dict") is None  # type: ignore[arg-type]

    def test_origin_and_destination_are_first_and_last_points(self):
        data = {
            "days": [
                self._day("Madrid"),
                self._day("Valencia"),
                self._day("Barcelona"),
            ]
        }
        url = build_itinerary_maps_url(data)
        assert url is not None
        decoded = urllib.parse.unquote(url)
        origin_pos = decoded.find("origin=") + len("origin=")
        dest_pos = decoded.find("destination=") + len("destination=")
        assert "Madrid" in decoded[origin_pos : origin_pos + 20]
        assert "Barcelona" in decoded[dest_pos : dest_pos + 20]
