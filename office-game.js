const positions = {
  changwoo: { home: [16, 30], meeting: [46, 58], delivery: [82, 78] },
  mike: { home: [47, 30], boss: [23, 31], meeting: [52, 58], design: [69, 34], dev: [31, 72], review: [67, 73], delivery: [78, 75] },
  mina: { home: [78, 34], meeting: [58, 56], mike: [55, 42], work: [78, 34], delivery: [84, 73] },
  jay: { home: [28, 74], meeting: [49, 68], mike: [49, 45], work: [28, 74], delivery: [73, 78] },
  yuna: { home: [67, 75], meeting: [58, 68], work: [67, 75], delivery: [88, 68] },
  hallway: {
    boss: [30, 42],
    center: [52, 45],
    lower: [52, 70],
    delivery: [74, 70],
  },
};

const agentLabels = {
  changwoo: "창우",
  mike: "Mike",
  mina: "Mina",
  jay: "Jay",
  yuna: "Yuna",
};

const els = {
  requestInput: document.querySelector("#requestInput"),
  startButton: document.querySelector("#startButton"),
  resetButton: document.querySelector("#resetButton"),
  statusText: document.querySelector("#statusText"),
  taskText: document.querySelector("#taskText"),
  artifactOutput: document.querySelector("#artifactOutput"),
  artifactCount: document.querySelector("#artifactCount"),
  deliveryBox: document.querySelector("#deliveryBox"),
  tabs: Array.from(document.querySelectorAll(".artifact-tab")),
  papers: {
    request: document.querySelector("#requestPaper"),
    brief: document.querySelector("#briefPaper"),
    draft: document.querySelector("#draftPaper"),
    final: document.querySelector("#finalPaper"),
  },
  agents: Object.fromEntries(
    Array.from(document.querySelectorAll(".agent")).map((agent) => [agent.dataset.agent, agent])
  ),
  cards: Object.fromEntries(
    Array.from(document.querySelectorAll(".team-member")).map((card) => [card.dataset.agentCard, card])
  ),
};

let artifacts = {};
let pendingArtifacts = {};
let logs = [];
let activeArtifact = "log";
let running = false;

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function setAgentPosition(agentKey, point) {
  const agent = els.agents[agentKey];
  agent.style.setProperty("--x", point[0]);
  agent.style.setProperty("--y", point[1]);
}

function setActiveAgent(agentKey) {
  Object.values(els.cards).forEach((card) => card.classList.remove("active"));
  if (agentKey) els.cards[agentKey].classList.add("active");
}

function setTask(status, task) {
  els.statusText.textContent = status;
  els.taskText.textContent = task;
}

function showSpeech(agentKey, text) {
  const speech = els.agents[agentKey].querySelector(".speech");
  speech.textContent = text;
  speech.classList.add("show");
}

function hideSpeech(agentKey) {
  els.agents[agentKey].querySelector(".speech").classList.remove("show");
}

function hideAllSpeech() {
  Object.keys(els.agents).forEach(hideSpeech);
}

async function moveAgent(agentKey, point, taskText) {
  const agent = els.agents[agentKey];
  setActiveAgent(agentKey);
  if (taskText) setTask("Running", taskText);
  agent.classList.add("walking");
  setAgentPosition(agentKey, point);
  await sleep(680);
  agent.classList.remove("walking");
}

async function moveAgentPath(agentKey, points, taskText) {
  for (const [index, point] of points.entries()) {
    await moveAgent(agentKey, point, index === 0 ? taskText : "");
  }
}

async function say(agentKey, text, ms = 1000) {
  showSpeech(agentKey, text);
  await sleep(ms);
  hideSpeech(agentKey);
}

function addLog(text) {
  logs.push(`${String(logs.length + 1).padStart(2, "0")}. ${text}`);
  artifacts.log = logs.join("\n");
  updateArtifactCount();
  if (activeArtifact === "log") renderArtifact();
}

async function runBackendPipeline(request, attempt = 0) {
  const response = await fetch("/api/run", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ request }),
  });
  const payload = await response.json();
  if (!response.ok && payload.retryable && attempt < 2) {
    const retryAfter = Math.min(Number(payload.retry_after || 60), 300);
    addLog(`일시 오류. ${retryAfter}초 후 자동 재시도합니다. (${attempt + 1}/2)`);
    setTask("Retrying", `Waiting ${retryAfter}s before retry`);
    await sleep(retryAfter * 1000);
    return runBackendPipeline(request, attempt + 1);
  }
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || "AI pipeline request failed");
  }
  return payload;
}

