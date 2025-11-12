"""LangGraph agent with LangChain tools for proposing activities or hotels."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, Literal, Optional, TypedDict

from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph

from app import dal

MODEL_NAME = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
MODEL = ChatOllama(
    model=MODEL_NAME,
    temperature=0.1,
    num_ctx=2048,
    format="json",
)

DEFAULT_CANDIDATE_COUNT = 5
REQUESTED_COUNT_PATTERN = re.compile(r"requested_(?:items|activities|hotels)\s*=\s*(\d+)", re.IGNORECASE)

# MEJORA: Patrones para detección de intención
ACTIVITY_KEYWORDS = ["actividad", "actividades", "hacer", "visitar", "plan", "planes", "ver", "excursión", "excursiones", "turismo"]
HOTEL_KEYWORDS = ["hotel", "hoteles", "alojamiento", "hospedaje", "dormir", "hostal", "hospedarse", "quedarse"]
DAY_PATTERN = re.compile(r"d[íi]a\s+(\d+)", re.IGNORECASE)


class AgentState(TypedDict):
    trip_id: int
    message: str
    intent: Optional[Literal["activities", "hotels"]]
    day_index: Optional[int]
    requested_count: Optional[int]
    result: Dict[str, Any] | None


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


def _resolve_day_info(trip: Dict[str, Any], day_index: int) -> tuple[str, Dict[str, Any]]:
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


def _as_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        fragments: list[str] = []
        for piece in content:
            if isinstance(piece, dict):
                fragments.append(piece.get("text") or "")
            else:
                fragments.append(str(piece))
        return "".join(fragments)
    return str(content or "")


def _clean_json_response(text: str) -> str:
    """Limpia la respuesta para extraer JSON válido."""
    # Eliminar markdown code blocks
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    
    # Buscar JSON entre llaves
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        return json_match.group(0)
    
    return text.strip()


def _build_schema(task: str, location: str) -> Dict[str, Any]:
    if task == "propose_hotels":
        return {
            "candidates": [
                {
                    "name": "",
                    "location": location,
                    "summary": "",
                    "details": "",
                    "price_per_night": None,
                    "reservation_id": None,
                    "link": "",
                    "rating": None,
                }
            ]
        }
    return {
        "candidates": [
            {
                "name": "",
                "location": location,
                "summary": "",
                "details": "",
                "estimated_time_hours": 0,
                "price": None,
                "reservation_id": None,
                "link": "",
            }
        ]
    }


def _call_llm_for_candidates(task: str, location: str, date: str, count: int) -> list[Dict[str, Any]]:
    """MEJORADO: Generación más robusta de candidatos."""
    
    # Sistema de prompt simplificado y claro
    if task == "propose_hotels":
        system_message = f"""Genera {count} hoteles para {location} en formato JSON.
Devuelve SOLO un objeto JSON con esta estructura exacta:
{{"candidates": [{{"name": "Hotel ejemplo", "location": "{location}", "summary": "Descripción breve", "details": "Detalles completos", "price_per_night": 100, "reservation_id": null, "link": "", "rating": 4.5}}]}}

IMPORTANTE: Solo JSON, sin texto adicional."""
    else:
        system_message = f"""Genera {count} actividades turísticas para {location} en formato JSON.
Devuelve SOLO un objeto JSON con esta estructura exacta:
{{"candidates": [{{"name": "Actividad ejemplo", "location": "{location}", "summary": "Descripción breve", "details": "Detalles completos", "estimated_time_hours": 2, "price": 20, "reservation_id": null, "link": ""}}]}}

