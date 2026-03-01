# Technical Reference

Architecture and engineering notes for Trip Planner. For product overview and usage see [README.md](README.md).

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10+, Flask 3 |
| ORM | SQLAlchemy 2.0 (modern `Mapped[...]` syntax) |
| Database | SQLite (default), any SQLAlchemy-compatible DB |
| AI runtime | Ollama (local LLM server) |
| AI framework | LangChain (`langchain-ollama`, `langchain-core`) |
| Structured output | Pydantic 2 |
| PDF generation | ReportLab |
| Frontend | Jinja2 + HTMX + Alpine.js + Tailwind CSS (all CDN) |
| Linting | Ruff |
| Type checking | mypy (strict) |

No build step. No Node.js. No compiled frontend assets.

---

## Project structure

```
app/
├── __init__.py          # App factory (create_app)
├── database.py          # SQLAlchemy engine + session factory
├── models.py            # ORM models
├── dal.py               # Data Access Layer (used by AI services)
├── routes.py            # All Flask routes (~1,400 lines)
├── services/
│   ├── ai.py            # One-shot itinerary generation
│   └── agent.py         # Conversational agent with tool calling
├── utils/
│   ├── maps.py          # Google Maps URL builders
│   ├── pdf_export.py    # ReportLab PDF export
│   └── csv_export.py    # CSV export
├── templates/
│   ├── base.html
│   ├── pages/
│   │   ├── trip_list.html
│   │   ├── trip_overview.html
│   │   └── day_detail.html
│   └── partials/        # HTMX fragments
│       ├── chat_panel.html
│       ├── kpis.html
│       ├── day_hotel.html
│       ├── day_activities.html
│       ├── general_items.html
│       ├── oneshot_panel.html
│       └── trip_overview_content.html
└── static/
    └── js/app.js        # Alpine.js chatPanel component
```

---

## Data model

```
Trip
├── id, name, description, start_date, end_date
├── knowledge_general        ← destination facts accumulated by the agent
│
├── Day (ordered by date)
│   ├── id, trip_id, date, tagline
│   ├── hotel_name, hotel_location, hotel_description
│   ├── hotel_price, hotel_reservation_id, hotel_link, hotel_maps_link, hotel_cancelable
│   ├── distance_km, distance_hours, distance_minutes
│   │
│   └── Activity (ordered by insertion)
│       ├── id, day_id
│       ├── name, location, description
│       ├── price, reservation_id, link, maps_link, cancelable
│
└── GeneralItem  (flights, insurance, rail passes — not tied to a day)
    ├── id, trip_id
    ├── name, description
    └── price, reservation_id, link, maps_link, cancelable
```

`Trip.knowledge_general` is a free-text field populated automatically by the agent as the user chats. It accumulates destination facts (geography, transport, culture, climate) and is injected into the system prompt on subsequent messages.

---

## Architecture

### MVC + service layer

Routes in `routes.py` act as controllers. Business logic that requires LLM calls lives in `services/`. Database access from services goes exclusively through `dal.py` (prevents circular imports between services and models).

```
Request → routes.py → models.py / dal.py → DB
                    → services/ai.py  → Ollama
                    → services/agent.py → Ollama
                    → utils/          → file output
```

### Session management

`app/__init__.py` creates a `scoped_session` factory attached to the app as `app.session_factory`. Routes and DAL create sessions explicitly and close them in `try/finally` blocks. No global session state.

### HTMX pattern

POST routes that mutate data detect the `HX-Request` header. If present they return an HTML partial for in-place swap; otherwise they redirect (standard form behaviour). This gives HTMX interactivity without duplicating route logic.

---

## AI: two modes

### 1. One-shot itinerary generation (`services/ai.py`)

Sends a single structured prompt to the LLM and expects a JSON response matching the full itinerary schema. Used for generating a complete trip plan from scratch.

- Streaming variant (`stream_itinerary_generation`) yields tokens via SSE so the UI can show a live console
- Non-streaming variant (`generate_itinerary`) logs prompts and responses to `logs/trip_{id}/` for debugging
- After generation the user previews the output and applies it; nothing is written to the DB automatically

**Output schema (abridged):**
```json
{
  "days": [{
    "date": "YYYY-MM-DD",
    "distance_km": 0, "distance_hours": 0, "distance_minutes": 0,
    "hotel": { "name", "location", "price", "reservation_id", "link", ... },
    "activities": [{ "name", "location", "price", "reservation_id", "link", ... }]
  }],
  "general_items": [{ "name", "price", "reservation_id", ... }],
  "knowledge_general": "structured destination overview"
}
```

### 2. Conversational agent (`services/agent.py`)

A tool-calling agent backed by `ChatOllama.bind_tools`. The LLM decides when to call a tool based on the user message and tool docstrings — no regex or keyword pre-filtering.

**Available tools:**

| Tool | When the LLM calls it |
|------|-----------------------|
| `propose_activities(trip_id, day_index, n)` | User asks for activity ideas for a specific day |
| `propose_hotels(trip_id, day_index, n)` | User asks for hotel options for a specific day |
| `estimate_budget(trip_id)` | User asks about costs or budget |
| `summarize_trip(trip_id)` | User asks for a trip narrative or summary |