function createSimulationArtifacts(request) {
  const topic = request.split(".")[0].trim() || request.trim();
  return {
    brief: JSON.stringify(
      {
        owner: "Mike",
        mode: "GitHub Pages simulation",
        goal: "Codex에 넣을 고품질 작업 프롬프트로 바꾸기",
        request: topic,
        team: ["Mina: UX 요구사항", "Jay: 기술 지시", "Yuna: 검증 기준"],
      },
      null,
      2
    ),
    plan: [
      "# Mike's Plan",
      "",
      "1. 창우의 과제를 목표/범위/산출물로 정리한다.",
      "2. Codex가 헷갈리지 않도록 성공 기준을 체크리스트로 만든다.",
      "3. Mina는 UX와 화면 요구사항을 쓴다.",
      "4. Jay는 파일 구조와 구현 지시를 쓴다.",
      "5. Yuna는 테스트 계획과 위험 요소를 검토한다.",
    ].join("\n"),
    design: [
      "# Mina's Design Notes",
      "",
      "- 사용자가 직접 확인할 핵심 화면만 명시한다.",
      "- 화면별 상태, 빈 상태, 에러 상태를 요구사항에 포함한다.",
      "- 시각적 디테일보다 검증 가능한 UX 기준을 우선한다.",
    ].join("\n"),
    dev: [
      "# Jay's Build Notes",
      "",
      "- Codex에게 만들 파일 목록을 명확히 준다.",
      "- 구현 전 성공 기준을 먼저 쓰게 한다.",
      "- 가능한 자동 테스트와 빌드 검증 명령을 포함한다.",
      "- 결과 보고 형식을 고정한다.",
    ].join("\n"),
    review: [
      "# Yuna's Review",
      "",
      "- 성공 기준이 검증 가능해야 한다.",
      "- 자동 검증/수동 검수/위험 항목을 구분해야 한다.",
      "- Codex가 임의로 다음 기능으로 넘어가지 않게 제한해야 한다.",
    ].join("\n"),
    final: [
      "# Final Delivery",
      "",
      `요청: ${request}`,
      "",
      "납품물:",
      "- codex_prompt.md",
      "- acceptance_checklist.md",
      "- test_plan.md",
      "- risk_notes.md",
      "",
      "로컬 실행판:",
      "`python3 server.py`로 열면 실제 AI가 Codex용 프롬프트 패키지를 만든다.",
    ].join("\n"),
  };
}

function shouldUseBackend() {
  return ["localhost", "127.0.0.1"].includes(window.location.hostname);
}

function updateArtifactCount() {
  const created = ["log", "brief", "plan", "design", "dev", "final"].filter((key) => {
    if (key === "log") return logs.length > 0;
    return Boolean(artifacts[key]);
  }).length;
  els.artifactCount.textContent = `${created}/6`;
}

function renderArtifact() {
  els.artifactOutput.textContent = artifacts[activeArtifact] || "아직 생성되지 않았습니다.";
  els.tabs.forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.artifact === activeArtifact);
  });
}

function showPaper(key) {
  if (els.papers[key]) els.papers[key].classList.add("visible");
}

function resetOffice() {
  running = false;
  artifacts = {};
  pendingArtifacts = {};
  logs = [];
  activeArtifact = "log";
  Object.entries(positions).forEach(([agentKey, points]) => setAgentPosition(agentKey, points.home));
  Object.values(els.papers).forEach((paper) => paper.classList.remove("visible"));
  els.deliveryBox.classList.remove("complete");
  hideAllSpeech();
  setActiveAgent(null);
  setTask("Idle", "Waiting for request");
  updateArtifactCount();
  renderArtifact();
  els.startButton.disabled = false;
}

