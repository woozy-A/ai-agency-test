# Changwoo Prompt Agency

This is a small learning project for turning rough tasks into high-quality Codex prompts.

## Visual Demo

Open `index.html` in a browser.

The demo shows this flow:

```text
Client Request -> Brief Builder -> Planner -> Generator -> Reviewer -> Finalizer
```

Each step creates an artifact:

- `request.md`
- `brief.json`
- `plan.json`
- `draft.md`
- `review.md`
- `final.md`

## Pixel Prompt Office

Open `office-game.html` in a browser.

This version shows the prompt agency as a retro office simulation:

```text
Changwoo task -> Mike PM -> Mina UX + Jay prompt engineer -> Yuna reviewer -> Codex prompt package
```

On GitHub Pages it runs as a simulation. On localhost it calls the local backend and creates a prompt package.

## Local AI Backend

For the real local AI version, create `.env`:

```bash
cp .env.example .env
```

Then edit `.env` and set your API key. The default provider is Gemini because it has a free tier for learning:

```text
AI_PROVIDER=gemini
AI_PIPELINE_MODE=one_call
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash-lite
```

Gemini mode uses Python's standard library, so no package install is required.

Optional OpenAI mode:

```text
AI_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4.1-mini
```

Start the local backend:

```bash
python3 server.py
```

Open:

```text
http://localhost:8000/office-game.html
```

When opened through `localhost`, the pixel office calls the backend and creates a Codex-ready prompt package. When opened on GitHub Pages, it stays in simulation mode so the public demo still works.

The local backend uses one AI request per run. The single response is split into:

- Mike PM brief
- Mike plan
- Mina UX requirements
- Jay implementation prompt notes
- Yuna review/checklist
- Final Codex prompt package

Each run is saved under `outputs/` and includes:

- `generated_prompt/codex_prompt.md`
- `generated_prompt/acceptance_checklist.md`
- `generated_prompt/test_plan.md`
- `generated_prompt/risk_notes.md`

This keeps the learning version cheaper than calling one model per agent.

To run each worker with its own model, use multi-agent mode:

```text
AI_PROVIDER=gemini
AI_PIPELINE_MODE=multi
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash-lite

MIKE_MODEL=gemini-2.5-flash
MINA_MODEL=gemini-2.5-flash-lite
JAY_MODEL=gemini-2.5-flash
YUNA_MODEL=gemini-2.5-flash
FINAL_MODEL=gemini-2.5-flash-lite
```

Multi-agent mode is easier to understand, but it uses five API calls per run. One-call mode is recommended for the free tier.

## How To Extend

Useful next steps:

1. Add more project type routing rules.
2. Add prompt quality scoring.
3. Add a copy button for `codex_prompt.md`.
4. Add a mode that sends the generated prompt directly into another Codex session.
