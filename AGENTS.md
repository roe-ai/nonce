# Privato

- `backend/`: Python (FastAPI, uv). Agent API (`/v1`, `/mcp`), dashboard API (`/admin`), signals, Gmail. Run tests with `cd backend && uv run pytest`.
- `web/`: Next.js dashboard. Read `web/AGENTS.md` before touching it: this Next.js version has breaking changes.

Decisions live in `backend/privato/policy.py` (pure functions); detectors only produce signals (`backend/privato/signals.py`). Keep that split. After changing signal questions or thresholds, score detectors with `cd backend && uv run python bench/run.py none openai --misses`.
