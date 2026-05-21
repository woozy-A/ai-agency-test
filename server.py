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


class RetryableAIError(RuntimeError):
    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


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


def get_model_candidates(primary_model: str) -> list[str]:
    provider = get_provider()
    models = [primary_model]
    if provider == "gemini":
        fallback_raw = os.getenv("GEMINI_FALLBACK_MODELS", "gemini-2.0-flash-lite,gemini-2.0-flash")
    elif provider == "openai":
        fallback_raw = os.getenv("OPENAI_FALLBACK_MODELS", "")
    else:
        fallback_raw = ""

    for item in fallback_raw.split(","):
        candidate = item.strip()
        if candidate and candidate not in models:
            models.append(candidate)
    return models


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
                raise RetryableAIError(
                    "Gemini 모델 서버가 현재 혼잡합니다. 잠시 후 다시 시도하거나 "
                    ".env에서 AI_PIPELINE_MODE=one_call 및 GEMINI_MODEL=gemini-2.5-flash-lite 설정을 사용하세요. "
                    "원문 오류: " + error_body,
                    retry_after=300,
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
        last_error = None
        for candidate in get_model_candidates(model):
            try:
                return ask_openai_agent(client, agent_name, role_prompt, user_prompt, candidate)
            except Exception as exc:
                last_error = exc
        raise last_error or RuntimeError(f"{agent_name} OpenAI 호출에 실패했습니다.")
    if provider == "gemini":
        last_error = None
        for candidate in get_model_candidates(model):
            try:
                return ask_gemini_agent(agent_name, role_prompt, user_prompt, candidate)
            except (RetryableAIError, RuntimeError) as exc:
                last_error = exc
                if not is_model_fallback_error(exc):
                    raise
        raise last_error or RuntimeError(f"{agent_name} Gemini 호출에 실패했습니다.")
    raise RuntimeError(f"지원하지 않는 AI_PROVIDER입니다: {provider}")


def is_model_fallback_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "429",
            "503",
            "quota",
            "rate",
            "할당량",
            "분당 제한",
            "혼잡",
            "unavailable",
        )
    )


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


def normalize_artifacts(data: dict) -> tuple[dict[str, str], list[dict[str, str]]]:
    required = ["brief", "plan", "design", "dev", "review", "final"]
    artifacts = {}
    for key in required:
        value = data.get(key, "")
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, indent=2)
        value = str(value).strip()
        artifacts[key] = value or f"{key} 결과가 비어 있습니다."
    files = data.get("files", [])
    if not isinstance(files, list):
        files = []
    clean_files = []
    for item in files:
        if not isinstance(item, dict):
            continue
        path = re.sub(r"/+", "/", str(item.get("path", "")).strip().replace("\\", "/"))
        path = path.lstrip("/")
        path = "/".join(part for part in path.split("/") if part not in ("", ".", ".."))
        content = str(item.get("content", ""))
        if path and content:
            clean_files.append({"path": path, "content": content})
    return artifacts, clean_files


def detect_project_type(request: str) -> str:
    text = request.lower()
    if any(keyword in text for keyword in ["swift", "swiftui", "xcode", "macos", "맥용", "맥 앱"]):
        return "macos_swiftui"
    if any(keyword in text for keyword in ["python", "파이썬", "cli", "터미널"]):
        return "python_cli"
    if any(keyword in text for keyword in ["node", "npm", "javascript cli", "자바스크립트 cli"]):
        return "node_cli"
    if any(keyword in text for keyword in ["문서", "기획서", "보고서", "readme", "매뉴얼"]):
        return "documentation"
    return "web_static"


def project_file_contract(project_type: str) -> str:
    contracts = {
        "web_static": """
project_type은 web_static이다.
Codex가 만들 결과물은 보통 아래 구조를 목표로 한다:
- index.html
- style.css
- app.js
단, 너는 앱 코드를 직접 납품하지 말고 Codex가 위 파일을 만들도록 정확한 프롬프트를 작성한다.
""",
        "macos_swiftui": """
project_type은 macos_swiftui이다.
Codex가 만들 결과물은 보통 아래 Swift Package 또는 Xcode 친화 구조를 목표로 한다:
- Package.swift
- Sources/GeneratedMacApp/main.swift
SwiftUI macOS 앱으로 작성하도록 지시한다. 지뢰찾기 같은 게임 요청이면 게임 상태 모델과 UI를 분리하도록 요구한다.
HTML/CSS/JS가 아니라 SwiftUI/macOS 산출물을 만들도록 프롬프트에 명확히 적는다.
""",
        "python_cli": """
project_type은 python_cli이다.
Codex가 만들 결과물은 보통 아래 구조를 목표로 한다:
- main.py
- README.md
표준 라이브러리 위주로 바로 실행 가능하게 지시한다.
""",
        "node_cli": """
project_type은 node_cli이다.
Codex가 만들 결과물은 보통 아래 구조를 목표로 한다:
- package.json
- index.js
- README.md
Node.js로 바로 실행 가능하게 지시한다.
""",
        "documentation": """
project_type은 documentation이다.
Codex가 만들 결과물은 보통 아래 문서 구조를 목표로 한다:
- README.md
- plan.md
실행 앱이 아니라 문서 산출물을 만들도록 지시한다.
""",
    }
    return contracts.get(project_type, contracts["web_static"])


