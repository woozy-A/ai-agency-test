# Testing Checklist

## Reset cancellation
- Start a long pipeline request from the local app.
- Press Reset while the status shows Working.
- Confirm the UI returns to Idle and old speech bubbles, movement, logs, and final artifacts do not continue updating.
- Repeat with Rework Mode running.

## Server down fallback
- Open `office-game.html` from GitHub Pages or stop the local server.
- Confirm the app uses simulation mode where applicable and shows a clear error for local-only API actions.

## Simulation mode
- Open the GitHub Pages URL.
- Run Start and confirm demo artifacts are generated without local API calls.
- Use Review Final and confirm it records a demo review instead of calling local models.

## Static file security
- Run `python3 server.py`.
- Confirm `http://127.0.0.1:8000/.env` returns 403.
- Confirm `http://127.0.0.1:8000/outputs/` returns 403.
- Confirm hidden files and files with names containing `token`, `secret`, `api_key`, or `credential` are blocked.

## Gemini fallback
- Configure `FINAL_DIRECTOR_MODEL=gemini-2.5-pro`.
- Confirm important requests route through `gemini-2.5-pro -> gemini-2.5-flash -> gemini-2.5-flash-lite -> gemini-2.0-flash -> ollama/qwen3:14b`.
- Temporarily force a failing Gemini model name and confirm fallback continues instead of stopping the company.

## Ollama model guard
- Run `ollama list` before local model testing.
- Confirm the models shown in the Team drawer exist locally, especially `qwen3:14b`, `freehuntx/qwen3-coder:14b`, `llama3.1:latest`, and `gemma4:latest`.
- If a configured Ollama model is missing, confirm `/api/agent-config` reports `missing_models`.
- Confirm missing local models can fall back to installed candidates such as `qwen3:14b` or `llama3.1:latest`.
- For slow local multi-agent runs, confirm `.env` can override `PIPELINE_TIMEOUT_SECONDS` and that the default is 2400 seconds.

## Prompt language policy
- Run a normal Start request.
- Confirm generated `codex_prompt.md` is English-first and paste-ready for Codex.
- Confirm the final report format inside the generated prompt asks Codex to respond in Korean.
- Confirm browser logs and status messages remain Korean-friendly for Changwoo.

## Artifact rendering
- Run Start.
- Confirm Log, Brief, Plan, UX, Prompt, Review, Final, Files, and HR tabs all render.
- Confirm Files tab shows generated prompt file names or file guidance.
- Confirm artifact count is based on 9 artifacts.
- Confirm Rework Mode writes a new Final and HR report.

## Baseline automated checks
- `python3 -m py_compile server.py`
- `python3 -m unittest tests.test_routing`
- `node --check office-game.js`
