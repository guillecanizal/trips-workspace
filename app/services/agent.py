"""Conversational travel agent using ChatOllama with tool calling."""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from pydantic import BaseModel

from app import dal

MODEL_NAME = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

# ---------------------------------------------------------------------------
# Lazy model initialization
# ---------------------------------------------------------------------------

_model: ChatOllama | None = None
_tool_model: Any = None


def get_model() -> ChatOllama:
    global _model
    if _model is None:
        _model = ChatOllama(model=MODEL_NAME, temperature=0.1, num_ctx=2048)
    return _model


def get_tool_model() -> Any:
    global _tool_model
    if _tool_model is None:
        _tool_model = get_model().bind_tools(TOOLS)
    return _tool_model


# ---------------------------------------------------------------------------
# Pydantic models for structured LLM output
# ---------------------------------------------------------------------------


class ActivityCandidate(BaseModel):
    name: str = ""
    location: str = ""
    summary: str = ""
    details: str = ""
    estimated_time_hours: float = 0
    price: float | None = None
    reservation_id: str | None = None
    link: str = ""


class HotelCandidate(BaseModel):
    name: str = ""
    location: str = ""
    summary: str = ""
    details: str = ""
    price_per_night: float | None = None
    reservation_id: str | None = None
    link: str = ""
    rating: float | None = None


class ActivityCandidatesResponse(BaseModel):
    candidates: list[ActivityCandidate]


class HotelCandidatesResponse(BaseModel):
    candidates: list[HotelCandidate]


DEFAULT_CANDIDATE_COUNT = 5

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_text(value: str | None) -> str:
    return (value or "").strip()


_ES_WORDS = {
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "de",
    "en",
    "que",
    "es",
    "con",
    "para",
    "del",
    "por",
    "qué",
    "cuánto",
    "dame",
    "dime",
    "propón",
    "busca",
    "muéstrame",
}


def _detect_lang(text: str) -> str:
    """Return 'es' if the message looks Spanish, otherwise 'en'."""
    words = set(text.lower().split())
    return "es" if words & _ES_WORDS else "en"


def _resolve_location(day: dict[str, Any]) -> str:
    hotel_location = _clean_text((day.get("hotel") or {}).get("location"))
    if hotel_location:
        return hotel_location
    activities = day.get("activities") or []
    if activities:
        loc = _clean_text((activities[0] or {}).get("location"))
        if loc:
            return loc
    raise ValueError("location_unavailable_for_day")


def _prepare_day_context(trip_id: int, day_index: int) -> tuple[str, str]:
    trip = dal.get_trip_compact(trip_id)
    if not trip:
        raise ValueError("trip_not_found")
    days = trip.get("days") or []
    if day_index < 1 or day_index > len(days):
        raise ValueError("day_index_out_of_range")
    day = days[day_index - 1] or {}
    date = _clean_text(day.get("date"))
    if not date:
        raise ValueError("day_missing_date")
    location = _resolve_location(day)
    return date, location


def _call_llm_for_candidates(
    task: str, location: str, date: str, count: int, lang: str = "es"
) -> list[dict[str, Any]]:
    """Generate candidates using Pydantic structured output."""
    is_hotel = task == "propose_hotels"
    response_model = HotelCandidatesResponse if is_hotel else ActivityCandidatesResponse
    item_type = "hotels" if is_hotel else "tourist activities"

    system_message = (
        f"Generate exactly {count} {item_type} for {location}. "
        f"Return a JSON with a 'candidates' array of {count} items. "
        f"Write all text fields in this language: {lang}."
    )
    user_message = f"Generate {count} {item_type} for {location} on {date}"

    structured = get_model().with_structured_output(response_model)
    result: HotelCandidatesResponse | ActivityCandidatesResponse = structured.invoke(
        [  # type: ignore[assignment]
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ]
    )
    candidates = [c.model_dump() for c in result.candidates]
    if not candidates:
        raise ValueError(f"No candidates generated for {location} on {date}.")
    return candidates


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool("propose_activities", return_direct=False)
def propose_activities(
    trip_id: int, day_index: int, n: int = DEFAULT_CANDIDATE_COUNT, lang: str = "en"
) -> dict[str, Any]:
    """Propose tourist activities for a specific day of the trip.
    Call this whenever the user asks for activity ideas, alternatives, plans or
    things to do on a day — regardless of the language used.
    NEVER list activities as plain text; always call this tool instead.

    Args:
        trip_id: ID del viaje
        day_index: Day number (1-based)
        n: Number of activities to generate
        lang: Language code for the response (e.g. 'en', 'es')
    """
    date, location = _prepare_day_context(trip_id, day_index)
    candidates = _call_llm_for_candidates("propose_activities", location, date, n, lang)
    return {
        "task": "propose_activities",
        "day": date,
        "location": location,
        "candidates": candidates,
    }