Conversational messages (questions, logistics queries) receive a plain text reply without any tool call.

**Tool results use Pydantic structured output** (`with_structured_output`) so the LLM returns typed candidate objects rather than free text. The frontend renders candidates as cards with "Apply" buttons.

**Day-scoped conversations:** when the user is on a day detail page, `hybrid_chat_stream` receives `day_id`. The agent resolves the day index internally and injects it into the system prompt so "suggest activities" works without the user saying "day 3".

**Conversation history** is stored in-memory per thread (`agent_thread_{trip_id}` or `agent_thread_{trip_id}_day_{day_id}`). The last 10 messages are included in each request.

**Knowledge enrichment:** after every plain text response, `_enrich_knowledge_general` runs asynchronously (best-effort, silent on failure). It asks the LLM whether the response contained useful destination facts, and if so merges them into `Trip.knowledge_general`.

**Lazy initialisation:** `get_model()` and `get_tool_model()` are called on first use, so the app starts without Ollama running.

---

## Frontend architecture

### Layout

Two-zone layout: content fills the upper ~67% of the viewport; the chat panel is `position: fixed` at the bottom ~33vh. Page templates add `pb-[34vh]` to `<main>` to prevent content from being hidden behind the panel.

```
base.html
  └── {% block content %}    ← page-specific content
  └── {% block chat_panel %} ← fixed bottom panel (overridden per page)
```

### HTMX + Alpine.js split

- **HTMX** handles navigation (clicking a day card loads `day_detail.html`) and partial refreshes after saves (hotel, activities, general items, KPIs)
- **Alpine.js** handles in-component state: edit/read toggle on hotel and activity forms, candidate card display after agent tool calls

### Chat component (`static/js/app.js`)

`chatPanel(tripId, dayId)` is an Alpine component that:
- POSTs to `/agent/stream` and consumes the SSE response
- Parses event types: `status`, `text`, `result`, `error`
- Renders message bubbles and, for `result` events, candidate cards with Apply buttons
- Supports cancel via `AbortController`
- Refreshes the relevant HTMX partial (hotel section or activities list) after applying a candidate

### Streaming (SSE)

Both the one-shot generator and the agent use Server-Sent Events. The SSE endpoints are plain Flask generators with `stream_with_context`. The frontend connects via `EventSource`-style fetch (not the native `EventSource` API, to support POST and `AbortController`).

---

## API surface

### Pages
| Method | Path | Description |
|--------|------|-------------|
| GET | `/trips` | Trip list |
| GET | `/trips/<id>` | Trip overview |
| GET | `/trips/<id>/days/<day_id>` | Day detail |

### HTMX partials
| Method | Path | Returns |
|--------|------|---------|
| GET | `/partials/trips/<id>/overview` | Trip overview fragment |
| GET | `/partials/trips/<id>/kpis` | KPI bar fragment |
| GET | `/partials/days/<day_id>/hotel` | Hotel editor fragment |
| GET | `/partials/days/<day_id>/activities` | Activities list fragment |
| GET | `/partials/trips/<id>/general-items` | General items fragment |

### REST API (JSON)
| Method | Path |
|--------|------|
| GET/POST | `/api/trips` |
| GET/PUT/DELETE | `/api/trips/<id>` |
| GET/POST | `/api/trips/<id>/days` |
| GET/PUT/DELETE | `/api/days/<id>` |
| POST | `/api/days/<id>/activities` |
| GET/PUT/DELETE | `/api/activities/<id>` |
| GET/POST | `/api/trips/<id>/general-items` |
| GET/PUT/DELETE | `/api/general-items/<id>` |

### AI endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/trips/<id>/generate_stream` | SSE itinerary generation |
| POST | `/agent/stream` | SSE agent chat |
| DELETE | `/agent/history/<trip_id>` | Clear chat history |
| GET | `/api/days/<id>/suggest-tagline` | Generate tagline via LLM |
| POST | `/api/days/<id>/tagline` | Save tagline |

### Export
| Method | Path |
|--------|------|
| GET | `/trips/<id>/export.pdf` |
| GET | `/trips/<id>/export.csv` |
| GET | `/trips/<id>/maps-itinerary` |

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///instance/trip_planner.db` | SQLAlchemy connection string |
| `SECRET_KEY` | `dev-secret-key` | Flask session key — change in production |
| `OLLAMA_MODEL` | `qwen2.5:7b` | Ollama model name |

---

## Engineering constraints

These apply to all contributions:

- **`from __future__ import annotations`** at the top of every Python file
- **Type hints on all function signatures** — mypy is run in strict mode
- **Services access the DB through `dal.py` only** — never import `models.py` in `services/`
- **SQLAlchemy sessions** must be closed in `try/finally`; use `Mapped[...]` / `mapped_column()` syntax
- **No external cloud calls** — all AI via local Ollama; no OpenAI, Anthropic, Firebase, etc.
- **No build step** — frontend dependencies loaded from CDN; the app ships as pure Python + templates

---

## Development

```bash
# Install
pip install -r requirements.txt

# Run
python run.py

# Lint
ruff check app/
ruff format --check app/

# Type check
mypy app/
```

AI prompt/response logs are written to `logs/trip_{id}/` for debugging LLM behaviour.
