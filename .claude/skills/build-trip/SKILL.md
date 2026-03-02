---
name: build-trip
description: Build a complete trip itinerary day by day using the MCP tools
---

# Build Trip

Build a complete travel itinerary using the trip-planner MCP tools. This skill solves the one-shot AI generation problem by planning each day individually with global budget awareness.

## Pre-flight

First verify the MCP tools are available. Try calling `list_trips`. If it fails with "tool not found" or a connection error:
1. Tell the user to run `/mcp-trips` to set up the MCP server
2. Tell the user to start Flask with `/run`
3. Stop here

## Collect trip parameters

Ask the user for (or read from their message):
- **Destination** — city/country, e.g. "Kyoto, Japan"
- **Start date** — YYYY-MM-DD
- **End date** — YYYY-MM-DD
- **Total budget** — in euros, e.g. 2500
- **Interests** — e.g. "temples, gastronomy, nature, nightlife"
- **Travel style** — budget / mid-range / luxury (default: mid-range)

If any required field is missing, ask before proceeding.

## Budget allocation

Compute per-day budget before starting:

```
budget_per_day = total_budget / num_days
hotel_per_day  = budget_per_day * 0.55   (55% for accommodation)
activities_per_day = budget_per_day * 0.35  (35% for activities)
buffer = budget_per_day * 0.10             (10% margin)
```

Keep this allocation visible while planning each day.

## Workflow

### 1. Create the trip

Call `create_trip` with the collected parameters. Note the `trip_id` and the list of days returned — each has a `day_number` and `date`.

### 2. Review the structure

Call `get_trip(trip_id)` to confirm the day count and dates. Plan the geographic flow mentally:
- Group nearby locations on consecutive days
- Place travel-heavy days (arrivals/departures) at the start and end
- Avoid backtracking

### 3. Plan each day with `plan_day`

For **each day** call `plan_day(trip_id, day_number, hotel_name, hotel_price, ..., activities=[...])`.

Rules per day:
- **Hotel**: Include hotel if it's a new location or first night. Omit if same hotel as previous day (use check-out day without hotel). Keep hotel cost near `hotel_per_day`.
- **Activities**: 3–5 activities per day, chronological order. Mix paid and free. Keep total activity cost near `activities_per_day`.
- **Day 1**: Arrival day — lighter schedule, include airport/station transfer as first "activity" if relevant.
- **Last day**: Departure day — only morning activities before check-out.
- **Coherence**: Reference the previous day's location to ensure geographic flow makes sense.

After each `plan_day` call, check `trip_kpis.total_eur` returned in the response. If the running total is tracking above budget, reduce hotel cost or activity count on the next days.

### 4. Verify final KPIs

After all days are planned, call `get_trip(trip_id)` and show the user:
- Total cost vs budget
- Hotel total / Activities total breakdown
- Day count and activity count

If total is over budget (>5% above), identify the most expensive days and offer to adjust them using `set_hotel` or `remove_activity`.

### 5. Export

Call `export_trip(trip_id, "pdf")` and show the user the URL to download their itinerary.

## Quality guidelines

- **Don't repeat hotels** across consecutive days unless the user explicitly wants a base hotel
- **Free activities** (parks, viewpoints, walking tours) are valuable — not everything needs a price
- **Meals are not activities** unless it's a specific restaurant booking — skip generic "lunch" entries
- **Be specific** — "Fushimi Inari Shrine hike" is better than "Sightseeing"
- **Respect local context** — opening hours, seasons, typical prices

## Output format

After completing, show a summary:

```
Trip built: [name]
Days planned: N
Total cost: €X / €budget
---
Day 1 — [date]: [hotel name] + N activities
Day 2 — [date]: [hotel name] + N activities
...
---
PDF: [url]
```
