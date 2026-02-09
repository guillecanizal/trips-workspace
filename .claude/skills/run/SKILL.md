---
name: run
description: Start the Flask development server
---

Run the Flask development server using the project's virtual environment. Always activate the venv first:

```bash
source .venv/bin/activate && python run.py
```

The app will be available at http://127.0.0.1:5000.

If port 5000 is already in use, find and show the process using it with `lsof -i :5000` so the user can decide whether to kill it.
