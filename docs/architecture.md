# Architecture

## Overview

The system is a local AI agency pipeline made of clear sequential stages. Each stage receives structured data, performs one job, and passes its result to the next stage.

```text
Client Request
    |
    v
Brief Builder
    |
    v
Planner
    |
    v
Generator
    |
    v
Reviewer
    |
    v
Finalizer
    |
    v
Saved Output
```

## Components

### 1. Brief Builder

Converts the raw client request into a structured brief.

Responsibilities:

- Identify the client goal
- Identify the target audience
- Identify required deliverables
- Identify constraints
- Identify missing information

Output:

- `brief.json`

### 2. Planner

Turns the brief into an execution plan.

Responsibilities:

- Break the request into steps
- Choose the output structure
- Define quality criteria
- Decide what the generator should produce

Output:

- `plan.json`

### 3. Generator

Creates the first draft of the requested deliverable.

Responsibilities:

- Follow the structured brief
- Follow the plan
- Produce the requested format
- Keep the content aligned with the audience and goal

Output:

- `draft.md`

### 4. Reviewer

Checks the draft before final delivery.

Responsibilities:

- Find unclear sections
- Check whether the output matches the brief
- Check formatting
- Suggest improvements

Output:

- `review.md`

### 5. Finalizer

Applies review feedback and saves the final version.

Responsibilities:

- Produce a polished final deliverable
- Save the output in the correct location
- Keep intermediate artifacts for debugging

Output:

- `final.md`

## Suggested Project Structure

```text
ai-agency-test/
├── docs/
│   ├── requirements.md
│   ├── architecture.md
│   └── tasks.md
├── src/
│   ├── pipeline/
│   │   ├── brief_builder.py
│   │   ├── planner.py
│   │   ├── generator.py
│   │   ├── reviewer.py
│   │   └── finalizer.py
│   ├── prompts/
│   │   ├── brief_builder.md
│   │   ├── planner.md
│   │   ├── generator.md
│   │   ├── reviewer.md
│   │   └── finalizer.md
│   └── main.py
├── outputs/
└── README.md
```

## Data Flow

Each run should create a new folder under `outputs/`.

Example:

```text
outputs/
└── 2026-05-21-client-request/
    ├── request.md
    ├── brief.json
    ├── plan.json
    ├── draft.md
    ├── review.md
    └── final.md
```

## V1 Technical Choice

Use Python for the first version because it is simple for scripting, file handling, and AI API integration.

Recommended V1 style:

- One command-line entry point
- One function per pipeline stage
- Prompt files stored separately from code
- Markdown and JSON outputs
- Local file storage