async function runOffice() {
  if (running) return;
  running = true;
  els.startButton.disabled = true;
  logs = [];
  artifacts = { log: "" };
  pendingArtifacts = {};
  renderArtifact();
  Object.values(els.papers).forEach((paper) => paper.classList.remove("visible"));
  els.deliveryBox.classList.remove("complete");

  const request = els.requestInput.value.trim();
  let backendResult;

  showPaper("request");
  addLog("창우가 새 과제를 올렸습니다.");
  await say("changwoo", "Mike, Codex에 넣을 작업지시서로 뽑아줘.", 1400);

  await moveAgentPath("mike", [positions.hallway.center, positions.hallway.boss, positions.mike.boss], "Mike is receiving the request");
  await say("mike", "접수했습니다. 프롬프트 기준부터 잡을게요.", 1200);
  setTask("Running", "Prompt team is shaping the request");
  if (shouldUseBackend()) {
    try {
      backendResult = await runBackendPipeline(request);
      pendingArtifacts = backendResult.artifacts;
      addLog(`AI pipeline completed with ${backendResult.provider}/${backendResult.mode || "one_call"}`);
      if (backendResult.project_type) {
        addLog(`프로젝트 타입: ${backendResult.project_type}`);
      }
      addLog(`모델: ${backendResult.model}`);
      addLog(`실제 API 호출 수: ${backendResult.calls || 1}`);
      addLog(`결과 저장 위치: ${backendResult.output_dir}`);
      if (backendResult.files && backendResult.files.length) {
        addLog(`생성 프롬프트: ${backendResult.files.join(", ")}`);
      }
    } catch (error) {
      artifacts.log = logs.concat([`ERROR. ${error.message}`]).join("\n");
      activeArtifact = "log";
      renderArtifact();
      setTask("Error", "Backend setup needs attention");
      await say("mike", "백엔드 설정을 먼저 확인해야 해요.", 1400);
      running = false;
      els.startButton.disabled = false;
      return;
    }
  } else {
    pendingArtifacts = createSimulationArtifacts(request);
    addLog("공개 링크에서는 시뮬레이션 모드로 실행됩니다.");
  }
  artifacts.brief = pendingArtifacts.brief;
  addLog("Mike가 과제를 brief로 정리했습니다.");
  showPaper("brief");
  await say("mike", "목표, 범위, 제외 범위 정리 완료.", 1000);
  await moveAgentPath("mike", [positions.hallway.boss, positions.hallway.center, positions.mike.home], "Mike is planning");
  await say("mike", "Mina, Jay. Codex 지시서 같이 다듬죠.", 1200);
  artifacts.plan = pendingArtifacts.plan;
  addLog("Mike가 실행 계획을 만들었습니다.");

  await Promise.all([
    moveAgentPath("mike", [positions.hallway.center, positions.mike.meeting], "Mike is calling a meeting"),
    moveAgentPath("mina", [positions.mina.mike, positions.mina.meeting], "Mina is joining the meeting"),
    moveAgentPath("jay", [positions.jay.mike, positions.jay.meeting], "Jay is joining the meeting"),
  ]);
  await say("mike", "Mina는 UX 기준, Jay는 구현 지시를 맡아줘.", 1400);
  await Promise.all([say("mina", "검수 가능한 화면 기준으로 쓸게요.", 1100), say("jay", "Codex가 바로 실행할 명령으로 정리합니다.", 1100)]);
  addLog("Mike, Mina, Jay가 짧은 회의를 마쳤습니다.");

  await Promise.all([
    moveAgentPath("mina", [positions.mina.mike, positions.mina.work], "Mina is designing"),
    moveAgentPath("jay", [positions.hallway.lower, positions.jay.work], "Jay is building"),
    moveAgentPath("mike", [positions.hallway.center, positions.mike.home], "Mike is tracking progress"),
  ]);
  await Promise.all([say("mina", "핵심 화면과 상태 기준을 정리했어요.", 1200), say("jay", "파일 구조와 테스트 명령을 넣었습니다.", 1200)]);
  artifacts.design = pendingArtifacts.design;
  addLog("Mina가 design artifact를 만들었습니다.");
  artifacts.dev = pendingArtifacts.dev;
  addLog("Jay가 dev artifact를 만들었습니다.");
  showPaper("draft");

  await Promise.all([
    moveAgentPath("mike", [positions.hallway.center, positions.mike.review], "Mike is requesting review"),
    moveAgentPath("yuna", [positions.yuna.meeting, positions.yuna.work], "Yuna is reviewing"),
  ]);
  await say("mike", "Yuna, 검증 가능한 프롬프트인지 봐주세요.", 1200);
  await say("yuna", "체크리스트, 테스트, 위험 항목을 나눠볼게요.", 1300);
  addLog("Yuna가 프롬프트 패키지를 검토했습니다.");

  await Promise.all([
    moveAgentPath("mike", [positions.hallway.delivery, positions.mike.delivery], "Team is preparing delivery"),
    moveAgentPath("mina", [positions.hallway.delivery, positions.mina.delivery], "Team is preparing delivery"),
    moveAgentPath("jay", [positions.hallway.delivery, positions.jay.delivery], "Team is preparing delivery"),
    moveAgentPath("yuna", [positions.hallway.delivery, positions.yuna.delivery], "Team is preparing delivery"),
    moveAgentPath("changwoo", [positions.hallway.center, positions.hallway.delivery, positions.changwoo.delivery], "Changwoo is checking final delivery"),
  ]);
  artifacts.final = pendingArtifacts.final;
  showPaper("final");
  els.deliveryBox.classList.add("complete");
  await say("mike", "Codex용 최종 프롬프트 준비됐습니다.", 1200);
  await say("changwoo", "좋아. 이걸 Codex에 넣어볼게.", 1100);
  addLog("프롬프트 패키지가 납품 박스에 도착했습니다.");

  activeArtifact = "final";
  renderArtifact();
  setTask("Done", "Final delivery is ready");
  setActiveAgent(null);
  running = false;
  els.startButton.disabled = false;
}

els.tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    activeArtifact = tab.dataset.artifact;
    renderArtifact();
  });
});

els.startButton.addEventListener("click", runOffice);
els.resetButton.addEventListener("click", resetOffice);

resetOffice();
