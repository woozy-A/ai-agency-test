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
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
FORBIDDEN_STATIC_NAMES = {
    ".env",
    ".env.example",
    ".gitignore",
}
FORBIDDEN_STATIC_SUFFIXES = {
    ".key",
    ".pem",
    ".p12",
}


class RetryableAIError(RuntimeError):
    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return

    file_values = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        file_values[key] = value

    for key, value in file_values.items():
        os.environ.setdefault(key, value)


def get_provider() -> str:
    load_env()
    return os.getenv("AI_PROVIDER", "gemini").strip().lower()


def get_model(provider: str | None = None) -> str:
    provider = provider or get_provider()
    if provider == "openai":
        return os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    if provider == "gemini":
        return os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    if provider == "ollama":
        return os.getenv("OLLAMA_MODEL", "qwen3:14b")
    raise RuntimeError(f"지원하지 않는 AI_PROVIDER입니다: {provider}")


def get_model_candidates(primary_model: str, provider: str | None = None) -> list[str]:
    provider = provider or get_provider()
    models = [primary_model]
    if provider == "gemini":
        fallback_raw = os.getenv("GEMINI_FALLBACK_MODELS", "gemini-2.0-flash-lite,gemini-2.0-flash")
    elif provider == "openai":
        fallback_raw = os.getenv("OPENAI_FALLBACK_MODELS", "")
    elif provider == "ollama":
        fallback_raw = os.getenv("OLLAMA_FALLBACK_MODELS", "qwen3:14b,freehuntx/qwen3-coder:14b,llama3.1:latest,gemma4:latest")
    else:
        fallback_raw = ""

    for item in fallback_raw.split(","):
        candidate = item.strip()
        if candidate and candidate not in models:
            models.append(candidate)
    return models


def get_agent_provider(agent_key: str) -> str:
    load_env()
    return os.getenv(f"{agent_key.upper()}_PROVIDER", get_provider()).strip().lower()


def get_agent_model(agent_key: str) -> str:
    env_key = f"{agent_key.upper()}_MODEL"
    provider = get_agent_provider(agent_key)
    return os.getenv(env_key, get_model(provider))


def get_agent_route(agent_key: str) -> dict[str, str | list[str]]:
    provider = get_agent_provider(agent_key)
    model = get_agent_model(agent_key)
    return {
        "provider": provider,
        "model": model,
        "kind": "Local" if provider == "ollama" else "External API",
        "candidates": get_model_candidates(model, provider),
    }


def get_pipeline_mode() -> str:
    load_env()
    return os.getenv("AI_PIPELINE_MODE", "multi").strip().lower()


def is_important_request(request: str) -> bool:
    lowered = request.lower()
    markers = (
        "중요",
        "진짜 중요한",
        "매우 중요",
        "신중",
        "퀄리티",
        "품질",
        "제대로",
        "난제",
        "최대 난제",
        "인류",
        "mvp",
        "비즈니스 모델",
        "수익",
        "플랫폼",
        "확장성",
        "정부지원",
        "b2b",
        "object detection",
        "coreml",
        "ar",
        "프로덕션",
        "배포",
        "상용",
        "실서비스",
        "보안",
        "결제",
        "로그인",
        "xcode",
        "swift",
        "macos",
        "ios",
        "production",
        "release",
        "security",
        "payment",
    )
    return len(request.strip()) >= 500 or any(marker in lowered for marker in markers)


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


