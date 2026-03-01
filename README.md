# Trip Planner

A personal AI travel planning workspace. Plan complete trips day by day — hotels, activities, costs, and logistics — with an AI copilot that suggests, never decides.

Runs entirely on your machine. No account, no subscription, no data leaving your device.

---

## What it does

Trip Planner gives you a structured workspace to build and manage travel itineraries. For each trip you define the dates and a rough idea; the app organises everything else into a day-by-day view.

**For each day you can record:**
- Where you're staying (hotel name, location, price, reservation ID, cancellation policy)
- What you're doing (activities with location, duration, price, booking links)
- How far you're driving (distance and travel time to the next stop)

**Across the whole trip:**
- General items not tied to a specific day — flights, insurance, rail passes
- A live budget breakdown: hotels, activities, general items, grand total
- A calendar grid that shows the whole trip at a glance
- PDF and CSV export for offline use or sharing

---

## The AI copilot

The AI is optional and assistive. It never books anything, never overwrites your data without you applying the change.

**Two ways to use it:**

1. **Generate a full itinerary** — describe your trip and the AI proposes a complete day-by-day plan with hotels, activities, and driving estimates. You preview it and apply it with one click.

2. **Chat with the AI** — ask questions or request specific suggestions. The chat panel is always visible at the bottom of every page.

   - *"Suggest activities for day 3"* — returns a list of options you can apply one by one
   - *"Find hotels in Seville for Friday"* — hotel candidates with details
   - *"How much is this trip costing?"* — live budget breakdown from your actual data
   - *"Summarise the trip for me"* — a narrative description of the itinerary
   - *"What's the weather like in Kyoto in April?"* — conversational answers without tool calls

The AI learns destination context as you chat and reuses it in future responses.

---

## Open by design

Trip Planner does not try to own your data or lock you into its ecosystem.

- Every hotel and activity has fields for your own **reservation IDs and booking links** — paste links from Booking.com, Airbnb, GetYourGuide, or anywhere else
- **Import JSON from any AI** — generate an itinerary in ChatGPT or Claude, paste the JSON into the import panel, preview it, and apply it
- **Export to PDF or CSV** at any time — the data is yours
- **Google Maps links** are generated automatically for hotels and activities, and a full directions URL is built for the whole route

---

## Philosophy

- **Private by default.** No cloud. No analytics. No third-party services. The AI runs locally via [Ollama](https://ollama.com).
- **No social features.** No sharing, comments, or followers.
- **No marketplace.** The app will never show ads, promoted hotels, or affiliate links.
- **Works without AI.** The AI features are additive. The app is fully functional as a plain itinerary organiser if Ollama is not installed.
- **Minimal and fast.** The goal is to go from trip idea to a complete, costed plan in minutes.

---

## Getting started

**Requirements:**
- Python 3.10+
- [Ollama](https://ollama.com) (optional, for AI features)

```bash
pip install -r requirements.txt
python run.py
```

Open http://127.0.0.1:5000 in your browser.

**To enable AI features**, install Ollama and pull a model:
```bash
ollama pull qwen2.5:7b
```

The app starts fine without Ollama — AI features activate automatically once a model is available.

---

## Recommended models

| Model | RAM needed | Notes |
|-------|-----------|-------|
| `qwen2.5:14b` | 16 GB+ | Best itinerary quality |
| `gemma2:9b` | 10 GB+ | Good balance |
| `qwen2.5:7b` | 6 GB+ | Default, works well |
| `llama3.1:8b` | 8 GB+ | Fast responses |

Override the default with `OLLAMA_MODEL=gemma2:9b python run.py`.

---

## License

Apache 2.0

---

*For architecture, engineering decisions, and API reference see [TECHNICAL.md](TECHNICAL.md).*
