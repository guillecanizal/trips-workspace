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
    task: str, location: str, date: str, count: int
) -> list[dict[str, Any]]:
    """Generate candidates using Pydantic structured output."""
    is_hotel = task == "propose_hotels"
    response_model = HotelCandidatesResponse if is_hotel else ActivityCandidatesResponse
    item_type = "hoteles" if is_hotel else "actividades turísticas"

    system_message = (
        f"Genera exactamente {count} {item_type} para {location}. "
        f"Devuelve un JSON con un array 'candidates' de {count} elementos."
    )
    user_message = f"Genera {count} {item_type} para {location} el día {date}"

    structured = get_model().with_structured_output(response_model)
    result: HotelCandidatesResponse | ActivityCandidatesResponse = structured.invoke([  # type: ignore[assignment]
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ])
    candidates = [c.model_dump() for c in result.candidates]
    if not candidates:
        raise ValueError(f"El modelo no generó candidatos para {location} el {date}.")
    return candidates


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool("propose_activities", return_direct=False)
def propose_activities(
    trip_id: int, day_index: int, n: int = DEFAULT_CANDIDATE_COUNT
) -> dict[str, Any]:
    """Propone actividades turísticas para un día específico del viaje.
    Úsala cuando el usuario pida explícitamente actividades, planes o qué hacer
    en un día concreto (e.g. "propón actividades para el día 3").

    Args:
        trip_id: ID del viaje
        day_index: Número del día (1-based)
        n: Cantidad de actividades a generar
    """
    date, location = _prepare_day_context(trip_id, day_index)
    candidates = _call_llm_for_candidates("propose_activities", location, date, n)
    return {"task": "propose_activities", "day": date, "location": location, "candidates": candidates}


@tool("propose_hotels", return_direct=False)
def propose_hotels(
    trip_id: int, day_index: int, n: int = DEFAULT_CANDIDATE_COUNT
) -> dict[str, Any]:
    """Propone opciones de alojamiento para un día específico del viaje.
    Úsala cuando el usuario pida explícitamente hoteles o alojamiento
    para un día concreto (e.g. "busca hoteles para el día 2").

    Args:
        trip_id: ID del viaje
        day_index: Número del día (1-based)
        n: Cantidad de hoteles a generar
    """
    date, location = _prepare_day_context(trip_id, day_index)
    candidates = _call_llm_for_candidates("propose_hotels", location, date, n)
    return {"task": "propose_hotels", "day": date, "location": location, "candidates": candidates}


@tool("estimate_budget", return_direct=False)
def estimate_budget(trip_id: int) -> dict[str, Any]:
    """Calcula el presupuesto total del viaje desglosado por categorías.
    Úsala cuando el usuario pida el presupuesto, costes totales o desglose
    de gastos del viaje (e.g. "¿cuánto cuesta el viaje?").

    Args:
        trip_id: ID del viaje
    """
    summary = dal.get_trip_cost_summary(trip_id)
    return {"task": "estimate_budget", **summary}


@tool("summarize_trip", return_direct=False)
def summarize_trip(trip_id: int) -> dict[str, Any]:
    """Genera un resumen narrativo del viaje en prosa.
    Úsala cuando el usuario pida un resumen, narrativa o diario del viaje
    (e.g. "resúmeme el viaje").

    Args:
        trip_id: ID del viaje
    """
    trip = dal.get_trip_compact(trip_id)
    if not trip:
        raise ValueError("trip_not_found")

    days_text = []
    for day in trip.get("days") or []:
        date_str = day.get("date") or "?"
        hotel = (day.get("hotel") or {}).get("name") or "sin hotel"
        activities = ", ".join(
            a.get("name") or "?" for a in (day.get("activities") or [])
        ) or "sin actividades"
        days_text.append(f"- {date_str}: Hotel: {hotel}. Actividades: {activities}")

    prompt = (
        f"Genera un resumen narrativo breve (3-5 párrafos) del viaje "
        f'"{trip.get("name")}".\n'
        f"Descripción: {trip.get('description') or 'N/A'}\n"
        f"Itinerario:\n" + "\n".join(days_text) + "\n\n"
        "Escribe en español, en tono amigable, como un diario de viaje. "
        "No uses JSON, solo texto en prosa."
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
    try:
        trip = dal.get_trip_compact(trip_id)
        current = (trip.get("knowledge_general") or "").strip()

        if not current:
            prompt = (
                "You are a travel information assistant. "
                "Given this chat reply, extract any useful facts about the destination "
                "(geography, culture, climate, currency, language, transport, safety, gastronomy, tips). "
                "Write a concise structured document with labeled paragraphs.\n\n"
                f"CHAT REPLY:\n{new_info}\n\n"
                "If the reply contains no destination information, reply with exactly: NO_UPDATE\n"
                "Otherwise write 6-10 short labeled paragraphs."
            )
        else:
            prompt = (
                "You maintain a destination information document for a trip.\n\n"
                f"CURRENT DOCUMENT:\n{current}\n\n"
                f"NEW CHAT REPLY:\n{new_info}\n\n"
                "If the reply adds useful new destination facts, rewrite the document integrating them. "
                "Keep it concise, structured, and non-redundant.\n"
                "If the reply adds nothing relevant, reply with exactly: NO_UPDATE"
            )

        response = get_model().invoke([{"role": "user", "content": prompt}])
        merged = getattr(response, "content", str(response)).strip()
        if merged and merged != "NO_UPDATE":
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
        location = day_data.get("hotel_location") or ""
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
            "(2 to 5 words, no quotes, no punctuation at the end).\n\n"
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
    if day_id is not None:
        try:
            day_info = dal.get_day_compact(day_id)
            day_index = day_info.get("day_index")
            day_date = day_info.get("date") or "?"
            day_location = day_info.get("hotel_location") or ""
            day_context = (
                f"El usuario está viendo el Día {day_index} ({day_date}"
                + (f", {day_location}" if day_location else "")
                + f"). Cuando uses herramientas que requieran day_index, usa {day_index}. "
            )
        except ValueError:
            pass

    yield {"type": "status", "message": "Consultando el modelo de IA..."}

    trip = dal.get_trip_compact(trip_id)
    knowledge = (trip.get("knowledge_general") or "").strip()

    system_prompt = (
        "Eres un asistente conversacional para planificación de viajes. "
        + day_context
        + "Responde con naturalidad a preguntas y comentarios. "
        "Usa las herramientas disponibles SOLO cuando el usuario pida explícitamente "
        "propuestas de actividades, hoteles, el presupuesto o un resumen del viaje. "
        "Si el usuario pregunta sobre distancias, horarios, curiosidades u otras cosas, "
        "responde en texto directamente sin llamar herramientas.\n\n"
        "CONTEXTO DEL VIAJE:\n"
        f"Trip ID: {trip_id}\n"
        f"Nombre: {trip.get('name')}\n"
        f"Fechas: {trip.get('start_date')} → {trip.get('end_date')}\n"
        f"Descripción: {trip.get('description') or 'N/A'}\n"
    )

    if knowledge:
        system_prompt += f"\nINFORMACIÓN SOBRE EL DESTINO:\n{knowledge}\n"

    system_prompt += f"\nSiempre usa trip_id={trip_id} en las herramientas. Responde en el mismo idioma que el usuario."

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
