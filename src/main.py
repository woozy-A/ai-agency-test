from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"


def build_brief(request: str) -> dict:
    return {
        "goal": "Create marketing deliverables from a client request",
        "audience": "Extracted from request or clarified later",
        "tone": "Practical and trustworthy",
        "deliverables": ["landing page copy", "social media copy"],
        "source_request": request,
    }


def build_plan(brief: dict) -> dict:
    return {
        "steps": [
            "Summarize the client goal",
            "Choose the deliverable structure",
            "Generate a draft",
            "Review the draft",
            "Create the final version",
        ],
        "quality_bar": [
            "Matches the requested deliverable",
            "Uses the requested tone",
            "Has a clear next action",
        ],
        "brief_goal": brief["goal"],
    }


def generate_draft(brief: dict, plan: dict) -> str:
    return "\n".join(
        [
            "# Draft",
            "",
            "## Headline",
            "Build your first practical launch system after work.",
            "",
            "## Body",
            "This draft is generated from the structured brief and execution plan.",
            "",
            "## CTA",
            "Check the curriculum",
            "",
            f"Brief goal: {brief['goal']}",
            f"Plan steps: {len(plan['steps'])}",
        ]
    )


def review_draft(draft: str) -> str:
    return "\n".join(
        [
            "# Review",
            "",
            "- The draft has a clear structure.",
            "- The CTA exists but can be more specific.",
            "- Add more audience-specific detail in the final version.",
            "",
            f"Draft length: {len(draft)} characters",
        ]
    )


def finalize(draft: str, review: str) -> str:
    return "\n".join(
        [
            "# Final",
            "",
            "Build your first practical launch system after work.",
            "",
            "Turn a vague business idea into a small testable offer, a clear landing page, and a first promotion message.",
            "",
            "CTA: Start with the launch checklist",
            "",
            "---",
            "",
            "Review applied:",
            review,
        ]
    )


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, content: dict) -> None:
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")


def run_pipeline(request: str) -> Path:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = OUTPUTS / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    brief = build_brief(request)
    plan = build_plan(brief)
    draft = generate_draft(brief, plan)
    review = review_draft(draft)
    final = finalize(draft, review)

    write_text(output_dir / "request.md", request)
    write_json(output_dir / "brief.json", brief)
    write_json(output_dir / "plan.json", plan)
    write_text(output_dir / "draft.md", draft)
    write_text(output_dir / "review.md", review)
    write_text(output_dir / "final.md", final)

    return output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AI agency sample pipeline.")
    parser.add_argument("request", help="Client request text")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = run_pipeline(args.request)
    print(f"Pipeline complete: {output_dir}")


if __name__ == "__main__":
    main()
