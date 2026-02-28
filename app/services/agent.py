"""Hybrid chat agent with LangChain tools for trip assistance."""

from __future__ import annotations

import os
import re
from typing import Any, Callable, Dict, Generator, Literal, Optional, TypedDict

from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from pydantic import BaseModel

from app import dal

MODEL_NAME = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

# ---------------------------------------------------------------------------
# Lazy model initialization — avoids crash if Ollama is not running at import
# ---------------------------------------------------------------------------
_model: ChatOllama | None = None
_tool_model: Any = None


def get_model() -> ChatOllama:
    """Return the shared ChatOllama instance, creating it on first use."""
    global _model
    if _model is None:
        _model = ChatOllama(
            model=MODEL_NAME,
            temperature=0.1,
            num_ctx=2048,
        )
    return _model


def get_tool_model() -> Any:
    """Return the tool-bound model, creating it on first use."""
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


# ---------------------------------------------------------------------------
# Constants and patterns
# ---------------------------------------------------------------------------

DEFAULT_CANDIDATE_COUNT = 5
REQUESTED_COUNT_PATTERN = re.compile(
    r"requested_(?:items|activities|hotels)\s*=\s*(\d+)", re.IGNORECASE
)

ACTIVITY_KEYWORDS = [
    "actividad", "actividades", "hacer", "visitar", "plan", "planes",
    "ver", "excursión", "excursiones", "turismo",
]
HOTEL_KEYWORDS = [
    "hotel", "hoteles", "alojamiento", "hospedaje", "dormir",
    "hostal", "hospedarse", "quedarse",
]
BUDGET_KEYWORDS = [
    "presupuesto", "coste", "costes", "gasto", "gastos", "precio",
    "precios", "cuánto", "cuanto", "budget", "total",
]
SUMMARY_KEYWORDS = [
    "resumen", "resumir", "resúmeme", "resumeme", "narrativa",
    "describe", "descripción", "describir", "diario",
]
DAY_PATTERN = re.compile(r"d[íi]a\s+(\d+)", re.IGNORECASE)

IntentType = Literal["activities", "hotels", "budget", "summary"]


class AgentState(TypedDict):
    trip_id: int
    message: str
    intent: Optional[IntentType]
    day_index: Optional[int]
    requested_count: Optional[int]
    result: Dict[str, Any] | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_text(value: Optional[str]) -> str:
    return (value or "").strip()


def _extract_requested_count(message: str) -> Optional[int]:
    match = REQUESTED_COUNT_PATTERN.search(message)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _format_message_with_count(message: str, count: Optional[int]) -> str:
    base = message.strip()
    if count is None:
        return base
    return f"{base}\n\n[requested_items={count}]"


def _resolve_day_info(
    trip: Dict[str, Any], day_index: int
) -> tuple[str, Dict[str, Any]]:
    days = trip.get("days") or []
    if day_index < 1 or day_index > len(days):
        raise ValueError("day_index_out_of_range")
    day = days[day_index - 1] or {}
    date = _clean_text(day.get("date"))
    if not date:
        raise ValueError("day_missing_date")
    return date, day


def _resolve_location(day: Dict[str, Any]) -> str:
    hotel_location = _clean_text((day.get("hotel") or {}).get("location"))
    if hotel_location:
        return hotel_location
    activities = day.get("activities") or []
    if activities:
        activity_location = _clean_text((activities[0] or {}).get("location"))
        if activity_location:
            return activity_location
    raise ValueError("location_unavailable_for_day")


def _prepare_day_context(trip_id: int, day_index: int) -> tuple[str, str]:
    trip = dal.get_trip_compact(trip_id)
    if not trip:
        raise ValueError("trip_not_found")
    date, day = _resolve_day_info(trip, day_index)
    location = _resolve_location(day)
    return date, location


# ---------------------------------------------------------------------------
# Structured LLM candidate generation
# ---------------------------------------------------------------------------


