# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Trip Planner is a Flask web application for managing travel itineraries with optional local AI features via Ollama. It is strictly offline-first and privacy-focused — no data leaves the user's machine. See AGENTS.md for the full privacy policy and coding constraints.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application (starts at http://127.0.0.1:5000, debug mode)
python run.py

# Pull the default AI model (requires Ollama installed)
ollama pull qwen2.5:7b
```

```bash
# Lint (ruff) and type check (mypy)
ruff check app/
ruff format --check app/
mypy app/
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///instance/trip_planner.db` | SQLAlchemy connection string |
| `SECRET_KEY` | `dev-secret-key` | Flask session key |
| `OLLAMA_MODEL` | `qwen2.5:7b` | Ollama model name |

## Architecture

MVC pattern with a service layer. Entry point is `run.py` → `app/__init__.py` (app factory).

- **`app/routes.py`** — All Flask routes (~1400 lines): HTML form endpoints, REST API (`/api/...`), AI endpoints (`/agent`, `/generate_stream`), and export endpoints. Contains input-parsing helpers (`parse_date`, `parse_float`, `parse_int`, `parse_bool`) that return 400 on invalid input.
- **`app/models.py`** — SQLAlchemy ORM models: `Trip` → `Day` → `Activity`, plus `GeneralItem`. Uses modern `Mapped[...]` / `mapped_column(...)` syntax.
- **`app/dal.py`** — Data Access Layer. **Services must use dal.py for DB access** to avoid circular imports (services must not import models directly).
- **`app/services/ai.py`** — Itinerary generation using LangChain + Ollama. Supports streaming via SSE. Logs prompts/responses to `logs/trip_{id}/`.
- **`app/services/agent.py`** — Conversational AI agent using LangGraph. Proposes hotels/activities with intent detection (supports Spanish). Falls back to mock data if LLM fails.
- **`app/templates/`** — Jinja2 server-side templates (base.html, index.html, trip_detail.html). Vanilla CSS/JS, no frontend framework.
- **`app/utils/`** — PDF export (ReportLab), CSV export, Google Maps URL generation.

## Key Constraints (from AGENTS.md)

- **Privacy**: No external cloud services. All AI must use local Ollama.
- **Type safety**: Every Python file must have `from __future__ import annotations` and strict type hints on all new functions.
- **DAL pattern**: AI services access the database exclusively through `app/dal.py`.
- **SQLAlchemy**: Use modern `Mapped[...]` / `mapped_column(...)` syntax. Always close sessions properly.
- **Frontend**: Vanilla CSS and JS only. SSE for real-time AI streaming.