AGENT_ROLES = {
    "mike": {
        "name": "Mike",
        "role": "PM",
        "prompt": "너는 Changwoo Prompt Agency의 PM Mike다. 범위, 우선순위, 산출물, 실행 순서를 현실적으로 정리한다.",
    },
    "mina": {
        "name": "Mina",
        "role": "UX Planner",
        "prompt": "너는 UX Planner Mina다. 사용 흐름, 화면 구조, 빈 상태, 오류 상태, 검수 가능한 UX 기준을 설명한다.",
    },
    "jay": {
        "name": "Jay",
        "role": "Tech Writer",
        "prompt": "너는 Tech Writer Jay다. Codex가 바로 실행할 수 있는 구현 지시, 파일 구조, 명령어, 테스트 기준을 쓴다.",
    },
    "yuna": {
        "name": "Yuna",
        "role": "QA Reviewer",
        "prompt": "너는 QA Reviewer Yuna다. acceptance criteria, 자동 테스트, 직접 검수 시나리오, 회귀 위험을 분리한다.",
    },
    "nora": {
        "name": "Nora",
        "role": "Scope Manager",
        "prompt": "너는 Scope Manager Nora다. 이번 작업에서 할 것과 하지 않을 것, 범위 초과 위험을 냉정하게 정리한다.",
    },
    "dana": {
        "name": "Dana",
        "role": "Developer Experience",
        "prompt": "너는 Developer Experience 담당 Dana다. 실행 방법, 개발자 경험, 오류 메시지, 로컬 환경 전제를 쉽게 만든다.",
    },
    "testkim": {
        "name": "Test Kim",
        "role": "QA Engineer",
        "prompt": "너는 QA Engineer Test Kim이다. 자동화 가능한 테스트와 사람이 봐야 할 검수 항목을 구체적으로 나눈다.",
    },
    "jason": {
        "name": "Jason",
        "role": "Red Team",
        "prompt": "너는 Red Team Reviewer Jason이다. 칭찬하지 말고 실패 가능성, 허점, 모호한 요구사항만 지적한다.",
    },
    "sana": {
        "name": "Sana",
        "role": "Security",
        "prompt": "너는 Security & Privacy 담당 Sana다. API 키, .env, 개인정보, 위험 명령, 공개 저장소 노출 위험을 점검한다.",
    },
    "iris": {
        "name": "Iris",
        "role": "Prompt Editor",
        "prompt": "너는 Prompt Editor Iris다. 프롬프트 문장을 명확하고 덜 모호하게 다듬고, Codex가 오해할 표현을 줄인다.",
    },
    "vera": {
        "name": "Vera",
        "role": "Validation Judge",
        "prompt": "너는 Validation Judge Vera다. 품질 점수, blocking issue, warning, 통과 기준을 수치와 근거로 말한다.",
    },
    "changwoo": {
        "name": "창우",
        "role": "Boss",
        "prompt": "너는 창우 사장이다. 학습자 관점에서 무엇을 봐야 하는지, 다음 의사결정이 무엇인지 짧고 현실적으로 말한다.",
    },
}


def run_agent_chat(agent_key: str, question: str) -> dict:
    agent = AGENT_ROLES.get(agent_key)
    if not agent:
        raise RuntimeError("알 수 없는 직원입니다.")

    provider = get_provider()
    client = require_openai_client() if provider == "openai" else None
    model = get_agent_model(agent_key)
    role_prompt = (
        f"{agent['prompt']} 너의 이름은 {agent['name']}이고 역할은 {agent['role']}다. "
        "창우에게 한국어로 답한다. 답변은 6문장 이내로 짧고 구체적으로 한다. "
        "필요하면 체크리스트를 3개 이하로만 제시한다."
    )
    answer = ask_agent(client, agent["name"], role_prompt, question, model)
    return {
        "ok": True,
        "agent": agent_key,
        "name": agent["name"],
        "role": agent["role"],
        "provider": provider,
        "model": model,
        "answer": answer,
    }


