# AI Agency Pipeline Sample

This is a small learning project for understanding how an automated AI agency pipeline can be structured.

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

## Pixel Office Demo

Open `office-game.html` in a browser.

This version shows the same pipeline as a retro office simulation:

```text
Changwoo -> Mike PM -> Mina Designer + Jay Developer -> Yuna Reviewer -> Delivery
```

It is still a front-end simulation, but it makes the agent handoff easier to understand.

## Local AI Backend

For the real local AI version, create `.env`:

```bash
cp .env.example .env
```

Then edit `.env` and set your API key:

```text
OPENAI_API_KEY=your_api_key_here
```

Install the OpenAI Python package:

```bash
python3 -m pip install openai
```

Start the local backend:

```bash
python3 server.py
```

Open:

```text
http://localhost:8000/office-game.html
```

When opened through `localhost`, the pixel office calls the backend and runs the AI agent pipeline. When opened on GitHub Pages, it stays in simulation mode so the public demo still works.

## Code Demo

Run the local Python sample:

```bash
python3 src/main.py "신규 온라인 강의 런칭을 위한 랜딩페이지 카피와 SNS 홍보 문구를 만들어줘."
```

The command creates a new folder under `outputs/`.

## How To Extend

Start by replacing one fake function at a time:

1. Replace `build_brief()` with an AI API call.
2. Replace `build_plan()` with a planning prompt.
3. Replace `generate_draft()` with a generator prompt.
4. Replace `review_draft()` with a review prompt.
5. Replace `finalize()` with a final editing prompt.

Keep the artifact files even after adding real AI calls. They make the pipeline easier to debug.
