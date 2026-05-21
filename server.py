from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def get_provider() -> str:
    load_env()
    return os.getenv("AI_PROVIDER", "gemini").strip().lower()


def get_model() -> str:
    provider = get_provider()
    if provider == "openai":
        return os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    if provider == "gemini":
        return os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    raise RuntimeError(f"지원하지 않는 AI_PROVIDER입니다: {provider}")


def get_agent_model(agent_key: str) -> str:
    env_key = f"{agent_key.upper()}_MODEL"
    return os.getenv(env_key, get_model())


def get_pipeline_mode() -> str:
    load_env()
    return os.getenv("AI_PIPELINE_MODE", "one_call").strip().lower()


def require_openai_client():
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY가 없습니다. 프로젝트 루트에 .env 파일을 만들고 OPENAI_API_KEY=... 를 넣어주세요."
        )

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai 패키지가 없습니다. `python3 -m pip install openai`를 실행해주세요.") from exc

    return OpenAI()


def ask_openai_agent(client, agent_name: str, role_prompt: str, user_prompt: str, model: str) -> str:
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": role_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
    )
    text = response.output_text.strip()
    if not text:
        raise RuntimeError(f"{agent_name}가 빈 응답을 반환했습니다.")
    return text


def ask_gemini_agent(agent_name: str, role_prompt: str, user_prompt: str, model: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY가 없습니다. Google AI Studio에서 무료 API 키를 만든 뒤 .env에 GEMINI_API_KEY=... 를 넣어주세요."
        )

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "systemInstruction": {
            "parts": [{"text": role_prompt}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
        },
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    for attempt in range(2):
        try:
            with urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 503 and attempt == 0:
                time.sleep(4)
                continue
            if exc.code == 429:
                raise RuntimeError(
                    "Gemini 무료 할당량 또는 분당 제한에 걸렸습니다. 잠시 후 다시 시도하거나, "
                    ".env의 GEMINI_MODEL을 다른 무료 지원 모델로 바꿔보세요. "
                    "자세한 원문 오류: " + error_body
                ) from exc
            if exc.code == 503:
                raise RuntimeError(
                    "Gemini 모델 서버가 현재 혼잡합니다. 잠시 후 다시 시도하거나 "
                    ".env에서 AI_PIPELINE_MODE=one_call 및 GEMINI_MODEL=gemini-2.5-flash-lite 설정을 사용하세요. "
                    "원문 오류: " + error_body
                ) from exc
            raise RuntimeError(f"Gemini API 오류 {exc.code}: {error_body}") from exc

    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"{agent_name}가 응답 후보를 반환하지 않았습니다: {data}")

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "\n".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise RuntimeError(f"{agent_name}가 빈 응답을 반환했습니다.")
    return text


def ask_agent(client, agent_name: str, role_prompt: str, user_prompt: str, model: str | None = None) -> str:
    provider = get_provider()
    model = model or get_model()
    if provider == "openai":
        return ask_openai_agent(client, agent_name, role_prompt, user_prompt, model)
    if provider == "gemini":
        return ask_gemini_agent(agent_name, role_prompt, user_prompt, model)
    raise RuntimeError(f"지원하지 않는 AI_PROVIDER입니다: {provider}")


def extract_json_object(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def normalize_artifacts(data: dict) -> dict[str, str]:
    required = ["brief", "plan", "design", "dev", "review", "final"]
    artifacts = {}
    for key in required:
        value = data.get(key, "")
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, indent=2)
        value = str(value).strip()
        artifacts[key] = value or f"{key} 결과가 비어 있습니다."
    return artifacts


def slugify(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣]+", "-", text).strip("-")
    return slug[:40] or "request"


def save_run(request: str, artifacts: dict[str, str]) -> Path:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = OUTPUTS / f"{run_id}-{slugify(request)}"
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "request.md").write_text(request, encoding="utf-8")
    for key, value in artifacts.items():
        if key == "log":
            continue
        extension = "json" if key == "brief" else "md"
        (output_dir / f"{key}.{extension}").write_text(value, encoding="utf-8")

    return output_dir


def run_one_call_pipeline(client, request: str) -> tuple[dict[str, str], int, str]:
    role_prompt = (
        "너는 작은 AI 에이전시 전체를 한 번에 시뮬레이션하는 오케스트레이터다. "
        "실제로는 API 호출을 한 번만 사용하지만, 결과는 Mike PM, Mina Designer, Jay Developer, "
        "Yuna Reviewer, Finalizer가 각각 일한 것처럼 나눠서 작성한다. "
        "학습용 자동화 파이프라인이므로 과하게 길게 쓰지 말고, 실행 가능한 수준으로 구체화한다. "
        "반드시 순수 JSON 객체만 반환한다. 마크다운 코드블록을 쓰지 않는다."
    )
    user_prompt = f"""
창우 사장의 요청:
{request}

다음 JSON 키를 모두 포함해서 한국어로 작성해줘.

{{
  "brief": "Mike PM이 정리한 목표, 대상, 산출물, 제약조건",
  "plan": "Mike PM의 단계별 실행 계획",
  "design": "Mina Designer의 화면/UX/콘텐츠 구조 제안",
  "dev": "Jay Developer의 구현 방법, 파일 구조, 필요한 코드 방향",
  "review": "Yuna Reviewer의 누락/위험/개선사항 검토",
  "final": "창우에게 납품할 최종 결과와 다음 액션"
}}

요청이 '투두리스트 앱 만들어줘'처럼 쉬운 앱이면 final에는 실제로 만들 파일 구성과 핵심 HTML/CSS/JS 예시까지 포함해줘.
"""

    model = get_model()
    raw = ask_agent(client, "Agency Orchestrator", role_prompt, user_prompt, model)
    artifacts = normalize_artifacts(extract_json_object(raw))
    return artifacts, 1, model