IMPORTANTE: Solo JSON, sin texto adicional."""
    
    user_message = f"Genera {count} {'hoteles' if task == 'propose_hotels' else 'actividades'} para {location} el día {date}"
    
    try:
        response = MODEL.invoke(
            [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ]
        )
        
        content = _as_text(getattr(response, "content", response))
        
        # Limpiar y extraer JSON
        cleaned_content = _clean_json_response(content)
        
        # Intentar parsear
        parsed = json.loads(cleaned_content)
        
        candidates = parsed.get("candidates")
        if not isinstance(candidates, list):
            raise ValueError("Response missing 'candidates' array")
        
        # Si está vacío, generar datos mock
        if not candidates:
            candidates = _generate_mock_candidates(task, location, count)
        
        return candidates
        
    except (json.JSONDecodeError, ValueError) as exc:
        # Fallback: generar datos mock si el LLM falla
        print(f"LLM JSON error: {exc}. Using mock data.")
        return _generate_mock_candidates(task, location, count)


def _generate_mock_candidates(task: str, location: str, count: int) -> list[Dict[str, Any]]:
    """Genera candidatos mock cuando el LLM falla."""
    if task == "propose_hotels":
        return [
            {
                "name": f"Hotel {location} {i+1}",
                "location": location,
                "summary": f"Hotel céntrico en {location}",
                "details": "Hotel con todas las comodidades necesarias",
                "price_per_night": 80 + (i * 20),
                "reservation_id": None,
                "link": "",
                "rating": 4.0 + (i * 0.2),
            }
            for i in range(count)
        ]
    else:
        return [
            {
                "name": f"Actividad {location} {i+1}",
                "location": location,
                "summary": f"Visita turística en {location}",
                "details": "Experiencia única en la ciudad",
                "estimated_time_hours": 2 + i,
                "price": 20 + (i * 10),
                "reservation_id": None,
                "link": "",
            }
            for i in range(count)
        ]


# MEJORA: Descripciones detalladas con ejemplos
@tool("propose_activities", return_direct=False)
def propose_activities(trip_id: int, day_index: int, n: int = DEFAULT_CANDIDATE_COUNT) -> Dict[str, Any]:
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
    return {"task": "propose_activities", "day": date, "location": location, "candidates": candidates}


@tool("propose_hotels", return_direct=False)
def propose_hotels(trip_id: int, day_index: int, n: int = DEFAULT_CANDIDATE_COUNT) -> Dict[str, Any]:
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
    return {"task": "propose_hotels", "day": date, "location": location, "candidates": candidates}


TOOLS = [propose_activities, propose_hotels]
TOOL_REGISTRY: Dict[str, Callable[..., Any]] = {tool.name: tool for tool in TOOLS}
TOOL_MODEL = MODEL.bind_tools(TOOLS)


# MEJORA: Nodo para detectar intención con regex
def parse_intent_node(state: AgentState) -> AgentState:
    """Detecta la intención y extrae parámetros del mensaje del usuario."""
    message_lower = state["message"].lower()
    
    # Detectar intención por palabras clave
    has_activity = any(kw in message_lower for kw in ACTIVITY_KEYWORDS)
    has_hotel = any(kw in message_lower for kw in HOTEL_KEYWORDS)
    
    intent = None
    if has_activity and not has_hotel:
        intent = "activities"
    elif has_hotel and not has_activity:
        intent = "hotels"
    
    # Extraer número de día
    day_match = DAY_PATTERN.search(state["message"])
    day_index = int(day_match.group(1)) if day_match else None
    
    # Extraer cantidad solicitada
    requested_count = _extract_requested_count(state["message"])
    if not requested_count:
        count_match = re.search(r"(\d+)\s+(?:actividades|hoteles|opciones)", message_lower)
        requested_count = int(count_match.group(1)) if count_match else None
    
    return {
        **state,
        "intent": intent,
        "day_index": day_index,
        "requested_count": requested_count,
    }


# MEJORA: Router condicional
def should_use_direct_call(state: AgentState) -> Literal["direct_call", "llm_agent"]:
    """Decide si podemos llamar directamente a la tool o necesitamos el LLM."""
    if state["intent"] and state["day_index"]:
        return "direct_call"
    return "llm_agent"


# MEJORA: Nodo para llamada directa (sin LLM)
def direct_call_node(state: AgentState) -> AgentState:
    """Llama directamente a la tool cuando la intención es clara."""
    tool_name = f"propose_{state['intent']}"
    tool_impl = TOOL_REGISTRY.get(tool_name)
    
    if not tool_impl:
        raise ValueError(f"tool_not_found: {tool_name}")
    
    tool_args = {
        "trip_id": state["trip_id"],
        "day_index": state["day_index"],
        "n": state["requested_count"] or DEFAULT_CANDIDATE_COUNT,
    }
    
    result = tool_impl.invoke(tool_args)
    return {**state, "result": result}


# MEJORA: Nodo LLM mejorado con mejor prompt
def llm_agent_node(state: AgentState) -> AgentState:
    """Usa el LLM cuando la intención no es clara o falta información."""
    system_prompt = f"""Eres un asistente especializado en planificación de viajes.

