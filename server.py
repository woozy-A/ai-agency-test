from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
PENDING_CANCELS: dict[str, float] = {}
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


class PipelineTimeoutError(RuntimeError):
    pass


class PipelineContext:
    def __init__(self, timeout_seconds: int | None = None):
        self.started_at = time.monotonic()
        self.timeout_seconds = timeout_seconds or int(os.getenv("PIPELINE_TIMEOUT_SECONDS", "2400"))
        self.absent_agents: set[str] = set()
        self.progress: list[str] = []
        self.cancelled = False
        self.lock = threading.Lock()

    def add_progress(self, message: str) -> None:
        elapsed = int(time.monotonic() - self.started_at)
        with self.lock:
            self.progress.append(f"{elapsed}s · {message}")

    def snapshot(self) -> list[str]:
        with self.lock:
            return list(self.progress)

    def check_timeout(self) -> None:
        if self.cancelled:
            raise RuntimeError("작업이 취소되었습니다.")
        elapsed = time.monotonic() - self.started_at
        if elapsed > self.timeout_seconds:
            raise PipelineTimeoutError(f"서버 작업 제한 시간 {self.timeout_seconds}초를 초과했습니다.")

    def cancel(self) -> None:
        self.cancelled = True
        self.add_progress("작업 취소 요청을 받았습니다.")


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
    return os.getenv("AI_PROVIDER", "gemini").strip().lower()  # FIX: PY-2


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
    return os.getenv(f"{agent_key.upper()}_PROVIDER", get_provider()).strip().lower()  # FIX: PY-2


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
    return os.getenv("AI_PIPELINE_MODE", "multi").strip().lower()  # FIX: PY-2


def is_important_request(request: str) -> bool:
    lowered = request.lower()
    line_count = len([line for line in request.splitlines() if line.strip()])
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
    word_markers = {"swift", "macos", "ios", "ar", "xcode", "mvp"}  # FIX: PY-3
    phrase_markers = {marker for marker in markers if marker not in word_markers}  # FIX: PY-3
    return (  # FIX: PY-3
        line_count >= 50
        or len(request.strip()) >= 500
        or any(marker in lowered for marker in phrase_markers)
        or any(re.search(rf"\b{re.escape(marker)}\b", lowered) for marker in word_markers)
    )


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


def ollama_tags_endpoint() -> str:
    endpoint = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
    parsed = urlparse(endpoint)
    return parsed._replace(path="/api/tags", query="", fragment="").geturl()