def ask_ollama_agent(agent_name: str, role_prompt: str, user_prompt: str, model: str) -> str:
    endpoint = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": role_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {
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
        with urlopen(request, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(
            "Ollama 서버에 연결할 수 없습니다. `ollama serve` 또는 Ollama 앱이 실행 중인지 확인해주세요."
        ) from exc

    text = str(data.get("message", {}).get("content", "")).strip()
    if not text:
        raise RuntimeError(f"{agent_name}가 Ollama에서 빈 응답을 반환했습니다: {data}")
    return text


def ask_agent(
    client,
    agent_name: str,
    role_prompt: str,
    user_prompt: str,
    model: str | None = None,
    provider: str | None = None,
) -> str:
    provider = provider or get_provider()
    model = model or get_model(provider)
    if provider == "openai":
        client = client or require_openai_client()
        last_error = None
        for candidate in get_model_candidates(model, provider):
            try:
                return ask_openai_agent(client, agent_name, role_prompt, user_prompt, candidate)
            except Exception as exc:
                last_error = exc
        raise last_error or RuntimeError(f"{agent_name} OpenAI 호출에 실패했습니다.")
    if provider == "gemini":
        last_error = None
        for candidate in get_model_candidates(model, provider):
            try:
                return ask_gemini_agent(agent_name, role_prompt, user_prompt, candidate)
            except (RetryableAIError, RuntimeError) as exc:
                last_error = exc
                if not is_model_fallback_error(exc):
                    raise
        raise last_error or RuntimeError(f"{agent_name} Gemini 호출에 실패했습니다.")
    if provider == "ollama":
        last_error = None
        for candidate in get_model_candidates(model, provider):
            try:
                return ask_ollama_agent(agent_name, role_prompt, user_prompt, candidate)
            except RuntimeError as exc:
                last_error = exc
                if "Ollama 서버에 연결할 수 없습니다" in str(exc):
                    raise
        raise last_error or RuntimeError(f"{agent_name} Ollama 호출에 실패했습니다.")
    raise RuntimeError(f"지원하지 않는 AI_PROVIDER입니다: {provider}")


def ask_agent_once(
    client,
    agent_name: str,
    role_prompt: str,
    user_prompt: str,
    model: str,
    provider: str,
) -> str:
    if provider == "openai":
        return ask_openai_agent(client or require_openai_client(), agent_name, role_prompt, user_prompt, model)
    if provider == "gemini":
        return ask_gemini_agent(agent_name, role_prompt, user_prompt, model)
    if provider == "ollama":
        return ask_ollama_agent(agent_name, role_prompt, user_prompt, model)
    raise RuntimeError(f"지원하지 않는 AI_PROVIDER입니다: {provider}")


def ask_final_editor(client, role_prompt: str, user_prompt: str, important: bool) -> tuple[str, str]:
    fallback_provider = os.getenv("FINAL_LOCAL_PROVIDER", "ollama")
    fallback_model = os.getenv("FINAL_LOCAL_MODEL", "qwen3:14b")
    normal_models = [os.getenv("FINAL_MODEL", "gemini-2.0-flash")]
    director_fallbacks = os.getenv(
        "FINAL_DIRECTOR_FALLBACK_MODELS",
        "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash",
    )
    important_models = [os.getenv("FINAL_DIRECTOR_MODEL", "gemini-2.5-pro")]
    important_models.extend(item.strip() for item in director_fallbacks.split(",") if item.strip())
    chain = [("gemini", model) for model in (important_models if important else normal_models)]
    chain.append((fallback_provider, fallback_model))

    last_error = None
    tried = []
    for provider, model in chain:
        route = f"{provider}/{model}"
        if route in tried:
            continue
        tried.append(route)
        try:
            return ask_agent_once(client, "Finalizer", role_prompt, user_prompt, model, provider), " -> ".join(tried)
        except (RetryableAIError, RuntimeError, Exception) as exc:
            last_error = exc
            if provider != "gemini" or not is_model_fallback_error(exc):
                if provider == fallback_provider and model == fallback_model:
                    break
                if provider != "gemini":
                    continue
    raise last_error or RuntimeError("Finalizer 호출에 실패했습니다.")


ROLE_FALLBACKS = {
    "pm": ["mike", "nora", "iris"],
    "structure": ["mina", "nora", "dana"],
    "dev": ["jay", "dana", "mike"],
    "qa": ["yuna", "testkim", "jason", "vera"],
    "scope": ["nora", "mike", "iris"],
    "dx": ["dana", "jay", "testkim"],
    "redteam": ["jason", "yuna", "vera"],
    "security": ["sana", "jason", "dana"],
    "editor": ["iris", "mike", "vera"],
    "judge": ["vera", "yuna", "jason"],
}


def role_absence_summary(exc: Exception) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text[:160] or exc.__class__.__name__


def emergency_role_output(role_label: str, request: str, failures: list[str]) -> str:
    return (
        f"## Emergency {role_label} Output\n\n"
        "지정된 담당자와 대체 담당자가 모두 응답하지 않아 최소 운영 규칙으로 산출물을 생성합니다.\n\n"
        f"- 원 요청: {request}\n"
        "- 처리 원칙: 범위를 작게 유지하고, Codex가 바로 실행할 수 있는 지시와 검증 기준을 우선한다.\n"
        "- 검수 필요: 이 섹션은 모델 검토 없이 생성된 비상 산출물이므로 창우가 핵심 범위와 위험 항목을 확인해야 한다.\n"
        f"- 실패 기록: {' / '.join(failures)}"
    )


def run_role_task(
    client,
    role_key: str,
    role_label: str,
    role_prompt: str,
    user_prompt: str,
    request: str,
    performance: list[dict[str, str]],
) -> str:
    failures = []
    for index, agent_key in enumerate(ROLE_FALLBACKS[role_key]):
        agent = AGENT_ROLES[agent_key]
        provider = get_agent_provider(agent_key)
        model = get_agent_model(agent_key)
        route = f"{provider}/{model}"
        try:
            result = ask_agent(client, agent["name"], role_prompt, user_prompt, model, provider)
            performance.append(
                {
                    "role": role_label,
                    "agent": agent["name"],
                    "route": route,
                    "status": "대체 성공" if index else "정상 출근",
                    "note": "담당자가 업무를 완료했습니다." if index == 0 else f"{ROLE_FALLBACKS[role_key][0]} 결근으로 대체 투입되었습니다.",
                }
            )
            return result
        except Exception as exc:
            failure = role_absence_summary(exc)
            failures.append(f"{agent['name']}({failure})")
            performance.append(
                {
                    "role": role_label,
                    "agent": agent["name"],
                    "route": route,
                    "status": "결근",
                    "note": failure,
                }
            )

    performance.append(
        {
            "role": role_label,
            "agent": "Emergency Desk",
            "route": "internal/rule-based",
            "status": "비상 운영",
            "note": "모든 담당자와 대체자가 실패해 최소 산출물을 생성했습니다.",
        }
    )
    return emergency_role_output(role_label, request, failures)


def build_hr_report(performance: list[dict[str, str]], final_route: str) -> str:
    absences = [item for item in performance if item["status"] == "결근"]
    backups = [item for item in performance if item["status"] == "대체 성공"]
    emergencies = [item for item in performance if item["status"] == "비상 운영"]
    score = max(0, 100 - len(absences) * 8 - len(emergencies) * 20 + len(backups) * 2)

    lines = [
        "# 인사평가 및 결근 처리",
        "",
        f"- 회사 운영 점수: {min(score, 100)}/100",
        f"- Finalizer 라우트: {final_route}",
        f"- 결근 처리: {len(absences)}건",
        f"- 대체 투입 성공: {len(backups)}건",
        f"- 비상 운영: {len(emergencies)}건",
        "",
        "## 직원별 업무 기록",
        "",
    ]
    for item in performance:
        lines.append(f"- {item['role']} / {item['agent']} / {item['route']} / {item['status']}: {item['note']}")

    lines.extend(
        [
            "",
            "## 운영 원칙",
            "",
            "- 한 명이 결근해도 다음 담당자가 업무를 이어받는다.",
            "- 외부 API가 실패해도 로컬 모델 또는 비상 산출물로 최소 결과를 만든다.",
            "- 반복 결근 모델은 기본 라우팅에서 제외하거나 낮은 우선순위로 내린다.",
            "- Codex 부대표는 직원 산출물을 보고 실제 코드 작성과 검증을 맡는다.",
        ]
    )
    return "\n".join(lines)


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

    provider = get_agent_provider(agent_key)
    client = require_openai_client() if provider == "openai" else None
    model = get_agent_model(agent_key)
    role_prompt = (
        f"{agent['prompt']} 너의 이름은 {agent['name']}이고 역할은 {agent['role']}다. "
        "창우에게 한국어로 답한다. 답변은 6문장 이내로 짧고 구체적으로 한다. "
        "필요하면 체크리스트를 3개 이하로만 제시한다."
    )
    answer = ask_agent(client, agent["name"], role_prompt, question, model, provider)
    return {
        "ok": True,
        "agent": agent_key,
        "name": agent["name"],
        "role": agent["role"],
        "provider": provider,
        "model": model,
        "model_candidates": get_model_candidates(model, provider),
        "answer": answer,
    }


def review_focus_for(agent_key: str) -> str:
    focuses = {
        "jason": "위험, 허점, 모호한 요구사항, 실패 가능성만 냉정하게 지적한다.",
        "sana": "API 키, .env, 개인정보, 공개 저장소, 위험 명령, 보안/프라이버시 문제만 점검한다.",
        "vera": "100점 만점 점수와 감점 사유, blocking issue, warning을 제시한다.",
        "dana": "실행 방법, 로컬 환경 전제, 설치/실행 명령, 오류 메시지, 개발자 경험이 충분한지 검토한다.",
        "jay": "구현 지시, 파일 구조, 테스트 명령, Swift/Xcode/웹 같은 기술 스택 지시가 구체적인지 검토한다.",
        "yuna": "성공 기준, 자동 테스트, 직접 검수 시나리오, 회귀 위험이 검증 가능하게 적혔는지 본다.",
        "testkim": "자동화 가능한 테스트와 실패 조건, 수동 검수 절차를 구체화한다.",
        "iris": "Codex가 오해할 표현, 모호한 문장, 산출물 형식을 다듬는다.",
        "nora": "범위 초과, 이번에 할 것/하지 않을 것, 과도한 요구를 줄인다.",
        "mike": "목표, 우선순위, 산출물, 실행 순서가 현실적인지 PM 관점으로 검토한다.",
        "mina": "사용자 흐름, 화면 상태, UX 검수 기준이 충분한지 본다.",
    }
    return focuses.get(agent_key, "자기 역할에 맞는 관점으로만 검토하고, 역할 밖 질문은 담당자를 안내한다.")


def run_artifact_review(agent_key: str, artifact_name: str, artifact: str, instruction: str) -> dict:
    agent = AGENT_ROLES.get(agent_key)
    if not agent:
        raise RuntimeError("알 수 없는 직원입니다.")
    if not artifact:
        raise RuntimeError("검토할 산출물이 비어 있습니다.")

    provider = get_agent_provider(agent_key)
    client = require_openai_client() if provider == "openai" else None
    model = get_agent_model(agent_key)
    focus = review_focus_for(agent_key)
    role_prompt = (
        f"{agent['prompt']} 너의 이름은 {agent['name']}이고 역할은 {agent['role']}다. "
        f"이번 일은 일반 대화가 아니라 산출물 재검토다. {focus} "
        "역할 밖의 질문이면 직접 해결하려 하지 말고 어떤 담당자에게 넘겨야 하는지 말한다. "
        "답변은 한국어로 작성하고, 반드시 '통과/수정 필요', '주요 지적', '다음 조치'를 포함한다."
    )
    user_prompt = (
        f"검토 대상 artifact: {artifact_name}\n\n"
        f"창우의 추가 지시:\n{instruction or '자기 역할 기준으로 재검토해줘.'}\n\n"
        f"검토할 산출물:\n{artifact}"
    )
    answer = ask_agent(client, agent["name"], role_prompt, user_prompt, model, provider)
    return {
        "ok": True,
        "agent": agent_key,
        "name": agent["name"],
        "role": agent["role"],
        "provider": provider,
        "model": model,
        "artifact": artifact_name,
        "focus": focus,
        "answer": answer,
    }


def build_rework_prompt(original_request: str, result: str, extra_context: str, reviews: dict[str, str]) -> str:
    review_text = "\n\n".join(f"## {name}\n{content}" for name, content in reviews.items())
    return f"""# Codex 재작업 지시서

## 원래 요청
{original_request or "원래 요청이 제공되지 않았습니다. 아래 결과물과 문제 상황을 기준으로 재작업한다."}

## 현재 결과물 / 에러 / 관찰 내용
{result}

## 추가 맥락
{extra_context or "추가 맥락 없음"}

## 직원 재검토 요약
{review_text}

## 재작업 목표
현재 결과물을 처음부터 갈아엎기보다, 문제를 일으키는 부분을 좁게 수정한다. 기존에 잘 동작하는 기능과 스타일은 유지한다.

## 수정 지시
- 재현 가능한 문제를 먼저 요약한다.
- 수정 전 성공 기준 체크리스트를 작성한다.
- 필요한 파일만 수정한다.
- 메뉴/상태/검증 로직처럼 데이터 무결성이 중요한 부분은 테스트 가능한 구조로 정리한다.
- UI 문제라면 데스크톱과 모바일에서 텍스트 겹침, 버튼 비활성 상태, 빈 상태를 확인한다.
- 에러 로그가 있다면 원인 후보와 실제 수정 근거를 분리해서 설명한다.

## 검증 기준
- 자동으로 확인 가능한 것은 테스트나 스크립트로 검증한다.
- 브라우저 확인이 필요한 것은 직접 검수 시나리오를 제공한다.
- 수정 후 결과 보고는 반드시 아래 형식을 따른다.

## 완료 보고 형식
- 변경 파일
- 자동 검증 완료 항목
- 검수 필요 항목
- 위험한 항목
- 실행 방법
"""


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


def run_rework_pipeline(original_request: str, result: str, extra_context: str = "") -> dict:
    if not result.strip():
        raise RuntimeError("재작업할 결과물이나 에러 내용을 입력해주세요.")

    review_targets = [
        ("Jay", "jay", "구현 지시와 코드 구조 관점에서 수정해야 할 점을 찾아줘."),
        ("Dana", "dana", "실행 방법, 재현 절차, 로컬 환경 문제를 찾아줘."),
        ("Yuna", "yuna", "성공 기준과 테스트 누락을 찾아줘."),
        ("Jason", "jason", "위험한 허점과 실패 가능성만 지적해줘."),
        ("Sana", "sana", "보안, 비밀값, 공개 저장소 위험만 점검해줘."),
        ("Vera", "vera", "수정 우선순위와 품질 점수를 매겨줘."),
    ]
    reviews = {}
    performance = []
    calls = 0
    artifact = f"원래 요청:\n{original_request}\n\n현재 결과물/에러:\n{result}\n\n추가 맥락:\n{extra_context}"

    for label, agent_key, instruction in review_targets:
        try:
            response = run_artifact_review(agent_key, "codex_result", artifact, instruction)
            reviews[label] = response["answer"]
            performance.append(f"- {label}: {response['provider']}/{response['model']} 검토 완료")
            calls += 1
        except Exception as exc:
            reviews[label] = f"검토 실패: {role_absence_summary(exc)}"
            performance.append(f"- {label}: 검토 실패, 다른 검토 결과로 재작업 지시서 생성")

    rework_prompt = build_rework_prompt(original_request, result, extra_context, reviews)
    artifacts = {
        "brief": "Codex가 만든 결과물 또는 에러를 기반으로 재작업 지시서를 생성했습니다.",
        "plan": "1. 결과물/에러 수집\n2. 역할별 재검토\n3. 수정 우선순위 정리\n4. Codex용 재작업 프롬프트 생성",
        "design": reviews.get("Dana", ""),
        "dev": reviews.get("Jay", ""),
        "review": "\n\n".join(reviews.values()),
        "final": rework_prompt,
        "hr": "# Rework 인사평가\n\n" + "\n".join(performance),
    }
    files = [
        {"path": "generated_prompt/rework_prompt.md", "content": rework_prompt},
        {"path": "generated_prompt/rework_reviews.md", "content": artifacts["review"]},
    ]
    output_dir = save_run("rework-" + (original_request or "codex-result"), artifacts, files)
    return {
        "ok": True,
        "mode": "rework",
        "provider": get_provider(),
        "model": "Rework=Jay+Dana+Yuna+Jason+Sana+Vera",
        "calls": calls,
        "output_dir": str(output_dir.relative_to(ROOT)),
        "files": [item["path"] for item in files],
        "artifacts": artifacts,
    }


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
        "너는 Changwoo Prompt Agency의 PM/기획 Mike다. 창우 사장의 요청을 요구사항, 구현 범위, "
        "하지 않을 일, 성공 기준으로 정리한다. 빠른 요약보다 좋은 Codex 작업지시서를 만드는 것이 목적이다. "
        "앱 요청은 Codex가 MVP 수준까지 실제 구현하고, 가능하면 그 이상도 판단해 구현하도록 전제한다. "
        "답변은 한국어로 쓰고 Codex가 이어받기 쉽게 구체적으로 쓴다."
    )
    mina_role = (
        "너는 Changwoo Prompt Agency의 기획 보조 Mina다. Mike의 범위를 보고 사용자 흐름, 화면/파일 구조, "
        "산출물 형태를 정리한다. 초보자가 프롬프트 작성법을 배울 수 있도록 왜 이 구조가 필요한지도 짧게 남긴다."
    )
    jay_role = (
        "너는 Changwoo Prompt Agency의 Dev/구현안 Jay다. Mike와 Mina의 내용을 바탕으로 Codex가 수정할 "
        "파일, 코드 구조, 명령어, 테스트 전략을 제안한다. Swift, 웹, 로컬 서버 같은 프로젝트 타입별 차이를 구분한다. "
        "Codex에게 '알아서 MVP를 구현하라'가 아니라, 어떤 파일과 동작을 구현해야 MVP인지 명확히 지시한다."
    )
    yuna_role = (
        "너는 Changwoo Prompt Agency의 QA/비판 Yuna다. brief, structure, dev 결과에서 버그, 성능, 예외 케이스, "
        "모호한 요구사항을 찾는다. 칭찬보다 실패 가능성과 검증 방법을 우선한다."
    )
    nora_role = (
        "너는 Scope Manager Nora다. 큰 아이디어를 Codex가 이번 작업에서 구현할 MVP, 다음 버전, 하지 않을 일로 나눈다. "
        "너무 작게 잘라 가치가 사라지지 않게 하되, 한 번에 구현 가능한 범위로 정리한다."
    )
    dana_role = (
        "너는 Developer Experience 담당 Dana다. Codex가 만든 결과물을 창우가 바로 실행하고 검수할 수 있게 "
        "설치, 실행, 환경 변수, 샘플 데이터, 실패 시 확인할 포인트를 정리한다."
    )
    jason_role = (
        "너는 Red Team Reviewer Jason이다. 사업/제품/기술 관점에서 실패할 가능성, 과장된 주장, 구현 난이도, "
        "법적/운영 리스크를 칭찬 없이 지적한다."
    )
    sana_role = (
        "너는 Security & Privacy 담당 Sana다. 카메라, 이미지, 위치, 결제/크레딧, 사용자 데이터, 공개 저장소, API 키, "
        "모델 추론 결과의 책임 문제를 점검한다."
    )
    iris_role = (
        "너는 Prompt Editor Iris다. 앞 단계 결과를 Codex가 오해하지 않는 문장으로 정리한다. "
        "모호한 표현을 지우고 산출물 형식, 구현 순서, 완료 보고 형식을 선명하게 만든다."
    )
    vera_role = (
        "너는 Validation Judge Vera다. 최종 프롬프트가 초보자에게 학습 가치가 있는지, Codex가 MVP 이상을 구현할 만큼 "
        "충분히 구체적인지 100점 만점으로 평가하고 blocking issue를 표시한다."
    )
    final_role = (
        "너는 Final Editor다. 앞 단계 산출물을 단순 요약하지 말고, 창우가 Codex에 그대로 붙여넣으면 "
        "MVP 수준의 실제 결과물이 나오도록 최종 프롬프트로 재구성한다. "
        "빠른 답보다 정확하고 검증 가능한 작업지시서를 우선한다. "
        "반드시 다음 섹션을 포함한다: 목표, MVP 범위, 구현 지시, 파일 구조, 자동 테스트, 직접 검수 시나리오, "
        "보안/개인정보 주의사항, 위험 항목, 완료 보고 형식."
    )

    mike_provider = get_agent_provider("mike")
    mina_provider = get_agent_provider("mina")
    jay_provider = get_agent_provider("jay")
    yuna_provider = get_agent_provider("yuna")
    mike_model = get_agent_model("mike")
    mina_model = get_agent_model("mina")
    jay_model = get_agent_model("jay")
    yuna_model = get_agent_model("yuna")
    important = is_important_request(request)
    performance = []

    brief = run_role_task(
        client,
        "pm",
        "PM / 기획",
        mike_role,
        f"창우의 요청:\n{request}\n\n1) 요구사항\n2) 구현 범위\n3) 성공 기준\n4) Jay/Yuna가 봐야 할 쟁점을 작성해줘.",
        request,
        performance,
    )
    design = run_role_task(
        client,
        "structure",
        "기획 보조 / 구조",
        mina_role,
        f"원 요청:\n{request}\n\nMike 결과:\n{brief}\n\nCodex 프롬프트에 들어갈 사용자 흐름, 화면/파일 구조, 산출물 형태를 제안해줘.",
        request,
        performance,
    )
    dev = run_role_task(
        client,
        "dev",
        "Dev / 구현안",
        jay_role,
        f"원 요청:\n{request}\n\nMike 결과:\n{brief}\n\nMina 결과:\n{design}\n\nCodex가 실제 코드 작성/수정에 착수할 수 있도록 구현안, 파일 구조, 명령어, 테스트 전략을 작성해줘.",
        request,
        performance,
    )
    review = run_role_task(
        client,
        "qa",
        "QA / 비판",
        yuna_role,
        f"원 요청:\n{request}\n\nMike:\n{brief}\n\nMina:\n{design}\n\nJay:\n{dev}\n\n버그, 성능, 예외 케이스, 누락된 검증을 중심으로 비판해줘.",
        request,
        performance,
    )
    scope = run_role_task(
        client,
        "scope",
        "Scope / 범위 관리",
        nora_role,
        f"원 요청:\n{request}\n\nMike:\n{brief}\n\nMina:\n{design}\n\nJay:\n{dev}\n\n이번 Codex 작업에서 구현할 MVP, 다음 버전, 하지 않을 일을 나눠줘.",
        request,
        performance,
    )
    dx = run_role_task(
        client,
        "dx",
        "DX / 실행 경험",
        dana_role,
        f"원 요청:\n{request}\n\nJay:\n{dev}\n\nYuna:\n{review}\n\nCodex 결과물을 실행하고 검수하기 위한 환경 전제, 실행 명령, 샘플 데이터, 실패 시 확인할 점을 정리해줘.",
        request,
        performance,
    )
    redteam = run_role_task(
        client,
        "redteam",
        "Red Team / 위험 지적",
        jason_role,
        f"원 요청:\n{request}\n\n현재 산출물:\n{brief}\n\n{design}\n\n{dev}\n\n{review}\n\n과장된 기능, 실패 가능성, 구현 난이도, 비즈니스 리스크만 지적해줘.",
        request,
        performance,
    )
    security = run_role_task(
        client,
        "security",
        "Security / 개인정보",
        sana_role,
        f"원 요청:\n{request}\n\n제품/기술 초안:\n{design}\n\n{dev}\n\n카메라, 이미지, 위치, 크레딧, 개인정보, API 키, 공개 배포 보안 위험을 점검해줘.",
        request,
        performance,
    )
    editor = run_role_task(
        client,
        "editor",
        "Prompt Editor / 문장 정리",
        iris_role,
        f"원 요청:\n{request}\n\nMike:\n{brief}\n\nMina:\n{design}\n\nJay:\n{dev}\n\nNora:\n{scope}\n\nDana:\n{dx}\n\nJason:\n{redteam}\n\nSana:\n{security}\n\nCodex가 오해할 표현을 줄이고 최종 프롬프트에 넣을 구조를 정리해줘.",
        request,
        performance,
    )
    judge = run_role_task(
        client,
        "judge",
        "Validation / 품질 평가",
        vera_role,
        f"원 요청:\n{request}\n\n전체 검토:\nMike={brief}\n\nMina={design}\n\nJay={dev}\n\nYuna={review}\n\nNora={scope}\n\nDana={dx}\n\nJason={redteam}\n\nSana={security}\n\nIris={editor}\n\n품질 점수, blocking issue, 수정 필요 항목을 평가해줘.",
        request,
        performance,
    )
    final_prompt_input = (
        f"원 요청:\n{request}\n\nPM/기획 Mike:\n{brief}\n\n구조 정리 Mina:\n{design}\n\nDev/구현안 Jay:\n{dev}\n\n"
        f"QA/비판 Yuna:\n{review}\n\nScope Nora:\n{scope}\n\nDX Dana:\n{dx}\n\nRed Team Jason:\n{redteam}\n\n"
        f"Security Sana:\n{security}\n\nPrompt Editor Iris:\n{editor}\n\nValidation Vera:\n{judge}\n\n"
        "이 내용을 하나의 Codex용 최종 프롬프트로 재구성해줘. 설명문이 아니라, 바로 붙여넣어 실행할 지시문이어야 한다. "
        "Codex가 실제 MVP를 구현하고, 구현 후 자동 검증과 수동 검수 보고까지 하도록 지시해."
    )
    try:
        final, final_route = ask_final_editor(client, final_role, final_prompt_input, important)
    except Exception as exc:
        final_route = "internal/emergency-finalizer"
        final = (
            "# Codex 실행 프롬프트\n\n"
            "아래 요청을 구현 전에 성공 기준을 먼저 세우고, 구현 후 자동 검증과 직접 검수 시나리오를 보고하는 방식으로 처리해줘.\n\n"
            f"## 원 요청\n{request}\n\n"
            f"## PM / 기획\n{brief}\n\n"
            f"## 구조\n{design}\n\n"
            f"## 구현안\n{dev}\n\n"
            f"## QA / 위험\n{review}\n\n"
            "## 완료 보고 형식\n"
            "- 자동 검증 완료 항목\n- 검수 필요 항목\n- 위험한 항목\n- 변경 파일\n- 실행 방법\n"
        )
        performance.append(
            {
                "role": "Final Editor",
                "agent": "Finalizer",
                "route": final_route,
                "status": "비상 운영",
                "note": role_absence_summary(exc),
            }
        )
    performance.append(
        {
            "role": "Final Editor",
            "agent": "Finalizer",
            "route": final_route,
            "status": "정상 납품" if final_route != "internal/emergency-finalizer" else "비상 납품",
            "note": "최종 Codex 프롬프트를 압축했습니다.",
        }
    )
    hr = build_hr_report(performance, final_route)

    artifacts = {
        "brief": brief,
        "plan": scope,
        "design": design,
        "dev": dev,
        "review": "\n\n".join(
            [
                "## Yuna QA\n" + review,
                "## Jason Red Team\n" + redteam,
                "## Sana Security\n" + security,
                "## Vera Validation\n" + judge,
            ]
        ),
        "final": final,
        "hr": hr,
    }
    files = [
        {"path": "generated_prompt/codex_prompt.md", "content": final},
        {"path": "generated_prompt/pm_brief.md", "content": brief},
        {"path": "generated_prompt/scope.md", "content": scope},
        {"path": "generated_prompt/ux_structure.md", "content": design},
        {"path": "generated_prompt/implementation_plan.md", "content": dev},
        {"path": "generated_prompt/dx_runbook.md", "content": dx},
        {"path": "generated_prompt/risk_notes.md", "content": redteam},
        {"path": "generated_prompt/security_notes.md", "content": security},
        {"path": "generated_prompt/prompt_editor_notes.md", "content": editor},
        {"path": "generated_prompt/quality_score.md", "content": judge},
    ]
    models = (
        f"Mike={mike_provider}/{mike_model}, Mina={mina_provider}/{mina_model}, Jay={jay_provider}/{jay_model}, "
        f"Yuna={yuna_provider}/{yuna_model}, Nora={get_agent_provider('nora')}/{get_agent_model('nora')}, "
        f"Dana={get_agent_provider('dana')}/{get_agent_model('dana')}, Jason={get_agent_provider('jason')}/{get_agent_model('jason')}, "
        f"Sana={get_agent_provider('sana')}/{get_agent_model('sana')}, Iris={get_agent_provider('iris')}/{get_agent_model('iris')}, "
        f"Vera={get_agent_provider('vera')}/{get_agent_model('vera')}, Finalizer={final_route}"
    )
    return artifacts, files, len(performance), models


