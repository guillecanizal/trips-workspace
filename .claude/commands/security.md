---
description: Run a Flask-specific security review on uncommitted changes.
---

# Security Review

Review uncommitted changes (`git diff HEAD`) for security issues specific to this Flask project.

## Checklist

### Secrets (CRITICAL)
- Hardcoded API keys, tokens, or passwords in Python/HTML/JS files
- `SECRET_KEY` set to a real value in source code (should come from env var)
- Secrets in git history or log files under `logs/`
- `.env` files not in `.gitignore`

### SQL Injection (CRITICAL)
- Raw SQL strings with f-strings or `.format()` — must use SQLAlchemy ORM or parameterized queries
- Any direct `db.execute()` with user input not bound as parameters
- Verify all DB access goes through `app/dal.py`

### XSS (HIGH)
- Use of `| safe` filter in Jinja2 templates with user-controlled data
- Use of `Markup()` with unsanitized input
- Inline JavaScript that interpolates server-side variables without escaping
- `innerHTML` assignments in vanilla JS with user data

### Input Validation (HIGH)
- New routes accepting user input without validation
- Missing use of `parse_date`, `parse_float`, `parse_int`, `parse_bool` helpers from routes.py
- File paths constructed from user input (path traversal)

### CSRF (MEDIUM)
- State-changing endpoints (POST/PUT/DELETE) without CSRF protection
- Forms missing CSRF tokens

### Information Leakage (MEDIUM)
- Stack traces or internal paths returned in error responses
- Sensitive data logged to `logs/trip_{id}/` (passwords, tokens)
- Debug mode enabled in production config

## Output Format

For each finding:
- **Severity**: CRITICAL / HIGH / MEDIUM
- **File:line**: exact location
- **Issue**: what's wrong
- **Fix**: how to fix it

If no issues found, confirm the changes look clean.