def _call_llm_for_candidates(
    task: str, location: str, date: str, count: int
) -> list[Dict[str, Any]]:
    """Generate candidates using Pydantic structured output."""
    is_hotel = task == "propose_hotels"
    response_model = HotelCandidatesResponse if is_hotel else ActivityCandidatesResponse
    item_type = "hoteles" if is_hotel else "actividades turísticas"

    system_message = (
        f"Genera exactamente {count} {item_type} para {location}. "
        f"Devuelve un JSON con un array 'candidates' de {count} elementos."
    )
    user_message = (
        f"Genera {count} {item_type} para {location} el día {date}"
    )

    structured = get_model().with_structured_output(response_model)
    result = structured.invoke([
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ])
    candidates = [c.model_dump() for c in result.candidates]
    if not candidates:
        raise ValueError(
            f"El modelo no generó ningún candidato para {location} el {date}. "
            "Verifica que Ollama esté funcionando correctamente."
        )
    return candidates


# ---------------------------------------------------------------------------
# LangChain tools
# ---------------------------------------------------------------------------


@tool("propose_activities", return_direct=False)
def propose_activities(
    trip_id: int, day_index: int, n: int = DEFAULT_CANDIDATE_COUNT
) -> Dict[str, Any]:
    """
    Propone actividades turísticas para un día específico del viaje.

    USA ESTA HERRAMIENTA cuando el usuario pida:
    - "actividades para el día X"
    - "cosas que hacer el día X"
    - "qué visitar el día X"
    - "propón planes para el día X"
    - "excursiones para el día X"
    - "turismo día X"

    Args:
        trip_id: ID del viaje (siempre proporcionado en el contexto)
        day_index: Número del día (1-based). Ejemplo: "día 2" -> day_index=2
        n: Cantidad de actividades a generar (default 5)

    Returns:
        Diccionario con actividades propuestas
    """
    date, location = _prepare_day_context(trip_id, day_index)
    candidates = _call_llm_for_candidates("propose_activities", location, date, n)
    return {
        "task": "propose_activities",
        "day": date,
        "location": location,
        "candidates": candidates,
    }


@tool("propose_hotels", return_direct=False)
def propose_hotels(
    trip_id: int, day_index: int, n: int = DEFAULT_CANDIDATE_COUNT
) -> Dict[str, Any]:
    """
    Propone opciones de alojamiento para un día específico del viaje.

    USA ESTA HERRAMIENTA cuando el usuario pida:
    - "hoteles para el día X"
    - "dónde alojarme el día X"
    - "busca alojamiento para el día X"
    - "opciones de hospedaje el día X"
    - "dónde dormir el día X"
    - "dónde quedarse el día X"

    Args:
        trip_id: ID del viaje (siempre proporcionado en el contexto)
        day_index: Número del día (1-based). Ejemplo: "día 10" -> day_index=10
        n: Cantidad de hoteles a generar (default 5)

    Returns:
        Diccionario con hoteles propuestos
    """
    date, location = _prepare_day_context(trip_id, day_index)
    candidates = _call_llm_for_candidates("propose_hotels", location, date, n)
    return {
        "task": "propose_hotels",
        "day": date,
        "location": location,
        "candidates": candidates,
    }


@tool("estimate_budget", return_direct=False)
def estimate_budget(trip_id: int) -> Dict[str, Any]:
    """
    Calcula el presupuesto total del viaje desglosado por día.

    USA ESTA HERRAMIENTA cuando el usuario pida:
    - "presupuesto del viaje"
    - "cuánto cuesta el viaje"
    - "desglose de gastos"
    - "total del viaje"
    - "cuánto llevo gastado"

    Args:
        trip_id: ID del viaje

    Returns:
        Diccionario con desglose de costes por día y totales
    """
    summary = dal.get_trip_cost_summary(trip_id)
    return {"task": "estimate_budget", **summary}