def get_agent_config() -> dict:
    agents = {}
    for key, value in AGENT_ROLES.items():
        route = get_agent_route(key)
        agents[key] = {
            "name": value["name"],
            "role": value["role"],
            **route,
        }
    return {
        "ok": True,
        "mode": get_pipeline_mode(),
        "important_markers": [
            "중요",
            "신중",
            "제대로",
            "퀄리티",
            "MVP",
            "비즈니스 모델",
            "플랫폼",
            "확장성",
            "프로덕션",
            "배포",
            "보안",
            "결제",
            "Swift",
            "macOS",
            "iOS",
        ],
        "finalizer": {
            "normal": [
                f"gemini/{os.getenv('FINAL_MODEL', 'gemini-2.0-flash')}",
                f"ollama/{os.getenv('FINAL_LOCAL_MODEL', 'qwen3:14b')}",
            ],
            "important": [
                f"gemini/{os.getenv('FINAL_DIRECTOR_MODEL', 'gemini-2.5-pro')}",
                *[
                    f"gemini/{item.strip()}"
                    for item in os.getenv(
                        "FINAL_DIRECTOR_FALLBACK_MODELS",
                        "gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash",
                    ).split(",")
                    if item.strip()
                ],
                f"ollama/{os.getenv('FINAL_LOCAL_MODEL', 'qwen3:14b')}",
            ],
        },
        "agents": agents,
    }


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
        "model_candidates": get_model_candidates(get_model(provider), provider),
        "mode": mode,
        "calls": calls,
        "output_dir": str(output_dir.relative_to(ROOT)),
        "files": [item["path"] for item in files],
        "quality_score": extract_quality_score(files, artifacts),
        "artifacts": artifacts,
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def is_forbidden_static_path(self, path: str) -> bool:
        requested = urlparse(path).path
        parts = [part for part in requested.split("/") if part]
        if not parts:
            return False
        if any(part.startswith(".") for part in parts):
            return True
        if parts[0] == "outputs":
            return True
        leaf = parts[-1]
        lowered = leaf.lower()
        if leaf in FORBIDDEN_STATIC_NAMES:
            return True
        if any(lowered.endswith(suffix) for suffix in FORBIDDEN_STATIC_SUFFIXES):
            return True
        if any(marker in lowered for marker in ("secret", "apikey", "api_key", "token", "credential")):
            return True
        return False

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/agent-config":
            try:
                self.send_json(200, get_agent_config())
            except Exception as exc:
                traceback.print_exc()
                self.send_json(500, {"ok": False, "error": str(exc)})
            return
        if self.is_forbidden_static_path(self.path):
            self.send_error(403, "Forbidden")
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if self.is_forbidden_static_path(self.path):
            self.send_error(403, "Forbidden")
            return
        super().do_HEAD()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/api/run", "/api/agent-chat", "/api/review-artifact", "/api/rework"):
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
            if path == "/api/review-artifact":
                agent = str(payload.get("agent", "")).strip().lower()
                artifact_name = str(payload.get("artifact_name", "final")).strip() or "final"
                artifact = str(payload.get("artifact", "")).strip()
                instruction = str(payload.get("instruction", "")).strip()
                result = run_artifact_review(agent, artifact_name, artifact, instruction)
                self.send_json(200, result)
                return
            if path == "/api/rework":
                original_request = str(payload.get("original_request", "")).strip()
                result_text = str(payload.get("result", "")).strip()
                extra_context = str(payload.get("extra_context", "")).strip()
                result = run_rework_pipeline(original_request, result_text, extra_context)
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