@tool("propose_hotels", return_direct=False)
def propose_hotels(
    trip_id: int, day_index: int, n: int = DEFAULT_CANDIDATE_COUNT, lang: str = "en"
) -> dict[str, Any]:
    """Propose hotel options for a specific day of the trip.
    Call this whenever the user asks for hotel ideas, alternatives or accommodation
    on a day — regardless of the language used.
    NEVER list hotels as plain text; always call this tool instead.

    Args:
        trip_id: ID del viaje
        day_index: Day number (1-based)
        n: Number of hotels to generate
        lang: Language code for the response (e.g. 'en', 'es')
    """
    date, location = _prepare_day_context(trip_id, day_index)
    candidates = _call_llm_for_candidates("propose_hotels", location, date, n, lang)
    return {"task": "propose_hotels", "day": date, "location": location, "candidates": candidates}


@tool("estimate_budget", return_direct=False)
def estimate_budget(trip_id: int) -> dict[str, Any]:
    """Calculate the total trip budget broken down by categories.
    Use it when the user asks about the budget, total costs, or expense
    breakdown for the trip (e.g. "how much does the trip cost?").

    Args:
        trip_id: Trip ID
    """
    summary = dal.get_trip_cost_summary(trip_id)
    return {"task": "estimate_budget", **summary}


@tool("summarize_trip", return_direct=False)
def summarize_trip(trip_id: int) -> dict[str, Any]:
    """Generate a narrative prose summary of the trip.
    Use it when the user asks for a summary, narrative, or travel diary
    (e.g. "summarize the trip").

    Args:
        trip_id: Trip ID
    """
    trip = dal.get_trip_compact(trip_id)
    if not trip:
        raise ValueError("trip_not_found")

    days_text = []
    for day in trip.get("days") or []:
        date_str = day.get("date") or "?"
        hotel = (day.get("hotel") or {}).get("name") or "no hotel"
        activities = (
            ", ".join(a.get("name") or "?" for a in (day.get("activities") or []))
            or "no activities"
        )
        days_text.append(f"- {date_str}: Hotel: {hotel}. Activities: {activities}")

    prompt = (
        f"Write a short narrative summary (3-5 paragraphs) of the trip "
        f'"{trip.get("name")}".\n'
        f"Description: {trip.get('description') or 'N/A'}\n"
        f"Itinerary:\n" + "\n".join(days_text) + "\n\n"
        "Use a friendly tone, like a travel diary. "
        "No JSON, plain prose only."
    )

    response = get_model().invoke([{"role": "user", "content": prompt}])
    text = getattr(response, "content", str(response))
    return {"task": "summarize_trip", "trip_name": trip.get("name"), "summary": text}


TOOLS = [propose_activities, propose_hotels, estimate_budget, summarize_trip]
TOOL_REGISTRY: dict[str, Any] = {t.name: t for t in TOOLS}

# ---------------------------------------------------------------------------
# Conversation history (in-memory, per thread)
# ---------------------------------------------------------------------------

_chat_histories: dict[str, list] = {}


def _get_history(thread_id: str) -> list:
    return _chat_histories.setdefault(thread_id, [])


def _append_history(thread_id: str, role: str, content: str) -> None:
    _chat_histories.setdefault(thread_id, []).append({"role": role, "content": content})


def clear_thread(thread_id: str) -> None:
    _chat_histories.pop(thread_id, None)


