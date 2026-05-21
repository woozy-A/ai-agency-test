from __future__ import annotations

import json
import os
import re
import sys
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


def ask_openai_agent(client, agent_name: str, role_prompt: str, user_prompt: str) -> str:
    response = client.responses.create(
        model=get_model(),
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


def ask_gemini_agent(agent_name: str, role_prompt: str, user_prompt: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY가 없습니다. Google AI Studio에서 무료 API 키를 만든 뒤 .env에 GEMINI_API_KEY=... 를 넣어주세요."
        )

    model = get_model()
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

    try:
        with urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 429:
            raise RuntimeError(
                "Gemini 무료 할당량 또는 분당 제한에 걸렸습니다. 잠시 후 다시 시도하거나, "
                ".env의 GEMINI_MODEL을 다른 무료 지원 모델로 바꿔보세요. "
                "자세한 원문 오류: " + error_body
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


def ask_agent(client, agent_name: str, role_prompt: str, user_prompt: str) -> str:
    provider = get_provider()
    if provider == "openai":
        return ask_openai_agent(client, agent_name, role_prompt, user_prompt)
    if provider == "gemini":
        return ask_gemini_agent(agent_name, role_prompt, user_prompt)
    raise RuntimeError(f"지원하지 않는 AI_PROVIDER입니다: {provider}")


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


def run_ai_pipeline(request: str) -> dict:
    provider = get_provider()
    client = require_openai_client() if provider == "openai" else None

    mike_role = (
        "너는 AI 에이전시의 PM Mike다. 창우 사장의 요청을 실행 가능한 brief와 작업 계획으로 바꾼다. "
        "답변은 한국어로, 실무자가 바로 이어받을 수 있게 구체적으로 작성한다."
    )
    mina_role = (
        "너는 AI 에이전시의 디자이너 Mina다. PM의 brief와 plan을 보고 사용자가 볼 화면, 콘텐츠 구조, "
        "메시지 흐름을 설계한다. 한국어로 간결하지만 구체적으로 작성한다."
    )
    jay_role = (
        "너는 AI 에이전시의 개발자 Jay다. PM의 plan과 디자이너의 제안을 보고 실제 구현/자동화 관점에서 "
        "필요한 구조, 데이터 흐름, 다음 코드 작업을 정리한다. 한국어로 작성한다."
    )
    yuna_role = (
        "너는 AI 에이전시의 리뷰어 Yuna다. brief, design, dev 결과를 검토하고 누락, 위험, 개선안을 찾는다. "
        "날카롭지만 실행 가능하게 한국어로 작성한다."
    )
    final_role = (
        "너는 최종 납품 편집자다. 앞 단계 산출물과 리뷰를 반영해 창우가 바로 이해할 수 있는 최종 결과물을 만든다. "
        "한국어로 작성하고 다음 액션을 명확히 적는다."
    )

    brief = ask_agent(
        client,
        "Mike",
        mike_role,
        f"창우의 요청:\n{request}\n\n1) brief\n2) 작업 계획\n3) 각 팀원에게 줄 지시를 작성해줘.",
    )
    design = ask_agent(
        client,
        "Mina",
        mina_role,
        f"원 요청:\n{request}\n\nMike의 brief/plan:\n{brief}\n\n디자인/콘텐츠 구조를 제안해줘.",
    )
    dev = ask_agent(
        client,
        "Jay",
        jay_role,
        f"원 요청:\n{request}\n\nMike의 brief/plan:\n{brief}\n\nMina의 디자인 제안:\n{design}\n\n구현 계획을 작성해줘.",
    )
    review = ask_agent(
        client,
        "Yuna",
        yuna_role,
        f"원 요청:\n{request}\n\nMike:\n{brief}\n\nMina:\n{design}\n\nJay:\n{dev}\n\n검토 결과를 작성해줘.",
    )
    final = ask_agent(
        client,
        "Finalizer",
        final_role,
        f"원 요청:\n{request}\n\nMike:\n{brief}\n\nMina:\n{design}\n\nJay:\n{dev}\n\nYuna review:\n{review}\n\n최종 결과물을 작성해줘.",
    )

    artifacts = {
      "brief": brief,
      "plan": brief,
      "design": design,
      "dev": dev,
      "review": review,
      "final": final,
    }
    output_dir = save_run(request, artifacts)

    return {
        "ok": True,
        "provider": provider,
        "model": get_model(),
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
