# Agent Technical Context & Guidelines

This document provides critical architectural details and constraints for AI agents (like Claude or Cursor) working on the Trip Planner codebase.

## 🔴 CRITICAL: Privacy & Offline-First Policy
- **NO DATA EXFILTRATION**: This application is strictly local-first. Never suggest or implement features that send user data, trip details, or prompts to external cloud services (e.g., OpenAI, Anthropic, Firebase, etc.).
- **LOCAL AI ONLY**: All AI features must use the local Ollama instance (`langchain-ollama`).
- **OFFLINE OPERATION**: The core functionality must work without an internet connection. External calls are only allowed for user-facing features like Google Maps links.

## Technical Architecture

### Backend Stack
- **Framework**: Python 3.10+ with Flask.
- **Database**: SQLite (`instance/trips.db`) with SQLAlchemy ORM.
- **AI Orchestration**: 
    - **LangChain**: Used for itinerary generation and streaming.
    - **LangGraph**: Used for the conversational AI agent.
- **Local LLM**: Ollama (default: `gemma2:9b`).

### Frontend Stack
- **Templating**: Server-side rendering with Jinja2 (`app/templates/`).
- **Assets**: Vanilla CSS and Vanilla JavaScript. No heavy frontend frameworks.
- **Interactivity**: Uses Server-Sent Events (SSE) for real-time AI generation/thought streaming.

### Data Access Layer (DAL)
- **Avoid Circular Imports**: Services (AI/Agent) should **not** import models directly.
- **Preferred Pattern**: Use functions in `app/dal.py` for database operations. It provides a clean interface for reading/writing trip data without causing circular dependency issues.

## Code Conventions

- **Type Safety**: 
    - Always include `from __future__ import annotations` at the top of every Python file.
    - Strict type hints are mandatory for all new functions, parameters, and return types.
- **SQLAlchemy**: 
    - Use modern SQLAlchemy `Mapped[...]` and `mapped_column(...)` syntax in `app/models.py`.
    - Always ensure database sessions are correctly closed (use `try...finally` or context managers).
- **Control Flow**:
    - Use the helper parsers in `app/routes.py` (`parse_date`, `parse_float`, `parse_int`, `parse_bool`) to handle user input and raise proper 400 errors.

## Directory Structure

```text
app/
├── dal.py             # MANDATORY Data Access Layer for AI services
├── database.py        # Database setup and session factory
├── models.py          # SQLAlchemy models (modern syntax)
├── routes.py          # Flask controllers and API endpoints
├── services/          # Business logic
│   ├── ai.py          # Itinerary generation (LangChain)
│   └── agent.py       # Conversational logic (LangGraph)
├── templates/         # Jinja2 HTML templates
└── utils/             # Helper modules (Map links, PDF/CSV export)
```

## AI Integration Details
- **Streaming**: Itinerary generation streams both "Reasoning" and "JSON" back to the UI via SSE.
- **Logging**: All AI prompts and responses are logged in `logs/trip_{id}/` with timestamps. Refer to these logs when debugging LLM failures.