# ---------------------------------------------------------------------------
# Knowledge enrichment (best-effort, never blocks)
# ---------------------------------------------------------------------------


def _enrich_knowledge_general(trip_id: int, new_info: str) -> None:
    # Skip short conversational replies — not worth an LLM call
    if len(new_info) < 80:
        return
    try:
        trip = dal.get_trip_compact(trip_id)
        current = (trip.get("knowledge_general") or "").strip()

        if not current:
            prompt = (
                "You are a travel information assistant. "
                "Read this chat reply and extract any useful facts about the destination "
                "(geography, culture, climate, currency, language, transport, safety, gastronomy, tips).\n\n"
                f"CHAT REPLY:\n{new_info}\n\n"
                "If the reply contains no destination information, output only the word: NO_UPDATE\n"
                "If it does contain destination facts, output 4-8 short labeled paragraphs. "
                "Do not include the word NO_UPDATE in that case."
            )
        else:
            prompt = (
                "You maintain a destination knowledge document for a trip.\n\n"
                f"CURRENT DOCUMENT:\n{current}\n\n"
                f"NEW CHAT REPLY:\n{new_info}\n\n"
                "Does the new reply contain destination facts that are NOT already in the document?\n"
                "- If YES: rewrite the full document integrating the new facts. Keep it concise and non-redundant.\n"
                "- If NO: output only the word: NO_UPDATE"
            )

        response = get_model().invoke([{"role": "user", "content": prompt}])
        merged = getattr(response, "content", str(response)).strip()
        # Robust check: model may add surrounding text to NO_UPDATE
        if not merged or "NO_UPDATE" in merged.upper():
            return
        dal.update_knowledge_general(trip_id, merged)
    except Exception:  # noqa: S110 — best-effort, intentionally silent
        pass


# ---------------------------------------------------------------------------
# Tagline suggestion
# ---------------------------------------------------------------------------


def suggest_day_tagline(day_id: int) -> str:
    """Generate a 2-5 word tagline for a day. Returns '' on failure."""
    try:
        day_data = dal.get_day_compact(day_id)
        location = (day_data.get("hotel") or {}).get("location") or ""
        activities = [a["name"] for a in day_data.get("activities", []) if a.get("name")]
        if not location and not activities:
            return ""
        parts: list[str] = []
        if location:
            parts.append(f"Location: {location}")
        if activities:
            parts.append("Activities: " + ", ".join(activities[:5]))
        prompt = (
            "You are a travel writer. Given this day's info, write a short evocative tagline "
            "(2 to 5 words, no quotes, no punctuation at the end). "
            "Write it in the same language as the location and activity names provided.\n\n"
            + "\n".join(parts)
            + "\n\nTagline:"
        )
        response = get_model().invoke([{"role": "user", "content": prompt}])
        tagline = getattr(response, "content", str(response)).strip().strip('"').strip("'")
        return tagline[:100]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Main chat stream — message → LLM (with tools) → text or tool result
# ---------------------------------------------------------------------------