def run_multi_agent_pipeline(client, request: str) -> tuple[dict[str, str], int, str]:
    mike_role = (
        "너는 AI 에이전시의 PM Mike다. 창우 사장의 요청을 실행 가능한 brief와 plan으로 바꾼다. "
        "답변은 한국어로 작성하고, 실무자가 바로 이어받을 수 있게 구체적으로 쓴다."
    )
    mina_role = (
        "너는 AI 에이전시의 디자이너 Mina다. Mike의 brief와 plan을 보고 화면 구조, 사용자 흐름, "
        "콘텐츠 배치를 설계한다. 한국어로 간결하지만 구체적으로 작성한다."
    )
    jay_role = (
        "너는 AI 에이전시의 개발자 Jay다. Mike의 plan과 Mina의 디자인을 바탕으로 구현 방법, 파일 구조, "
        "핵심 코드 방향을 작성한다. 쉬운 앱 요청이면 실제 HTML/CSS/JS 예시도 포함한다."
    )
    yuna_role = (
        "너는 AI 에이전시의 리뷰어 Yuna다. brief, design, dev 결과를 검토하고 누락, 위험, 개선사항을 찾는다. "
        "실행 가능한 피드백만 한국어로 작성한다."
    )
    final_role = (
        "너는 최종 납품 편집자다. 앞 단계 산출물과 리뷰를 반영해 창우가 바로 이해할 수 있는 최종 결과물을 만든다. "
        "다음 액션과 구현 요약을 명확히 쓴다."
    )

    mike_model = get_agent_model("mike")
    mina_model = get_agent_model("mina")
    jay_model = get_agent_model("jay")
    yuna_model = get_agent_model("yuna")
    final_model = get_agent_model("final")

    brief = ask_agent(
        client,
        "Mike",
        mike_role,
        f"창우의 요청:\n{request}\n\n1) brief\n2) 작업 계획\n3) Mina/Jay/Yuna에게 줄 지시를 작성해줘.",
        mike_model,
    )
    design = ask_agent(
        client,
        "Mina",
        mina_role,
        f"원 요청:\n{request}\n\nMike 결과:\n{brief}\n\n디자인/UX/콘텐츠 구조를 제안해줘.",
        mina_model,
    )
    dev = ask_agent(
        client,
        "Jay",
        jay_role,
        f"원 요청:\n{request}\n\nMike 결과:\n{brief}\n\nMina 결과:\n{design}\n\n구현 계획과 핵심 코드 방향을 작성해줘.",
        jay_model,
    )
    review = ask_agent(
        client,
        "Yuna",
        yuna_role,
        f"원 요청:\n{request}\n\nMike:\n{brief}\n\nMina:\n{design}\n\nJay:\n{dev}\n\n검토 결과를 작성해줘.",
        yuna_model,
    )
    final = ask_agent(
        client,
        "Finalizer",
        final_role,
        f"원 요청:\n{request}\n\nMike:\n{brief}\n\nMina:\n{design}\n\nJay:\n{dev}\n\nYuna review:\n{review}\n\n최종 결과물을 작성해줘.",
        final_model,
    )

    artifacts = {
        "brief": brief,
        "plan": brief,
        "design": design,
        "dev": dev,
        "review": review,
        "final": final,
    }
    models = (
        f"Mike={mike_model}, Mina={mina_model}, Jay={jay_model}, "
        f"Yuna={yuna_model}, Finalizer={final_model}"
    )
    return artifacts, 5, models


def run_ai_pipeline(request: str) -> dict:
    provider = get_provider()
    client = require_openai_client() if provider == "openai" else None
    mode = get_pipeline_mode()

    if mode == "multi":
        artifacts, calls, model_summary = run_multi_agent_pipeline(client, request)
    elif mode == "one_call":
        artifacts, calls, model_summary = run_one_call_pipeline(client, request)
    else:
        raise RuntimeError("AI_PIPELINE_MODE는 one_call 또는 multi 여야 합니다.")

    output_dir = save_run(request, artifacts)

    return {
        "ok": True,
        "provider": provider,
        "model": model_summary,
        "mode": mode,
        "calls": calls,
        "output_dir": str(output_dir),
        "artifacts": artifacts,
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/run":
            self.send_json(404, {"ok": False, "error": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            request = str(payload.get("request", "")).strip()
            if not request:
                self.send_json(400, {"ok": False, "error": "요청 내용을 입력해주세요."})
                return

            result = run_ai_pipeline(request)
            self.send_json(200, result)
        except Exception as exc:
            traceback.print_exc()
            self.send_json(500, {"ok": False, "error": str(exc)})


def main() -> None:
    load_env()
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Local AI agency server: http://localhost:{port}/office-game.html")
    print("Stop with Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped")
        server.server_close()
        sys.exit(0)


if __name__ == "__main__":
    main()
