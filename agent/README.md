# Trip Planner — MCP Agent Layer

Exposes the trip planner as an AI-accessible backend so external agents (Claude Code, OpenCode, etc.) can read and build trips via tools, without touching the UI.

## Architecture

```
Agent (Claude Code / OpenCode)
  └── MCP tools (stdio)
        └── agent/mcp_server.py
              └── Flask HTTP API (localhost:5000)
                    └── SQLite DB
```

The MCP layer never touches the database directly. All writes go through Flask, preserving validation and data integrity.

## Prerequisites

1. **Flask must be running** — the MCP server calls it for every operation:
   ```bash
   source .venv/bin/activate && python run.py
   ```
   Or use the `/run` skill inside Claude Code.

2. **Dependencies installed:**
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

### OpenCode (`opencode.json` in project root)

```json
{
  "mcp": {
    "trip-planner": {
      "type": "local",
      "command": ["/Users/guillecanizal/trips/.venv/bin/python", "-m", "agent.mcp_server"],
      "enabled": true,
      "timeout": 30000
    }
  }
}
```

> Use the absolute path to the venv Python so OpenCode doesn't rely on the system Python.

### Claude Code

```bash
claude mcp remove trip-planner  # if previously added
claude mcp add trip-planner -- /Users/guillecanizal/trips/.venv/bin/python -m agent.mcp_server
```

Verify with `claude mcp list`.

Or use the `/mcp-trips` skill inside Claude Code for guided setup.

## Available tools

| Tool | Description |
|------|-------------|
| `list_trips` | Summary list of all trips |
| `get_trip(trip_id)` | Full trip with days, activities, KPIs |
| `create_trip(name, destination, start_date, end_date)` | Create trip + auto-generate days |
| `update_trip(trip_id, ...)` | Update trip metadata |
| `plan_day(trip_id, day_number, hotel, activities[])` | ★ Configure a full day in one call |
| `set_hotel(trip_id, day_number, ...)` | Set/replace hotel for a day |
| `add_activity(trip_id, day_number, ...)` | Add a single activity |
| `remove_activity(trip_id, day_number, name)` | Remove an activity by name |
| `export_trip(trip_id, format)` | Get PDF or CSV download URL |

## Building a complete trip

The recommended workflow for agents building full itineraries:

```
1. create_trip(...)           → trip_id, day structure
2. get_trip(trip_id)          → confirm days, compute budget/day
3. plan_day(trip_id, 1, ...)  → day 1: hotel + activities, check running KPIs
4. plan_day(trip_id, 2, ...)  → day 2: ...
   ...repeat for all days...
5. get_trip(trip_id)          → verify total KPIs vs budget
6. export_trip(trip_id)       → PDF URL
```

This day-by-day approach avoids the quality degradation of one-shot generation on long trips.

Inside Claude Code, use `/build-trip` to run this workflow interactively.

## Smoke test

```bash
source .venv/bin/activate && python -m agent.mcp_server --test
```

Expected output:
```
Flask OK — N trips found
MCP tools registered: ['list_trips', 'get_trip', ...]
Smoke test passed.
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TRIP_API_URL` | `http://localhost:5000` | Flask server base URL |

## Philosophy

The UI remains the primary interface. This MCP layer is for:
- Building trips via AI agents with external models (Claude, GPT)
- Scripting and batch creation
- Power users who prefer agentic workflows

The Flask core is the single source of truth — all validation runs there regardless of how data enters.