def hybrid_chat_stream(
    trip_id: int,
    message: str,
    *,
    thread_id: str | None = None,
    day_id: int | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Stream a conversational response, optionally calling a tool.

    The LLM decides when to call a tool — no keyword pre-filtering.
    When day_id is provided, the day context is injected into the system
    prompt so the user doesn't need to say "día 3".
    """
    tid = thread_id or f"trip_{trip_id}"

    # Build day context if scoped to a specific day
    day_context = ""
    day_detail_block = ""
    resolved_day_index: int | None = None
    if day_id is not None:
        try:
            day_info = dal.get_day_compact(day_id)
            day_index = day_info.get("day_index")
            resolved_day_index = day_index
            day_date = day_info.get("date") or "?"
            hotel = day_info.get("hotel") or {}
            activities = day_info.get("activities") or []
            hotel_location = hotel.get("location") or ""

            day_context = (
                f"The user is viewing Day {day_index} ({day_date}"
                + (f", {hotel_location}" if hotel_location else "")
                + f"). When using tools that require day_index, use {day_index}. "
                "Always respond in the context of this specific day. "
            )

            # Build a detailed block with everything recorded for this day
            lines: list[str] = [f"DAY {day_index} DATA ({day_date}):"]
            hotel_name = hotel.get("name") or ""
            hotel_desc = hotel.get("description") or ""
            hotel_price = hotel.get("price")
            if hotel_name or hotel_location:
                hotel_line = f"  Hotel: {hotel_name or '(unnamed)'}"
                if hotel_location:
                    hotel_line += f" — {hotel_location}"
                if hotel_price is not None:
                    hotel_line += f" (€{hotel_price}/night)"
                lines.append(hotel_line)
                if hotel_desc:
                    lines.append(f"    {hotel_desc}")
            else:
                lines.append("  Hotel: not set")
            if activities:
                lines.append("  Activities:")
                for i, act in enumerate(activities, 1):
                    act_name = act.get("name") or "?"
                    act_loc = act.get("location") or ""
                    act_price = act.get("price")
                    act_desc = act.get("description") or ""
                    act_line = f"    {i}. {act_name}"
                    if act_loc:
                        act_line += f" ({act_loc})"
                    if act_price is not None:
                        act_line += f" — €{act_price}"
                    lines.append(act_line)
                    if act_desc:
                        lines.append(f"       {act_desc}")
            else:
                lines.append("  Activities: none defined")
            day_detail_block = "\n".join(lines)
        except ValueError:
            pass

    yield {"type": "status", "message": "Querying the AI model..."}

    trip = dal.get_trip_compact(trip_id)
    knowledge = (trip.get("knowledge_general") or "").strip()

    system_prompt = (
        "You are a conversational travel planning assistant. "
        + day_context
        + "Respond naturally to questions and comments. "
        "TOOL USAGE RULES:\n"
        "- Proposals/alternatives/ideas for activities or plans → ALWAYS call propose_activities. Never list activities as plain text.\n"
        "- Proposals/alternatives/ideas for hotels or accommodation → ALWAYS call propose_hotels. Never list hotels as plain text.\n"
        "- Questions about budget or costs → call estimate_budget.\n"
        "- Request for trip summary → call summarize_trip.\n"
        "- Any other question (curiosities, distances, schedules, etc.) → reply directly in text.\n\n"
        "TRIP CONTEXT:\n"
        f"Trip ID: {trip_id}\n"
        f"Name: {trip.get('name')}\n"
        f"Dates: {trip.get('start_date')} → {trip.get('end_date')}\n"
        f"Description: {trip.get('description') or 'N/A'}\n"
    )

    if day_detail_block:
        system_prompt += f"\n{day_detail_block}\n"

    if knowledge:
        system_prompt += f"\nDESTINATION INFORMATION:\n{knowledge}\n"

    system_prompt += (
        f"\nAlways use trip_id={trip_id} in tools. Respond in the same language as the user."
    )

    history = _get_history(tid)
    messages = [
        {"role": "system", "content": system_prompt},
        *history[-10:],
        {"role": "user", "content": message},
    ]

    try:
        response = get_tool_model().invoke(messages)
        tool_calls = getattr(response, "tool_calls", None) or (
            getattr(response, "additional_kwargs", {}) or {}
        ).get("tool_calls")

        if tool_calls:
            call = tool_calls[0]
            tool_name = call.get("name")
            tool_impl = TOOL_REGISTRY.get(tool_name or "")
            if not tool_impl:
                yield {"type": "error", "message": f"Unknown tool: {tool_name}"}
                return
            tool_args = dict(call.get("args") or {})
            tool_args.setdefault("trip_id", trip_id)
            if resolved_day_index is not None:
                tool_args.setdefault("day_index", resolved_day_index)
            tool_args.setdefault("lang", _detect_lang(message))
            result = tool_impl.invoke(tool_args)
            _append_history(tid, "user", message)
            _append_history(tid, "assistant", f"[tool:{tool_name}]")
            yield {"type": "result", "data": result}
        else:
            text = getattr(response, "content", str(response)).strip()
            _append_history(tid, "user", message)
            _append_history(tid, "assistant", text)
            yield {"type": "text", "content": text}
            if text:
                _enrich_knowledge_general(trip_id, text)

    except Exception as exc:
        yield {"type": "error", "message": str(exc)}