HERRAMIENTAS DISPONIBLES:
1. propose_activities: Úsala cuando pidan ACTIVIDADES, PLANES, QUÉ HACER, QUÉ VISITAR, EXCURSIONES
2. propose_hotels: Úsala cuando pidan HOTELES, ALOJAMIENTO, DÓNDE DORMIR, HOSPEDAJE

CONTEXTO ACTUAL:
- Trip ID: {state['trip_id']}
- Mensaje del usuario: "{state['message']}"

INSTRUCCIONES CRÍTICAS:
1. DEBES extraer el número del día del mensaje del usuario
2. Si dice "día 2", usa day_index=2
3. Si dice "día 10", usa day_index=10
4. Siempre incluye trip_id={state['trip_id']} en la llamada
5. Elige UNA SOLA herramienta basándote en la intención principal

EJEMPLOS:
- "propon actividades para el día 2" -> propose_activities(trip_id={state['trip_id']}, day_index=2, n=5)
- "hoteles para el día 10" -> propose_hotels(trip_id={state['trip_id']}, day_index=10, n=5)
- "qué hacer el día 5" -> propose_activities(trip_id={state['trip_id']}, day_index=5, n=5)
- "dónde dormir el día 3" -> propose_hotels(trip_id={state['trip_id']}, day_index=3, n=5)
"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": state["message"]},
    ]
    
    response = TOOL_MODEL.invoke(messages)
    additional_kwargs = getattr(response, "additional_kwargs", {}) or {}
    tool_calls = getattr(response, "tool_calls", None) or additional_kwargs.get("tool_calls")
    
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
    
    # Usar requested_count del estado si está disponible
    if state.get("requested_count") is not None:
        tool_args.setdefault("n", state["requested_count"])
    else:
        tool_args.setdefault("n", DEFAULT_CANDIDATE_COUNT)
    
    result = tool_impl.invoke(tool_args)
    return {**state, "result": result}


def _build_graph():
    """Construye el grafo con routing condicional."""
    graph = StateGraph(AgentState)
    
    # Añadir nodos
    graph.add_node("parse_intent", parse_intent_node)
    graph.add_node("direct_call", direct_call_node)
    graph.add_node("llm_agent", llm_agent_node)
    
    # Entry point
    graph.set_entry_point("parse_intent")
    
    # Routing condicional desde parse_intent
    graph.add_conditional_edges(
        "parse_intent",
        should_use_direct_call,
        {
            "direct_call": "direct_call",
            "llm_agent": "llm_agent",
        },
    )
    
    # Ambos caminos terminan
    graph.add_edge("direct_call", END)
    graph.add_edge("llm_agent", END)
    
    return graph.compile()


WORKFLOW = _build_graph()


def run_simple_agent(trip_id: int, message: str) -> Dict[str, Any]:
    """Ejecuta el agente con el grafo mejorado."""
    initial_state: AgentState = {
        "trip_id": trip_id,
        "message": message,
        "intent": None,
        "day_index": None,
        "requested_count": None,
        "result": None,
    }
    final_state: AgentState = WORKFLOW.invoke(initial_state)
    result = final_state.get("result")
    if not result:
        raise ValueError("agent_failed")
    return result
