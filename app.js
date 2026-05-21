const stages = [
  {
    key: "brief",
    label: "Brief Builder",
    file: "brief.json",
    delay: 900,
    run: (request) => ({
      goal: "온라인 강의 런칭을 위한 마케팅 산출물 생성",
      audience: "1인 창업을 준비하는 직장인",
      tone: "실용적이고 신뢰감 있는 톤",
      deliverables: ["랜딩페이지 카피", "SNS 홍보 문구"],
      constraints: ["과장된 표현보다 구체적인 가치 제안 중심"],
      source_request: request,
    }),
  },
  {
    key: "plan",
    label: "Planner",
    file: "plan.json",
    delay: 900,
    run: () => ({
      steps: [
        "핵심 문제와 욕구를 정리한다",
        "랜딩페이지 섹션 구조를 만든다",
        "각 섹션의 메시지를 작성한다",
        "SNS용 짧은 문구로 재가공한다",
        "검토 기준에 맞춰 수정한다",
      ],
      quality_bar: ["타깃이 명확해야 함", "행동 유도가 있어야 함", "표현이 구체적이어야 함"],
    }),
  },
  {
    key: "draft",
    label: "Generator",
    file: "draft.md",
    delay: 1100,
    run: () =>
      [
        "# 랜딩페이지 초안",
        "",
        "## 헤드라인",
        "퇴근 후 2시간, 내 사업의 첫 판매 구조를 만드세요.",
        "",
        "## 서브카피",
        "아이디어는 있지만 어디서부터 시작해야 할지 막막한 직장인을 위해, 시장 검증부터 첫 상품 구성까지 실전 순서로 안내합니다.",
        "",
        "## SNS 문구",
        "창업 준비가 막연하다면, 먼저 판매 구조부터 작게 만들어보세요. 이번 강의는 직장인이 현실적으로 실행할 수 있는 첫 사업 설계법을 다룹니다.",
      ].join("\n"),
  },
  {
    key: "review",
    label: "Reviewer",
    file: "review.md",
    delay: 850,
    run: () =>
      [
        "# Review Notes",
        "",
        "- 타깃은 명확함",
        "- 랜딩페이지 초안에 CTA가 부족함",
        "- SNS 문구는 더 짧은 버전이 있으면 좋음",
        "- 결과물의 신뢰감을 높이려면 구체적인 학습 결과를 추가해야 함",
      ].join("\n"),
  },
  {
    key: "final",
    label: "Finalizer",
    file: "final.md",
    delay: 900,
    run: () =>
      [
        "# 최종 결과물",
        "",
        "## 랜딩페이지 핵심 카피",
        "",
        "퇴근 후 2시간, 내 사업의 첫 판매 구조를 만드세요.",
        "",
        "아이디어만 붙잡고 있는 시간을 줄이고, 고객 문제 정의, 상품 구성, 첫 제안문 작성까지 실행 가능한 순서로 완성합니다.",
        "",
        "## CTA",
        "",
        "지금 강의 커리큘럼 확인하기",
        "",
        "## SNS 짧은 문구",
        "",
        "창업을 크게 시작할 필요는 없습니다. 먼저 팔릴 수 있는 구조를 작게 설계하세요.",
      ].join("\n"),
  },
];

const els = {
  request: document.querySelector("#clientRequest"),
  runButton: document.querySelector("#runButton"),
  resetButton: document.querySelector("#resetButton"),
  runStatus: document.querySelector("#runStatus"),
  artifactOutput: document.querySelector("#artifactOutput"),
  artifactName: document.querySelector("#artifactName"),
  activityLog: document.querySelector("#activityLog"),
  elapsedTime: document.querySelector("#elapsedTime"),
  tabs: Array.from(document.querySelectorAll(".tab")),
  cards: Array.from(document.querySelectorAll(".stage-card")),
};

let artifacts = {};
let activeArtifact = "request";
let timerId = null;
let startedAt = 0;

function formatArtifact(value) {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function setArtifact(name) {
  activeArtifact = name;
  const stage = stages.find((item) => item.key === name);
  els.artifactName.textContent = name === "request" ? "request.md" : stage.file;
  els.artifactOutput.textContent = formatArtifact(artifacts[name] || "아직 생성되지 않았습니다.");

  els.tabs.forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.artifact === name);
  });
}

function setStatus(text, className = "") {
  els.runStatus.textContent = text;
  els.runStatus.className = `run-status ${className}`.trim();
}

function addLog(text) {
  const item = document.createElement("li");
  item.textContent = text;
  els.activityLog.append(item);
}

function setStageState(key, state) {
  const card = els.cards.find((item) => item.dataset.stage === key);
  if (!card) return;

  card.classList.toggle("active", state === "active");
  card.classList.toggle("done", state === "done");
  card.querySelector(".stage-state").textContent =
    state === "active" ? "Running" : state === "done" ? "Done" : "Waiting";
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function resetPipeline() {
  artifacts = {
    request: els.request.value.trim(),
  };
  els.activityLog.innerHTML = "";
  els.cards.forEach((card) => setStageState(card.dataset.stage, "waiting"));
  setStatus("Idle");
  window.clearInterval(timerId);
  els.elapsedTime.textContent = "0.0s";
  setArtifact("request");
}

async function runPipeline() {
  resetPipeline();
  els.runButton.disabled = true;
  setStatus("Running", "running");
  startedAt = performance.now();
  timerId = window.setInterval(() => {
    const elapsed = (performance.now() - startedAt) / 1000;
    els.elapsedTime.textContent = `${elapsed.toFixed(1)}s`;
  }, 100);

  for (const stage of stages) {
    setStageState(stage.key, "active");
    addLog(`${stage.label} started`);
    await sleep(stage.delay);
    artifacts[stage.key] = stage.run(artifacts.request, artifacts);
    setStageState(stage.key, "done");
    addLog(`${stage.file} created`);
    setArtifact(stage.key);
  }

  window.clearInterval(timerId);
  const elapsed = (performance.now() - startedAt) / 1000;
  els.elapsedTime.textContent = `${elapsed.toFixed(1)}s`;
  setStatus("Done", "done");
  els.runButton.disabled = false;
}

els.tabs.forEach((tab) => {
  tab.addEventListener("click", () => setArtifact(tab.dataset.artifact));
});

els.runButton.addEventListener("click", runPipeline);
els.resetButton.addEventListener("click", resetPipeline);
els.request.addEventListener("input", () => {
  artifacts.request = els.request.value.trim();
  if (activeArtifact === "request") setArtifact("request");
});

resetPipeline();
