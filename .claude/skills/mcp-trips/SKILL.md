---
name: mcp-trips
description: Verify MCP server dependencies and show configuration for OpenCode and Claude Code
---

# MCP Setup & Verification

The MCP server uses **stdio transport** — it is spawned by the client (OpenCode/Claude Code) automatically. You do not start it manually. This skill verifies everything is in place.

## Step 1 — Check dependencies

```bash
source .venv/bin/activate && python -c "import mcp; import httpx; print('Dependencies OK')" 2>/dev/null || echo "Missing deps — run: pip install -r requirements.txt"
```

If missing, install:
```bash
source .venv/bin/activate && pip install -r requirements.txt
```

## Step 2 — Check Flask is running

The MCP server requires Flask at localhost:5000. Check:

```bash
curl -sf http://localhost:5000/api/trips > /dev/null && echo "Flask OK" || echo "Flask not running — start it with: /run"
```

If Flask is not running, tell the user to run `/run` first.

## Step 3 — Smoke test the MCP server

```bash
source .venv/bin/activate && python -m agent.mcp_server --test
```

Expected output:
```
Flask OK — N trips found
MCP tools registered: ['list_trips', 'get_trip', 'create_trip', ...]
Smoke test passed.
```

## Step 4 — Show configuration snippets

Print both config snippets so the user can copy them:

### OpenCode (`opencode.json`)

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

> Use the absolute venv Python path — OpenCode does not activate virtualenvs automatically.

### Claude Code

```bash
claude mcp remove trip-planner  # if previously added with wrong path
claude mcp add trip-planner -- /Users/guillecanizal/trips/.venv/bin/python -m agent.mcp_server
```

Verify it was added with `claude mcp list`.

## Step 5 — Confirm

Tell the user:
- The MCP server is ready
- Flask must be running before any MCP tool is called
- Use `/build-trip` to build a complete itinerary using the MCP tools