def slugify(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣]+", "-", text).strip("-")
    return slug[:40] or "request"


def save_run(request: str, artifacts: dict[str, str], files: list[dict[str, str]] | None = None) -> Path:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = OUTPUTS / f"{run_id}-{slugify(request)}"
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "request.md").write_text(request, encoding="utf-8")
    for key, value in artifacts.items():
        if key == "log":
            continue
        extension = "json" if key == "brief" else "md"
        (output_dir / f"{key}.{extension}").write_text(value, encoding="utf-8")

    for item in files or []:
        file_path = output_dir / item["path"]
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(item["content"], encoding="utf-8")

    return output_dir


def extract_quality_score(files: list[dict[str, str]], artifacts: dict[str, str]) -> dict | None:
    sources = []
    for item in files:
        if item["path"].endswith("quality_score.md"):
            sources.append(item["content"])
    sources.extend([artifacts.get("review", ""), artifacts.get("final", "")])

    for source in sources:
        if not source:
            continue
        match = re.search(r"(\d{1,3})\s*/\s*100", source)
        if not match:
            match = re.search(r"(?:총점|점수|score|total)[^\d]{0,12}(\d{1,3})", source, re.IGNORECASE)
        if match:
            score = max(0, min(100, int(match.group(1))))
            return {"score": score, "text": source[:1200]}
    return None


def run_one_call_pipeline(client, request: str) -> tuple[dict[str, str], list[dict[str, str]], int, str]:
    project_type = detect_project_type(request)
    role_prompt = (
        "너는 Codex 프롬프트 제작 전문 AI 에이전시의 오케스트레이터다. "
        "실제로는 API 호출을 한 번만 사용하지만, 결과는 Mike PM, Mina Designer, Jay Developer, "
        "Yuna Reviewer, Finalizer가 각각 일한 것처럼 나눠서 작성한다. "
        "추가로 Nora Scope Manager, Dana Developer Experience, Test Kim QA Engineer, "
        "Jason Red Team Reviewer, Sana Security & Privacy, Iris Prompt Editor, "
        "Vera Validation Judge의 관점을 반드시 반영한다. "
        "창우는 네가 직접 앱을 만드는 것이 아니라, Codex에 그대로 붙여넣으면 좋은 결과가 나오는 "
        "고품질 작업 프롬프트와 검증 체크리스트를 원한다. "
        "요청 타입에 맞게 Codex가 만들 파일, 성공 기준, 테스트, 검수 절차를 명확히 설계한다. "
        "반드시 순수 JSON 객체만 반환한다. 마크다운 코드블록을 쓰지 않는다."
    )
    file_contract = project_file_contract(project_type)
    user_prompt = f"""
창우 사장의 요청:
{request}

판단된 project_type:
{project_type}

Codex 작업 설계 규칙:
{file_contract}

다음 JSON 키를 모두 포함해서 한국어로 작성해줘.

{{
  "project_type": "{project_type}",
  "brief": "Mike PM이 정리한 목표, 범위, 제외 범위, 산출물",
  "plan": "Codex에게 시킬 작업 순서. 구현 전 성공 기준부터 검증까지 포함",
  "design": "Mina Designer가 정리한 UX/화면/사용 흐름 요구사항",
  "dev": "Jay Developer가 정리한 기술 요구사항, 파일 구조, 구현 지시",
  "review": "Yuna Reviewer가 정리한 acceptance checklist, test plan, risks",
  "final": "창우에게 설명하는 최종 요약과 Codex 사용 방법",
  "files": [
    {{"path": "generated_prompt/codex_prompt.md", "content": "Codex에 그대로 붙여넣을 최종 프롬프트"}},
    {{"path": "generated_prompt/acceptance_checklist.md", "content": "성공 기준 체크리스트"}},
    {{"path": "generated_prompt/test_plan.md", "content": "자동/수동 테스트 계획"}},
    {{"path": "generated_prompt/risk_notes.md", "content": "위험 요소와 완화책"}},
    {{"path": "generated_prompt/scope.md", "content": "Nora가 정리한 이번 작업 범위와 제외 범위"}},
    {{"path": "generated_prompt/output_contract.md", "content": "Codex가 마지막에 보고해야 하는 형식"}},
    {{"path": "generated_prompt/security_notes.md", "content": "Sana가 정리한 보안/비밀값/위험 명령 주의사항"}},
    {{"path": "generated_prompt/quality_score.md", "content": "Vera가 평가한 프롬프트 품질 점수와 감점 사유"}}
  ]
}}

규칙:
- 코드를 직접 완성해서 납품하지 말고, Codex가 구현하도록 지시하는 프롬프트를 납품한다.
- codex_prompt.md는 반드시 아래 섹션을 포함한다: 목표, 성공 기준, 구현 지시, 파일 구조, 자동 테스트, 직접 검수 시나리오, 보고 형식.
- 성공 기준은 체크박스 목록으로 작성한다.
- 테스트 계획은 가능한 자동 테스트와 수동 검수를 구분한다.
- 위험 요소는 빌드 실패, 범위 초과, 플랫폼 차이, 모델 한계 등을 현실적으로 적는다.
- scope.md에는 이번 작업에서 할 것과 하지 않을 것을 분리한다.
- output_contract.md에는 Codex의 최종 보고 형식을 "자동 검증 완료 항목 / 검수 필요 항목 / 위험한 항목 / 변경 파일 / 실행 방법"으로 고정한다.
- security_notes.md에는 API 키, .env, 토큰, 개인정보, destructive command 관련 주의사항을 포함한다.
- quality_score.md에는 100점 만점 점수, Clarity/Scope/Testability/Safety/Codex Usability 세부 점수, Blocking Issues, Warnings를 포함한다.
- Jason은 칭찬하지 말고 실패 가능성만 지적한다. Vera는 80점 미만이면 수정 필요라고 표시한다.
- "3주 계획", "회의 일정", "언젠가 구현" 같은 장기 계획을 쓰지 말고, Codex가 바로 실행할 수 있는 단위로 쓴다.
"""

    model = get_model()
    raw = ask_agent(client, "Agency Orchestrator", role_prompt, user_prompt, model)
    artifacts, files = normalize_artifacts(extract_json_object(raw))
    if files:
        file_list = "\n".join(f"- `{item['path']}`" for item in files)
        artifacts["final"] = (
            artifacts["final"].rstrip()
            + "\n\n## 생성된 프롬프트 패키지\n\n"
            + file_list
            + "\n\n`generated_prompt/codex_prompt.md` 내용을 Codex에 붙여넣으면 됩니다."
        )
    return artifacts, files, 1, model