@tool("summarize_trip", return_direct=False)
def summarize_trip(trip_id: int) -> Dict[str, Any]:
    """
    Genera un resumen narrativo del viaje en prosa.

    USA ESTA HERRAMIENTA cuando el usuario pida:
    - "resumen del viaje"
    - "resúmeme el viaje"
    - "describe el viaje"
    - "diario del viaje"
    - "narrativa del viaje"

    Args:
        trip_id: ID del viaje

    Returns:
        Diccionario con el resumen narrativo
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

    response = get_model().invoke([
        {"role": "user", "content": prompt},
    ])
    text = getattr(response, "content", str(response))

    return {
        "task": "summarize_trip",
        "trip_name": trip.get("name"),
        "summary": text,
    }


TOOLS = [propose_activities, propose_hotels, estimate_budget, summarize_trip]
TOOL_REGISTRY: Dict[str, Callable[..., Any]] = {t.name: t for t in TOOLS}

# ---------------------------------------------------------------------------
# In-memory conversation history (ephemeral, same contract as MemorySaver)
# ---------------------------------------------------------------------------

_chat_histories: Dict[str, list] = {}


def _get_history(thread_id: str) -> list:
    return _chat_histories.setdefault(thread_id, [])


def _append_history(thread_id: str, role: str, content: str) -> None:
    _chat_histories.setdefault(thread_id, []).append(
        {"role": role, "content": content}
    )


def clear_thread(thread_id: str) -> None:
    """Clear conversation history for a thread."""
    _chat_histories.pop(thread_id, None)


# ---------------------------------------------------------------------------
# Knowledge enrichment
# ---------------------------------------------------------------------------


def _enrich_knowledge_general(trip_id: int, new_info: str) -> None:
    """Merge new_info into Trip.knowledge_general using the LLM."""
    try:
        trip = dal.get_trip_compact(trip_id)
        current = (trip.get("knowledge_general") or "").strip()

        if not current:
            prompt = (
                "You are a travel information assistant. "
                "You receive a chat reply about a trip. "
                "If it contains useful facts about the destination (geography, population, culture, climate, currency, language, transport, safety, gastronomy, tips, etc.), "
                "write a concise destination information document with labeled paragraphs.\n\n"
                f"CHAT REPLY:\n{new_info}\n\n"
                "If the reply contains no relevant destination information (e.g. it is conversational, an error, or unrelated), "
                "reply with exactly: NO_UPDATE\n\n"
                "Otherwise write 6-10 short labeled paragraphs. Be concise and structured."
            )
        else:
            prompt = (
                "You maintain a concise destination information document for a trip.\n\n"
                f"CURRENT DOCUMENT:\n{current}\n\n"
                f"NEW CHAT REPLY:\n{new_info}\n\n"
                "If the reply contains useful new facts about the destination (geography, population, culture, climate, currency, language, transport, safety, gastronomy, tips, etc.), "
                "rewrite the document integrating them. Keep it concise, structured, and non-redundant.\n"
                "If the reply contains no relevant destination information, "
                "reply with exactly: NO_UPDATE"
            )

        response = get_model().invoke([{"role": "user", "content": prompt}])
        merged = getattr(response, "content", str(response)).strip()
        if merged and merged != "NO_UPDATE":
            dal.update_knowledge_general(trip_id, merged)
    except Exception:
        pass  # enrichment is best-effort; never block the chat response


# ---------------------------------------------------------------------------
# Hybrid chat stream
# ---------------------------------------------------------------------------


def hybrid_chat_stream(
    trip_id: int, message: str, *, thread_id: str | None = None
) -> Generator[Dict[str, Any], None, None]:
    """Stream a hybrid chat response: parse_intent gate first, then LLM decides.

    Flow:
    1. parse_intent: if clear actionable intent + complete params → direct_call
    2. Otherwise: LLM with bound tools decides (text reply or tool call)
    3. If message is a general destination question: enrich knowledge_general
    """
    tid = thread_id or f"trip_{trip_id}"

    # --- Gate 1: deterministic intent detection (keeps tool reliability) ---
    fake_state: AgentState = {
        "trip_id": trip_id,
        "message": message,
        "intent": None,
        "day_index": None,
        "requested_count": None,
        "result": None,
    }
    parsed = parse_intent_node(fake_state)
    route = should_use_direct_call(parsed)

    if route == "direct_call":
        yield {"type": "status", "message": "Procesando solicitud..."}
        try:
            result_state = direct_call_node(parsed)
            result = result_state.get("result")
            if result:
                _append_history(tid, "user", message)
                _append_history(tid, "assistant", f"[tool:{parsed['intent']}]")
                yield {"type": "result", "data": result}
            else:
                yield {"type": "error", "message": "No result from tool"}
        except Exception as exc:
            yield {"type": "error", "message": str(exc)}
        return

    # --- Gate 2: LLM with optional tool use ---
    yield {"type": "status", "message": "Consultando el modelo de IA..."}

    trip = dal.get_trip_compact(trip_id)
    knowledge = (trip.get("knowledge_general") or "").strip()

    system_prompt = (
        "Eres un asistente de viajes conversacional. "
        "Tienes acceso a herramientas para proponer actividades, hoteles, presupuesto y resumen.\n\n"
        "HERRAMIENTAS DISPONIBLES:\n"
        "- propose_activities: cuando el usuario pide actividades/planes/qué hacer un día específico\n"
        "- propose_hotels: cuando el usuario pide hoteles/alojamiento un día específico\n"
        "- estimate_budget: cuando el usuario pide presupuesto/costes del viaje\n"
        "- summarize_trip: cuando el usuario pide un resumen/narrativa del viaje\n\n"
        "CONTEXTO DEL VIAJE:\n"
        + f"Trip ID: {trip_id}\n"
        + f"Nombre: {trip.get('name')}\n"
        + f"Fechas: {trip.get('start_date')} → {trip.get('end_date')}\n"
        + f"Descripción: {trip.get('description') or 'N/A'}\n"
    )

    if knowledge:
        system_prompt += f"\nINFORMACIÓN SOBRE EL DESTINO:\n{knowledge}\n"

    system_prompt += (
        "\nINSTRUCCIONES:\n"
        f"- Siempre usa trip_id={trip_id} en las herramientas\n"
        "- Si el usuario hace una pregunta conversacional, responde directamente en texto\n"
        "- Solo llama a una herramienta si el usuario lo pide explícitamente\n"
        "- Responde en el mismo idioma que el usuario\n"
    )

    history = _get_history(tid)
    messages = (
        [{"role": "system", "content": system_prompt}]
        + history[-10:]  # keep last 10 exchanges to bound context size
        + [{"role": "user", "content": message}]
    )

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


# ---------------------------------------------------------------------------
# LangGraph nodes
# ---------------------------------------------------------------------------


def parse_intent_node(state: AgentState) -> AgentState:
    """Detecta la intención y extrae parámetros del mensaje del usuario."""
    message_lower = state["message"].lower()

    has_activity = any(kw in message_lower for kw in ACTIVITY_KEYWORDS)
    has_hotel = any(kw in message_lower for kw in HOTEL_KEYWORDS)
    has_budget = any(kw in message_lower for kw in BUDGET_KEYWORDS)
    has_summary = any(kw in message_lower for kw in SUMMARY_KEYWORDS)

    intent = None
    if has_budget:
        intent = "budget"
    elif has_summary:
        intent = "summary"
    elif has_activity and not has_hotel:
        intent = "activities"
    elif has_hotel and not has_activity:
        intent = "hotels"

    day_match = DAY_PATTERN.search(state["message"])
    day_index = int(day_match.group(1)) if day_match else None

    requested_count = _extract_requested_count(state["message"])
    if not requested_count:
        count_match = re.search(
            r"(\d+)\s+(?:actividades|hoteles|opciones)", message_lower
        )
        requested_count = int(count_match.group(1)) if count_match else None

    return {
        **state,
        "intent": intent,
        "day_index": day_index,
        "requested_count": requested_count,
    }


def should_use_direct_call(
    state: AgentState,
) -> Literal["direct_call", "llm_agent"]:
    """Decide si podemos llamar directamente a la tool o necesitamos el LLM."""
    intent = state["intent"]
    if intent in ("budget", "summary"):
        return "direct_call"
    if intent and state["day_index"]:
        return "direct_call"
    return "llm_agent"


_INTENT_TO_TOOL: Dict[str, str] = {
    "activities": "propose_activities",
    "hotels": "propose_hotels",
    "budget": "estimate_budget",
    "summary": "summarize_trip",
}


def direct_call_node(state: AgentState) -> AgentState:
    """Llama directamente a la tool cuando la intención es clara."""
    tool_name = _INTENT_TO_TOOL.get(state["intent"] or "")
    tool_impl = TOOL_REGISTRY.get(tool_name or "")

    if not tool_impl:
        raise ValueError(f"tool_not_found: {state['intent']}")

    tool_args: Dict[str, Any] = {"trip_id": state["trip_id"]}
    if state["intent"] in ("activities", "hotels"):
        tool_args["day_index"] = state["day_index"]
        tool_args["n"] = state["requested_count"] or DEFAULT_CANDIDATE_COUNT

    result = tool_impl.invoke(tool_args)
    return {**state, "result": result}


def llm_agent_node(state: AgentState) -> AgentState:
    """Usa el LLM cuando la intención no es clara o falta información."""
    system_prompt = (
        "Eres un asistente especializado en planificación de viajes.\n\n"
        "HERRAMIENTAS DISPONIBLES:\n"
        "1. propose_activities: ACTIVIDADES, PLANES, QUÉ HACER, EXCURSIONES\n"
        "2. propose_hotels: HOTELES, ALOJAMIENTO, DÓNDE DORMIR\n"
        "3. estimate_budget: PRESUPUESTO, COSTES, GASTOS, CUÁNTO CUESTA\n"
        "4. summarize_trip: RESUMEN, DESCRIBE EL VIAJE, DIARIO\n\n"
        f"CONTEXTO ACTUAL:\n"
        f'- Trip ID: {state["trip_id"]}\n'
        f'- Mensaje del usuario: "{state["message"]}"\n\n'
        "INSTRUCCIONES:\n"
        "1. Para propose_activities/propose_hotels extrae el día del mensaje\n"
        "2. Para estimate_budget/summarize_trip solo necesitas trip_id\n"
        f'3. Siempre incluye trip_id={state["trip_id"]}\n'
        "4. Elige UNA SOLA herramienta\n\n"
        "EJEMPLOS:\n"
        f'- "actividades día 2" -> '
        f'propose_activities(trip_id={state["trip_id"]}, day_index=2, n=5)\n'
        f'- "hoteles día 10" -> '
        f'propose_hotels(trip_id={state["trip_id"]}, day_index=10, n=5)\n'
        f'- "presupuesto del viaje" -> '
        f'estimate_budget(trip_id={state["trip_id"]})\n'
        f'- "resumen del viaje" -> '
        f'summarize_trip(trip_id={state["trip_id"]})\n'
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": state["message"]},
    ]

    response = get_tool_model().invoke(messages)
    additional_kwargs = getattr(response, "additional_kwargs", {}) or {}
    tool_calls = getattr(response, "tool_calls", None) or additional_kwargs.get(
        "tool_calls"
    )

    if not tool_calls:
        raise ValueError("agent_missing_tool_call")

    call = tool_calls[0]
    tool_name = call.get("name")
    tool_impl = TOOL_REGISTRY.get(tool_name or "")

    if not tool_impl:
        raise ValueError(f"agent_unknown_tool: {tool_name}")

    tool_args = dict(call.get("args") or {})
    tool_args.setdefault("trip_id", state["trip_id"])

    if "day_index" not in tool_args:
        raise ValueError("agent_missing_day_index")

    if state.get("requested_count") is not None:
        tool_args.setdefault("n", state["requested_count"])
    else:
        tool_args.setdefault("n", DEFAULT_CANDIDATE_COUNT)

    result = tool_impl.invoke(tool_args)
    return {**state, "result": result}