def get_installed_ollama_models(timeout: float = 0.8) -> set[str] | None:
    request = Request(ollama_tags_endpoint(), method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None
    return {str(item.get("name", "")).strip() for item in data.get("models", []) if item.get("name")}


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


def request_profile(request: str) -> dict[str, str | list[str]]:
    lowered = request.lower()
    if any(marker in lowered for marker in ("신발", "스니커", "sneaker", "shoe", "조던", "나이키", "아디다스")):
        return {
            "title": "shoe collection management app",
            "domain": "collection management for sneaker collectors with 100+ pairs",
            "item": "shoe",
            "item_plural": "shoes",
            "primary_user": "sneaker collector",
            "core_fields": ["name", "brand", "purchaseDate", "price", "photo", "category", "color", "size", "condition", "notes"],
            "summary_metrics": ["total owned pairs", "count by brand", "current-year spending", "monthly purchase trend", "recent purchases", "similar-shoe warning"],
            "optional_features": ["photo upload", "barcode/SKU input", "CSV export", "duplicate purchase prevention"],
        }
    return {
        "title": "personal inventory management app",
        "domain": "cataloging personal items and purchase history",
        "item": "item",
        "item_plural": "items",
        "primary_user": "user managing a personal collection",
        "core_fields": ["name", "brandOrCategory", "purchaseDate", "price", "photo", "condition", "notes"],
        "summary_metrics": ["total owned items", "count by category", "current-year spending", "monthly purchase trend", "recent purchases"],
        "optional_features": ["photo upload", "search/filter", "CSV export", "duplicate prevention"],
    }


def bullet_lines(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def emergency_role_output(role_label: str, request: str, failures: list[str]) -> str:
    profile = request_profile(request)
    title = profile["title"]
    fields = bullet_lines(profile["core_fields"])
    metrics = bullet_lines(profile["summary_metrics"])
    optional = bullet_lines(profile["optional_features"])
    failure_note = f"\n\n## 비상 운영 기록\n- 모델 호출 실패: {' / '.join(failures)}" if failures else ""

    if "PM" in role_label or "기획" in role_label:
        body = f"""## 목표
- {title}의 MVP를 만든다.
- 사용자가 보유한 {profile['item_plural']}을 빠르게 등록, 검색, 필터링하고 중복 구매를 줄이게 한다.
- 구매일과 가격 데이터를 기반으로 지출/보유 현황을 한눈에 보여준다.

## MVP 범위
- {profile['item']} 등록/수정/삭제
- 목록, 검색, 브랜드/카테고리 필터
- 상세 보기와 사진 미리보기
- 브랜드별 수량, 총 보유 수량, 올해 구매 금액 대시보드
- 브라우저 Local Storage 기반 데이터 저장

## 하지 않을 일
- 실제 쇼핑몰/정품 인증 API 연동
- 서버 로그인/클라우드 동기화
- 완전 자동 바코드 인식
- 모바일 앱 배포"""
    elif "UX" in role_label or "Design" in role_label or "화면" in role_label:
        body = f"""## 디자인 권장사항
- 첫 화면은 대시보드와 {profile['item']} 목록이 동시에 보이게 만든다.
- 카드에는 사진, 이름, 브랜드, 구매일, 가격, 상태를 표시한다.
- 상단에는 총 보유 수량, 올해 구매 금액, 최다 브랜드, 최근 구매를 compact stat으로 배치한다.
- 필터는 브랜드, 카테고리, 구매연도, 상태 기준으로 제공한다.

## 화면/상태 설계
- Empty: 아직 등록된 {profile['item']}이 없을 때 샘플 등록 버튼 표시
- List: 카드 그리드와 검색/필터
- Detail/Edit: 등록 폼, 사진 URL 또는 파일 입력, 가격/구매일 입력
- Dashboard: 브랜드별 수량과 월별 구매 금액 차트
- Error: 필수값 누락, 잘못된 가격/날짜 입력 메시지"""
    elif "Dev" in role_label or "구현" in role_label:
        body = f"""## 데이터 모델
필드는 다음 기준으로 설계한다.
{fields}

## 구현 지시
- 정적 웹 앱으로 구현한다. 프레임워크가 이미 없다면 HTML/CSS/JS만 사용한다.
- 상태는 단일 source of truth 배열로 관리하고 Local Storage에 저장한다.
- 샘플 데이터 12개 이상을 넣어 첫 실행부터 차트와 필터를 확인할 수 있게 한다.
- CRUD, 검색, 필터, 정렬, 통계 계산 함수를 분리한다.
- 차트는 외부 라이브러리 없이 CSS/DOM 기반 막대 차트로 구현한다.
- 사진은 로컬 파일 영구 저장 대신 이미지 URL 또는 object URL 미리보기로 처리한다."""
    elif "QA" in role_label or "비판" in role_label:
        body = f"""## 자동 테스트 기준
- 통계 계산 함수: 브랜드별 수량, 올해 구매 금액, 월별 구매 금액
- 필터 함수: 브랜드/카테고리/검색어 조합
- CRUD 후 Local Storage 저장/복원

## 직접 검수 시나리오
- {profile['item']} 1개 추가 후 목록/통계에 반영되는지 확인
- 비슷한 브랜드와 이름을 검색해 중복 구매 방지에 도움이 되는지 확인
- 올해 구매 금액이 가격 수정/삭제 후 즉시 바뀌는지 확인
- 필수 입력값 누락 시 사용자에게 명확한 오류가 보이는지 확인

## 위험 항목
- 사진 자동 인식/바코드 스캔은 MVP에서 과장하면 안 된다.
- 100개 이상 데이터에서 카드 그리드가 느려질 수 있다.
- 사용자가 귀찮아서 입력하지 않는 문제가 가장 큰 제품 리스크다."""
    else:
        body = f"""## 역할별 보강 메모
- 핵심 필드: {', '.join(profile['core_fields'])}
- 핵심 지표: {', '.join(profile['summary_metrics'])}
- 확장 후보: {', '.join(profile['optional_features'])}
- Codex 프롬프트에는 구현 파일, 테스트 기준, 직접 검수 시나리오를 반드시 포함한다."""

    return f"## Emergency {role_label} Output\n\n{body}{failure_note}"


def build_rule_based_codex_prompt(request: str) -> str:
    profile = request_profile(request)
    fields = bullet_lines(profile["core_fields"])
    metrics = bullet_lines(profile["summary_metrics"])
    optional = bullet_lines(profile["optional_features"])
    return f"""# Codex Execution Prompt

You are a senior frontend engineer with strong product judgment. Build a working MVP from the request below. Before implementation, write success criteria. After implementation, run available automated checks and provide manual QA scenarios.

## Original Request
{request}

## Goal
- Build a {profile['title']}.
- Target user: {profile['primary_user']}.
- Help the user see their owned {profile['item_plural']} at a glance and avoid buying near-duplicates.
- Use purchase date and price data to show ownership and spending trends.

## MVP Scope
- Add, edit, and delete {profile['item']} records.
- Card-based collection grid.
- Search, brand filter, category filter, and purchase-year filter.
- Detail view.
- Local Storage persistence.
- Dashboard metrics:
{metrics}

## Non-Goals
- Login, server database, payments, or cloud sync.
- Real shopping mall, authentication, or product database API integration.
- Fully automatic barcode or image recognition.
- Native mobile app deployment.

## Design Direction
- The first screen should feel like a dense management tool, not a landing page.
- Place four key stats at the top.
- Put search, filters, and the card grid in the main area.
- Use a right-side panel or modal for add/edit forms.
- Each card should show photo, name, brand, purchase date, price, and condition.
- Use brand badges or subtle color accents, but avoid decorative clutter.

## Screens And States
- Empty state: show a sample-data button when no {profile['item']} records exist.
- Loading state: keep it brief if Local Storage restoration needs a visible state.
- List state: card grid, search, filters, and sorting.
- Detail/Edit state: separate required fields from optional fields.
- Error state: clear validation for missing name, brand, purchase date, or price.

## Data Model
Each record should include at least:
{fields}

## Implementation Instructions
- Inspect the existing project structure first and choose the simplest compatible implementation.
- If this is a static app with no framework, create `index.html`, `style.css`, and `app.js`.
- If a framework already exists, follow the existing patterns.
- Include at least 12 sample records so the dashboard and filters are testable immediately.
- Keep statistics calculation separate from DOM rendering.
- For photos, implement image URL input or local file preview only.
- For barcode/product lookup, implement a manual SKU/product-code field and document it as a future extension instead of pretending real scanning exists.

## Automated Tests
- Write tests for pure calculation/filtering functions where the project setup allows it.
- Cover:
  - Brand count calculation.
  - Current-year spending calculation.
  - Monthly spending calculation.
  - Search and filter combinations.
  - Stored data updates after add/edit/delete.

## Manual QA Scenarios
- Confirm sample records appear and total count is correct.
- Confirm brand filters such as Nike/Jordan/Adidas work.
- Add a new {profile['item']} and confirm the card grid and metrics update immediately.
- Edit a price and confirm current-year spending changes.
- Delete a record, reload, and confirm Local Storage persistence is correct.
- Search similar names and confirm it helps avoid duplicate purchases.

## Security And Privacy
- Do not introduce API keys or secrets.
- Do not upload user photo files to a server.
- Make it clear in the UI or README that Local Storage data stays in the user's browser.

## Risks
- Users may find manual data entry annoying.
- Automatic photo/barcode recognition is outside the MVP scope.
- Rendering 100+ cards can become slow if the render path is careless.
- Spending stats can be wrong if price/date validation is weak.

## Future Extensions
{optional}

## Final Report Format
Respond in Korean with exactly these sections:
- 변경 파일
- 자동 검증 완료 항목
- 검수 필요 항목
- 위험한 항목
- 실행 방법
- 핵심 화면/동작 요약

## Korean Summary For Changwoo
- 원 요청을 복붙하지 않고 MVP, 제외 범위, 데이터 모델, 검증 기준으로 분해했다.
- 사진/바코드 같은 과장되기 쉬운 기능을 MVP와 확장 후보로 분리했다.
- Codex가 바로 구현할 수 있도록 파일, 상태, 테스트, 보고 형식을 고정했다.
"""


def run_role_task(
    client,
    role_key: str,
    role_label: str,
    role_prompt: str,
    user_prompt: str,
    request: str,
    performance: list[dict[str, str]],
    context: PipelineContext | None = None,
) -> str:
    failures = []
    for index, agent_key in enumerate(ROLE_FALLBACKS[role_key]):
        if context:
            context.check_timeout()
            if agent_key in context.absent_agents:
                failures.append(f"{AGENT_ROLES[agent_key]['name']}(이번 run에서 이미 결근 처리되어 재호출 금지)")
                continue
        agent = AGENT_ROLES[agent_key]
        provider = get_agent_provider(agent_key)
        model = get_agent_model(agent_key)
        route = f"{provider}/{model}"
        try:
            if context:
                context.add_progress(f"{role_label}: {agent['name']} 작업 시작 ({route})")
            result = ask_agent(client, agent["name"], role_prompt, user_prompt, model, provider)
            if context:
                context.add_progress(f"{role_label}: {agent['name']} 작업 완료")
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
            if context:
                context.absent_agents.add(agent_key)
                context.add_progress(f"{role_label}: {agent['name']} 결근 처리 - {failure}")
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


def contribution_score(item: dict[str, str]) -> int:
    if item["status"] == "결근":
        return 0
    if item["status"] == "비상 운영":
        return 35
    if item["status"] == "대체 성공":
        return 82
    if item["role"] == "Final Editor":
        return 92 if item["status"] == "정상 납품" else 55
    return 88


def build_hr_report(performance: list[dict[str, str]], final_route: str) -> str:
    absences = [item for item in performance if item["status"] == "결근"]
    backups = [item for item in performance if item["status"] == "대체 성공"]
    emergencies = [item for item in performance if item["status"] == "비상 운영"]
    scored = [(item, contribution_score(item)) for item in performance]
    score = round(sum(value for _, value in scored) / max(1, len(scored)))

    lines = [
        "# 인사평가 및 기여도 평가",
        "",
        f"- 회사 협업 점수: {min(score, 100)}/100",
        f"- Finalizer 라우트: {final_route}",
        f"- 결근 처리: {len(absences)}건",
        f"- 대체 투입 성공: {len(backups)}건",
        f"- 비상 운영: {len(emergencies)}건",
        "- 평가 기준: 산출물 기여도, 역할 적합성, 대체 투입 여부, 결근/비상 운영 여부",
        "",
        "## 직원별 기여도",
        "",
    ]
    for item, value in scored:
        if value >= 90:
            grade = "A"
        elif value >= 80:
            grade = "B"
        elif value >= 60:
            grade = "C"
        elif value > 0:
            grade = "D"
        else:
            grade = "F"
        lines.append(
            f"- {item['role']} / {item['agent']} / {item['route']} / {item['status']} / 기여도 {value}/100 ({grade}): {item['note']}"
        )

    lines.extend(
        [
            "",
            "## 운영 원칙",
            "",
            "- 이 회사의 목적은 빠른 답변이 아니라 초보자가 Codex/Claude Code에 넣을 좋은 프롬프트를 배우고 얻는 것이다.",
            "- 약한 로컬 모델들도 역할을 쪼개 협업하면 더 좋은 작업지시서를 만들 수 있다는 전제로 운영한다.",
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
    artifacts["files"] = format_generated_files(files)
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
        if item["path"].endswith("quality_score.json"):
            try:
                data = json.loads(item["content"])
                score = data.get("score")
                if isinstance(score, int):
                    return {"score": max(0, min(100, score)), "text": item["content"][:1200]}
            except (json.JSONDecodeError, TypeError):
                pass
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


PROMPT_COMPANY_PRINCIPLES = """
Changwoo Prompt Agency principles:
- Do not pretend to be smarter than GPT. The value is structure, role-based review, and omission prevention.
- Force-check design, UI states, file structure, tests, security, and verification criteria that AI beginners often miss.
- Produce a task brief concrete enough for Codex/Claude Code to implement a real MVP.
- The deliverable is not a casual prompt. It is a learnable implementation brief package.
- Internal agent work and Codex execution prompts should be English-first for implementation accuracy.
- User-facing logs, summaries, and final report requirements should remain Korean-friendly for Changwoo.
""".strip()


REQUIRED_CODEX_PROMPT_SECTIONS = [
    "Original Request",
    "Goal",
    "MVP Scope",
    "Non-Goals",
    "Design Direction",
    "Screens And States",
    "File Structure",
    "Implementation Instructions",
    "Automated Tests",
    "Manual QA Scenarios",
    "Security And Privacy",
    "Risks",
    "Final Report Format",
    "Korean Summary For Changwoo",
]


def required_prompt_sections_text() -> str:
    return "\n".join(f"- {section}" for section in REQUIRED_CODEX_PROMPT_SECTIONS)


def format_generated_files(files: list[dict[str, str]]) -> str:
    sections = ["# Generated Prompt Files", ""]
    for item in files:
        sections.extend(
            [
                f"## {item['path']}",
                "",
                item["content"],
                "",
            ]
        )
    return "\n".join(sections).strip()


def run_one_call_pipeline(client, request: str) -> tuple[dict[str, str], list[dict[str, str]], int, str]:
    project_type = detect_project_type(request)
    role_prompt = (
        "You are the orchestrator of Changwoo Prompt Agency. Work in English for technical prompt production. "
        "Even though this is a single API call, structure the result as if Mike PM, Mina UX, Jay implementation writer, "
        "Yuna QA, Nora scope, Dana DX, Test Kim QA automation, Jason red team, Sana security, Iris prompt editor, "
        "Vera validation, and Finalizer all contributed. Changwoo does not want you to build the app directly here; "
        "he wants a high-quality Codex prompt that can be pasted into Codex to produce a working MVP. "
        "Return only a pure JSON object. Do not use markdown code fences."
    )
    file_contract = project_file_contract(project_type)
    user_prompt = f"""
창우 사장의 요청:
{request}

판단된 project_type:
{project_type}

Codex 작업 설계 규칙:
{file_contract}

Return every JSON value in English, except the final report format inside codex_prompt.md must tell Codex to report back in Korean.

{{
  "project_type": "{project_type}",
  "brief": "Mike PM brief: goal, scope, non-goals, deliverables",
  "plan": "Codex work plan from pre-implementation success criteria to verification",
  "design": "Mina UX/design requirements: user flow, screens, states, layout, accessibility",
  "dev": "Jay technical implementation guidance: file structure, commands, behavior, tests",
  "review": "Yuna/Jason/Sana/Vera review: acceptance checklist, test plan, risks, security, score",
  "final": "Short Korean-facing summary that tells Changwoo which generated file to paste into Codex",
  "files": [
    {{"path": "generated_prompt/codex_prompt.md", "content": "Paste-ready English Codex Execution Prompt"}},
    {{"path": "generated_prompt/acceptance_checklist.md", "content": "Acceptance criteria checklist"}},
    {{"path": "generated_prompt/test_plan.md", "content": "Automated and manual test plan"}},
    {{"path": "generated_prompt/risk_notes.md", "content": "Risks and mitigations"}},
    {{"path": "generated_prompt/scope.md", "content": "MVP scope, later version, non-goals"}},
    {{"path": "generated_prompt/output_contract.md", "content": "Required Korean final report format for Codex"}},
    {{"path": "generated_prompt/security_notes.md", "content": "Security/privacy/secrets/destructive command notes"}},
    {{"path": "generated_prompt/quality_score.md", "content": "Prompt quality score with sub-scores and warnings"}}
  ]
}}

Rules:
- Do not build the app directly in this response. Deliver a prompt that instructs Codex to build it.
- codex_prompt.md must include: Goal, Success Criteria, Implementation Instructions, File Structure, Automated Tests, Manual QA Scenarios, Security/Privacy, Risks, Final Report Format.
- Success criteria must be checkboxes.
- Separate automated tests from manual QA.
- Be realistic about build failure, scope creep, platform differences, and model limitations.
- scope.md must separate MVP, later version, and non-goals.
- output_contract.md must require Codex to report in Korean with "자동 검증 완료 항목 / 검수 필요 항목 / 위험한 항목 / 변경 파일 / 실행 방법".
- security_notes.md must include API keys, .env, tokens, personal data, and destructive command cautions.
- quality_score.md must include a 100-point score, Clarity/Scope/Testability/Safety/Codex Usability sub-scores, Blocking Issues, and Warnings.
- Jason must identify failure risks without praise. Vera must mark prompts below 80 as needing revision.
- Do not write a 3-week plan, meeting schedule, or vague future roadmap. Write an executable Codex task.
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


def run_multi_agent_pipeline(
    client,
    request: str,
    context: PipelineContext | None = None,
) -> tuple[dict[str, str], list[dict[str, str]], int, str]:
    mike_role = (
        "You are Mike, the PM at Changwoo Prompt Agency. Work in English. Convert Changwoo's Korean request "
        "into requirements, implementation scope, non-goals, and acceptance criteria for a Codex build prompt. "
        "Prioritize a precise, executable task brief over a quick summary. Assume Codex should implement a real MVP."
    )
    mina_role = (
        "You are Mina, the UX/Design planner. Work in English. Define user flows, screen structure, layout, "
        "visual tone, empty/loading/error/success states, and responsive behavior. Make the design guidance concrete "
        "enough for Codex to implement, not just describe."
    )
    jay_role = (
        "You are Jay, the technical implementation writer. Work in English. Based on Mike and Mina, specify files, "
        "code structure, commands, implementation order, and test strategy. Do not say 'build the MVP' vaguely; "
        "state exactly what behavior and files make the MVP complete."
    )
    yuna_role = (
        "You are Yuna, the QA reviewer. Work in English. Find bugs, performance risks, edge cases, ambiguous requirements, "
        "and missing tests in the brief/design/dev plan. Lead with verification methods and failure cases."
    )
    nora_role = (
        "You are Nora, the scope manager. Work in English. Split the idea into MVP, later version, and explicit non-goals. "
        "Keep the MVP valuable but implementable in one Codex task."
    )
    dana_role = (
        "You are Dana, the developer experience owner. Work in English. Define setup, run commands, sample data, "
        "environment assumptions, and troubleshooting points so Changwoo can run and verify the result."
    )
    jason_role = (
        "You are Jason, the red-team reviewer. Work in English. No praise. Identify product, business, technical, "
        "legal, operational, and overclaim risks."
    )
    sana_role = (
        "You are Sana, the security and privacy reviewer. Work in English. Check API keys, .env files, user data, "
        "images, camera/barcode claims, public repository exposure, risky commands, and privacy boundaries."
    )
    iris_role = (
        "You are Iris, the prompt editor. Work in English. Remove ambiguity, clarify output format, implementation order, "
        "and final report format. Add a short Korean learning note only if useful for Changwoo."
    )
    vera_role = (
        "You are Vera, the validation judge. Work in English. Score the prompt out of 100 and list blocking issues. "
        "Check required sections, design specificity, testability, security/privacy, run instructions, and Codex usability."
    )
    final_role = (
        "You are the Final Editor. Produce the final Codex prompt primarily in English. Do not merely summarize the agents. "
        "Rewrite their work into a paste-ready instruction that can produce a working MVP. Keep implementation guidance, "
        "file structure, validation, and risk controls concrete. Include a Korean final report format so Codex reports back "
        "to Changwoo in Korean. Missing required sections is a failure."
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
    if context:
        context.add_progress("파이프라인 시작: 역할별 작업지시서 회의 준비")

    brief = run_role_task(
        client,
        "pm",
        "PM / 기획",
        mike_role,
        f"Changwoo's Korean request:\n{request}\n\nWrite in English:\n1) Requirements\n2) Implementation scope\n3) Acceptance criteria\n4) Issues Jay/Yuna must review.",
        request,
        performance,
        context,
    )
    design = run_role_task(
        client,
        "structure",
        "UX Design / 화면 설계",
        mina_role,
        f"Original request:\n{request}\n\nMike output:\n{brief}\n\n"
        "Write English UX/design instructions for the Codex prompt. Include user flow, first-screen layout, core components, "
        "visual tone, empty/loading/error/success states, desktop/mobile responsiveness, and accessibility criteria.",
        request,
        performance,
        context,
    )
    dev = run_role_task(
        client,
        "dev",
        "Dev / 구현안",
        jay_role,
        f"Original request:\n{request}\n\nMike output:\n{brief}\n\nMina output:\n{design}\n\nWrite English implementation guidance, file structure, commands, and test strategy so Codex can start coding immediately.",
        request,
        performance,
        context,
    )
    review = run_role_task(
        client,
        "qa",
        "QA / 비판",
        yuna_role,
        f"Original request:\n{request}\n\nMike:\n{brief}\n\nMina:\n{design}\n\nJay:\n{dev}\n\nReview in English. Focus on bugs, performance, edge cases, and missing verification.",
        request,
        performance,
        context,
    )
    scope = run_role_task(
        client,
        "scope",
        "Scope / 범위 관리",
        nora_role,
        f"Original request:\n{request}\n\nMike:\n{brief}\n\nMina:\n{design}\n\nJay:\n{dev}\n\nSplit the work in English into MVP, later version, and non-goals for this Codex task.",
        request,
        performance,
        context,
    )
    dx = run_role_task(
        client,
        "dx",
        "DX / 실행 경험",
        dana_role,
        f"Original request:\n{request}\n\nJay:\n{dev}\n\nYuna:\n{review}\n\nWrite English setup/run/verification guidance, sample data needs, environment assumptions, and troubleshooting points.",
        request,
        performance,
        context,
    )
    redteam = run_role_task(
        client,
        "redteam",
        "Red Team / 위험 지적",
        jason_role,
        f"Original request:\n{request}\n\nCurrent artifacts:\n{brief}\n\n{design}\n\n{dev}\n\n{review}\n\nWrite English red-team feedback. Only identify overclaims, failure modes, implementation difficulty, and business/product risks.",
        request,
        performance,
        context,
    )
    security = run_role_task(
        client,
        "security",
        "Security / 개인정보",
        sana_role,
        f"Original request:\n{request}\n\nProduct/technical draft:\n{design}\n\n{dev}\n\nWrite English security/privacy review for images, camera/barcode claims, location, credits/payments, personal data, API keys, and public deployment risks.",
        request,
        performance,
        context,
    )
    editor = run_role_task(
        client,
        "editor",
        "Prompt Editor / 문장 정리",
        iris_role,
        f"Original request:\n{request}\n\nMike:\n{brief}\n\nMina:\n{design}\n\nJay:\n{dev}\n\nNora:\n{scope}\n\nDana:\n{dx}\n\nJason:\n{redteam}\n\nSana:\n{security}\n\nWrite English prompt-editing guidance that removes ambiguity and prepares the final Codex prompt structure.",
        request,
        performance,
        context,
    )
    judge = run_role_task(
        client,
        "judge",
        "Validation / 품질 평가",
        vera_role,
        f"Original request:\n{request}\n\nRequired final prompt sections:\n{required_prompt_sections_text()}\n\n"
        f"Full review:\nMike={brief}\n\nMina={design}\n\nJay={dev}\n\nYuna={review}\n\nNora={scope}\n\nDana={dx}\n\nJason={redteam}\n\nSana={security}\n\nIris={editor}\n\n"
        "Score the prompt in English. Include blocking issues, required fixes, and pass/missing status for each required section.",
        request,
        performance,
        context,
    )
    final_prompt_input = (
        f"{PROMPT_COMPANY_PRINCIPLES}\n\n"
        f"Original request:\n{request}\n\nRequired final prompt sections:\n{required_prompt_sections_text()}\n\n"
        f"PM Mike:\n{brief}\n\nUX/Design Mina:\n{design}\n\nDev Jay:\n{dev}\n\n"
        f"QA Yuna:\n{review}\n\nScope Nora:\n{scope}\n\nDX Dana:\n{dx}\n\nRed Team Jason:\n{redteam}\n\n"
        f"Security Sana:\n{security}\n\nPrompt Editor Iris:\n{editor}\n\nValidation Vera:\n{judge}\n\n"
        "Rewrite this into one paste-ready Codex Execution Prompt in English. It must be an instruction, not a summary. "
        "Tell Codex to implement a working MVP, run available automated checks, and provide manual QA scenarios. "
        "Include design direction, screens/states, implementation instructions, tests, risks, and a Korean final report format. "
        "Add a short Korean Summary For Changwoo explaining why the prompt is strong."
    )
    if context:
        context.check_timeout()
        context.add_progress("Finalizer: 최종 Codex 프롬프트 압축 시작")
    try:
        final, final_route = ask_final_editor(client, final_role, final_prompt_input, important)
        if context:
            context.add_progress(f"Finalizer: 최종 프롬프트 납품 완료 ({final_route})")
    except Exception as exc:
        final_route = "internal/emergency-finalizer"
        if context:
            context.add_progress(f"Finalizer: 비상 납품 전환 - {role_absence_summary(exc)}")
        final = build_rule_based_codex_prompt(request)
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
        {"path": "generated_prompt/design_recommendations.md", "content": design},
        {"path": "generated_prompt/ux_structure.md", "content": design},
        {"path": "generated_prompt/implementation_plan.md", "content": dev},
        {"path": "generated_prompt/dx_runbook.md", "content": dx},
        {"path": "generated_prompt/risk_notes.md", "content": redteam},
        {"path": "generated_prompt/security_notes.md", "content": security},
        {"path": "generated_prompt/prompt_editor_notes.md", "content": editor},
        {"path": "generated_prompt/quality_score.md", "content": judge},
        {"path": "generated_prompt/why_this_prompt_works.md", "content": editor},
    ]
    parsed_score = extract_quality_score(files, {"review": artifacts["review"], "final": final}) or {}
    files.append(
        {
            "path": "generated_prompt/quality_score.json",
            "content": json.dumps(
                {
                    "score": parsed_score.get("score"),
                    "source": "Vera",
                    "route": get_agent_route("vera"),
                    "note": "score가 null이면 Vera 텍스트에서 안정적인 점수를 찾지 못한 것입니다.",
                },
                ensure_ascii=False,
                indent=2,
            ),
        }
    )
    artifacts["files"] = format_generated_files(files)
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
    installed_ollama_models = get_installed_ollama_models()
    missing_models = []
    if installed_ollama_models is not None:
        for key, route in agents.items():
            if route["provider"] == "ollama" and route["model"] not in installed_ollama_models:
                fallback = next(
                    (model for model in route.get("candidates", []) if model in installed_ollama_models),
                    "qwen3:14b 또는 llama3.1:latest",
                )
                missing_models.append({"agent": key, "model": route["model"], "fallback": fallback})
    return {
        "ok": True,
        "mode": get_pipeline_mode(),
        "missing_models": missing_models,
        "ollama_model_check": "unavailable" if installed_ollama_models is None else "checked",
        "important_markers": [
            "중요",
            "신중",
            "제대로",
            "퀄리티",
            "MVP",
            "50줄 이상",
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


def run_ai_pipeline(request: str, context: PipelineContext | None = None) -> dict:
    provider = get_provider()
    client = require_openai_client() if provider == "openai" else None
    mode = get_pipeline_mode()
    context = context or PipelineContext()
    context.add_progress("서버가 요청을 접수했습니다.")
    if mode == "multi":
        artifacts, files, calls, model_summary = run_multi_agent_pipeline(client, request, context)
    elif mode == "one_call":
        context.check_timeout()
        context.add_progress("one_call 오케스트레이터 작업 시작")
        artifacts, files, calls, model_summary = run_one_call_pipeline(client, request)
    else:
        raise RuntimeError("AI_PIPELINE_MODE는 one_call 또는 multi 여야 합니다.")

    context.check_timeout()
    context.add_progress("산출물을 outputs 폴더에 저장하는 중입니다.")
    output_dir = save_run(request, artifacts, files)
    context.add_progress("파이프라인 완료")

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
        "progress": context.snapshot(),
        "artifacts": artifacts,
    }


def start_pipeline_job(request: str, job_id: str | None = None) -> str:
    cleanup_jobs()
    if not job_id or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", job_id):
        job_id = uuid.uuid4().hex
    context = PipelineContext()
    with JOBS_LOCK:
        if job_id in JOBS:
            job_id = uuid.uuid4().hex
        if job_id in PENDING_CANCELS:
            PENDING_CANCELS.pop(job_id, None)
            context.cancel()
            JOBS[job_id] = {
                "ok": True,
                "job_id": job_id,
                "status": "canceled",
                "progress": context.snapshot(),
                "result": None,
                "error": "사용자가 작업을 취소했습니다.",
                "context": context,
                "created_monotonic": time.monotonic(),
                "started_at": datetime.now().isoformat(timespec="seconds"),
            }
            return job_id
        JOBS[job_id] = {
            "ok": True,
            "job_id": job_id,
            "status": "running",
            "progress": context.snapshot(),
            "result": None,
            "error": None,
            "context": context,
            "created_monotonic": time.monotonic(),
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }

    def worker() -> None:
        try:
            result = run_ai_pipeline(request, context)
            with JOBS_LOCK:
                current = JOBS.get(job_id)
                if current and current.get("status") == "canceled":
                    current["progress"] = context.snapshot()
                    return
                JOBS[job_id].update(
                    {
                        "status": "done",
                        "progress": context.snapshot(),
                        "result": result,
                    }
                )
        except Exception as exc:
            with JOBS_LOCK:
                current = JOBS.get(job_id)
                if current and current.get("status") == "canceled":
                    current["progress"] = context.snapshot()
                    current["error"] = str(exc)
                    return
                JOBS[job_id].update(
                    {
                        "status": "error",
                        "progress": context.snapshot(),
                        "error": str(exc),
                        "retryable": isinstance(exc, RetryableAIError),
                        "retry_after": getattr(exc, "retry_after", None),
                    }
                )

    threading.Thread(target=worker, daemon=True).start()
    return job_id


def public_job(job: dict) -> dict:
    return {key: value for key, value in job.items() if key not in ("context", "created_monotonic")}


def job_ttl_seconds() -> int:
    return int(os.getenv("JOB_TTL_SECONDS", "1800"))


def max_jobs() -> int:
    return int(os.getenv("MAX_JOBS", "20"))


def cleanup_jobs() -> None:
    now = time.monotonic()
    ttl_seconds = job_ttl_seconds()
    max_job_count = max_jobs()
    with JOBS_LOCK:
        for job_id, created_at in list(PENDING_CANCELS.items()):
            if now - created_at > ttl_seconds:
                PENDING_CANCELS.pop(job_id, None)
        expired = [
            job_id
            for job_id, job in JOBS.items()
            if job.get("status") != "running" and now - float(job.get("created_monotonic", now)) > ttl_seconds
        ]
        for job_id in expired:
            JOBS.pop(job_id, None)
        overflow = max(0, len(JOBS) - max_job_count)
        if overflow:
            sorted_jobs = sorted(JOBS.items(), key=lambda item: float(item[1].get("created_monotonic", now)))
            for job_id, job in sorted_jobs:
                if overflow <= 0:
                    break
                if job.get("status") == "running":
                    continue
                JOBS.pop(job_id, None)
                overflow -= 1


def cancel_pipeline_job(job_id: str) -> dict:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            if re.fullmatch(r"[A-Za-z0-9_-]{8,80}", job_id):
                PENDING_CANCELS[job_id] = time.monotonic()
                return {"ok": True, "job_id": job_id, "status": "canceled", "error": "작업 시작 전 취소 요청을 기록했습니다."}
            return {"ok": False, "error": "작업을 찾을 수 없습니다."}
        if job.get("status") in ("done", "error", "canceled"):
            return public_job(job)
        context = job.get("context")
        if isinstance(context, PipelineContext):
            context.cancel()
            job["progress"] = context.snapshot()
        job["status"] = "canceled"
        job["error"] = "사용자가 작업을 취소했습니다."
        return public_job(job)


def get_pipeline_job(job_id: str) -> dict:
    cleanup_jobs()
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return {"ok": False, "error": "작업을 찾을 수 없습니다."}
        context = job.get("context")
        if isinstance(context, PipelineContext):
            job["progress"] = context.snapshot()
        return public_job(job)


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
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/agent-config":
            try:
                self.send_json(200, get_agent_config())
            except Exception as exc:
                traceback.print_exc()
                self.send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/api/run-status":
            job_id = parse_qs(parsed.query).get("job_id", [""])[0]
            payload = get_pipeline_job(job_id)
            self.send_json(200 if payload.get("ok") else 404, payload)
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
        if path not in ("/api/run", "/api/run-job", "/api/cancel-job", "/api/agent-chat", "/api/review-artifact", "/api/rework"):
            self.send_json(404, {"ok": False, "error": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if path == "/api/cancel-job":
                job_id = str(payload.get("job_id", "")).strip()
                result = cancel_pipeline_job(job_id)
                self.send_json(200 if result.get("ok") else 404, result)
                return
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
                if not original_request or not result_text:  # FIX: PY-1
                    self.send_json(400, {"ok": False, "error": "original_request와 result를 모두 입력해주세요."})  # FIX: PY-1
                    return  # FIX: PY-1
                result = run_rework_pipeline(original_request, result_text, extra_context)
                self.send_json(200, result)
                return

            request = str(payload.get("request", "")).strip()
            if not request:
                self.send_json(400, {"ok": False, "error": "요청 내용을 입력해주세요."})
                return

            if path == "/api/run-job":
                client_job_id = str(payload.get("job_id", "")).strip()
                job_id = start_pipeline_job(request, client_job_id)
                self.send_json(202, {"ok": True, "job_id": job_id})
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
