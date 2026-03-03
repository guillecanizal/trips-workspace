"""Tests for pure deterministic helper functions in app/services/agent.py."""

from __future__ import annotations

import pytest

from app.services.agent import _clean_text, _detect_lang, _resolve_location


class TestDetectLang:
    def test_spanish_words_detected(self):
        assert _detect_lang("quiero hoteles en Madrid") == "es"

    def test_spanish_question_detected(self):
        assert _detect_lang("¿qué puedo hacer en Barcelona?") == "es"

    def test_english_returns_en(self):
        assert _detect_lang("I want to visit the museum") == "en"

    def test_empty_string_returns_en(self):
        assert _detect_lang("") == "en"

    def test_mixed_defaults_to_es_when_spanish_words_present(self):
        assert _detect_lang("dame some ideas for activities") == "es"


class TestCleanText:
    def test_strips_whitespace(self):
        assert _clean_text("  hello  ") == "hello"

    def test_none_returns_empty_string(self):
        assert _clean_text(None) == ""

    def test_empty_string_stays_empty(self):
        assert _clean_text("") == ""

    def test_preserves_inner_content(self):
        assert _clean_text("  Sagrada Família  ") == "Sagrada Família"


class TestResolveLocation:
    def test_returns_hotel_location_when_present(self):
        day = {"hotel": {"location": "Madrid Centro"}, "activities": []}
        assert _resolve_location(day) == "Madrid Centro"

    def test_falls_back_to_first_activity_location(self):
        day = {
            "hotel": {"location": ""},
            "activities": [{"location": "Barrio Gótico"}, {"location": "Eixample"}],
        }
        assert _resolve_location(day) == "Barrio Gótico"

    def test_hotel_location_takes_priority_over_activity(self):
        day = {
            "hotel": {"location": "Gracia"},
            "activities": [{"location": "Eixample"}],
        }
        assert _resolve_location(day) == "Gracia"

    def test_raises_when_no_location_available(self):
        day = {"hotel": {}, "activities": []}
        with pytest.raises(ValueError, match="location_unavailable_for_day"):
            _resolve_location(day)

    def test_raises_when_activity_has_no_location(self):
        day = {"hotel": {}, "activities": [{"location": ""}]}
        with pytest.raises(ValueError, match="location_unavailable_for_day"):
            _resolve_location(day)

    def test_none_hotel_dict_falls_back_to_activity(self):
        day = {"hotel": None, "activities": [{"location": "Palma"}]}
        assert _resolve_location(day) == "Palma"