def run_multi_agent_pipeline(client, request: str) -> tuple[dict[str, str], list[dict[str, str]], int, str]:
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
    return artifacts, [], 5, models


def run_ai_pipeline(request: str) -> dict:
    provider = get_provider()
    client = require_openai_client() if provider == "openai" else None
    mode = get_pipeline_mode()

    if mode == "multi":
        artifacts, files, calls, model_summary = run_multi_agent_pipeline(client, request)
    elif mode == "one_call":
        artifacts, files, calls, model_summary = run_one_call_pipeline(client, request)
    else:
        raise RuntimeError("AI_PIPELINE_MODE는 one_call 또는 multi 여야 합니다.")

    output_dir = save_run(request, artifacts, files)

    return {
        "ok": True,
        "project_type": detect_project_type(request),
        "provider": provider,
        "model": model_summary,
        "model_candidates": get_model_candidates(get_model()),
        "mode": mode,
        "calls": calls,
        "output_dir": str(output_dir),
        "files": [item["path"] for item in files],
        "quality_score": extract_quality_score(files, artifacts),
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
        if path not in ("/api/run", "/api/agent-chat"):
            self.send_json(404, {"ok": False, "error": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if path == "/api/agent-chat":
                agent = str(payload.get("agent", "")).strip().lower()
                question = str(payload.get("question", "")).strip()
                if not question:
                    self.send_json(400, {"ok": False, "error": "질문을 입력해주세요."})
                    return
                result = run_agent_chat(agent, question)
                self.send_json(200, result)
                return

            request = str(payload.get("request", "")).strip()
            if not request:
                self.send_json(400, {"ok": False, "error": "요청 내용을 입력해주세요."})
                return

            result = run_ai_pipeline(request)
            self.send_json(200, result)
        except RetryableAIError as exc:
            traceback.print_exc()
            self.send_json(503, {"ok": False, "retryable": True, "retry_after": exc.retry_after, "error": str(exc)})
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
