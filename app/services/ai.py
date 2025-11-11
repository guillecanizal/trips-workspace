"""Helpers for generating itineraries with a local Ollama model."""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

try:
    from langchain_ollama import ChatOllama
except ImportError:  # pragma: no cover - optional dependency
    ChatOllama = None  # type: ignore


class AIGenerationError(RuntimeError):
    """Raised when the LLM could not generate a usable response."""


def _ensure_logs_dir(trip_id: int, base_path: Optional[Path] = None) -> Path:
    root = base_path or Path("logs")
    path = root / f"trip_{trip_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_trip_prompt(trip_name: str, description: str | None, days: list[date]) -> str:
    days_str = "\n".join(day.isoformat() for day in days)
    desc = description or "(no description provided)"
    return (
        "Trip name: "
        + trip_name
        + "\nDescription: "
        + desc
        + "\nDates (one per line):\n"
        + days_str
        + "\nFor each date produce a place to stay (city or hotel idea) and at least 2-3 thoughtful activities that fit the day."
        + " Cover every listed date exactly once and avoid repeating earlier days."
        + "\nWhen recommending hotels include location (city/area) and a concise description."
        + "\nFor every activity, populate a location (city/town or neighborhood) so travelers know where it happens."
        + "\nFor travel logistics (flights, rentals, ferries, etc.) add entries to general_items."
    )


def _build_messages(prompt: str) -> list[dict[str, str]]:
    schema = {
        "days": [
            {
                "date": "YYYY-MM-DD",
                "hotel": {
                    "name": "",
                    "location": "",
                    "description": "",
                    "notes": ""
                },
                "activities": [
                    {
                        "name": "",
                        "location": "",
                        "summary": "",
                        "details": "",
                        "estimated_time_hours": 0,
                        "price": None,
                        "reservation_id": None,
                        "link": ""
                    }
                ],
            }
        ],
        "general_items": [
            {
                "name": "",
                "description": "",
                "reservation_id": None,
                "price": None,
                "link": "",
                "maps_link": ""
            }
        ],
    }
    rules = "\n".join(
        [
            "Rules:",
            "- Avoid extra commentary or text outside the JSON.",
            "- Each date must appear exactly once.",
            "- If all days belong to the same city, use ONE consistent hotel (same 'name' and 'notes') for all days.",
            "- Always include hotel 'location' and 'description' fields.",
            "- Always include an activity 'location' indicating the city/town or neighborhood.",
            "- Change hotels ONLY when the itinerary moves between different cities or regions.",
            "- When the trip involves multiple locations by car, ensure each next location is within approximately 200–300 km from the previous one.",
            "- Activities must be unique, relevant, and family-friendly if context suggests children are included.",
            "- Always provide at least 2–3 thoughtful activities per day.",
            "- Populate every provided field; use null when data is unknown.",
        ]
    )
    system_prompt = (
        "You are a meticulous travel planner. Respond ONLY with compact JSON. "
        "Use this schema: "
        + json.dumps(schema)
        + "\n"
        + rules
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]


def generate_itinerary(
    trip_id: int,
    trip_name: str,
    description: str | None,
    days: list[date],
    *,
    model: Optional[str] = None,
    client_factory: Optional[Callable[[], Any]] = None,
    logs_dir: Optional[Path] = None,
) -> Tuple[Dict[str, Any], Path]:
    if ChatOllama is None:
        raise AIGenerationError(
            "langchain_ollama is not installed. Install it to enable AI generation."
        )

    if not days:
        raise AIGenerationError("At least one day is required for AI generation.")

    prompt = build_trip_prompt(trip_name, description, days)
    messages = _build_messages(prompt)

    if client_factory:
        chat = client_factory()
    else:
        chat = ChatOllama(
            model=model or os.environ.get("OLLAMA_MODEL", "mistral"),
            temperature=0,
        )

    try:
        response = chat.invoke(messages)
    except Exception as exc:  # pragma: no cover - depends on model availability
        raise AIGenerationError(str(exc)) from exc

    content = getattr(response, "content", None)
    if not content:
        raise AIGenerationError("The LLM returned an empty response.")

    logs_path = _ensure_logs_dir(trip_id, logs_dir)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    prompt_file = logs_path / f"{timestamp}_prompt.txt"
    prompt_content = (
        "SYSTEM:\n"
        + messages[0]["content"]
        + "\n\nUSER:\n"
        + messages[1]["content"]
    )
    prompt_file.write_text(prompt_content)
    response_file = logs_path / f"{timestamp}_response.json"
    response_file.write_text(content)

    try:
        return json.loads(content), response_file
    except json.JSONDecodeError as exc:
        raise AIGenerationError("LLM response was not valid JSON") from exc
