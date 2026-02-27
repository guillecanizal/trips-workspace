---
name: run
description: Start the Flask development server
---

## Pre-flight checks

1. **Port check**: If port 5000 is already in use, find and show the process using `lsof -i :5000` so the user can decide whether to kill it.

2. **Ollama check**: Verify Ollama is running:
```bash
curl -sf http://localhost:11434/api/tags > /dev/null && echo "Ollama OK" || echo "Ollama not running — start it with: ollama serve"
```

3. **Model check**: Ensure the configured model is pulled. The default model is `qwen2.5:7b` (configurable via `OLLAMA_MODEL` env var):
```bash
MODEL="${OLLAMA_MODEL:-qwen2.5:7b}"
ollama list | grep -q "$MODEL" && echo "Model $MODEL ready" || ollama pull "$MODEL"
```

## Start the server

```bash
source .venv/bin/activate && python run.py
```

The app will be available at http://127.0.0.1:5000.

## Configuration

Set `OLLAMA_MODEL` to override the default AI model:
```bash
OLLAMA_MODEL=llama3.1:8b python run.py
```
