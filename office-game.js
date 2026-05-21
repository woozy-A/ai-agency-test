const positions = {
  changwoo: { home: [16, 30], meeting: [46, 58], delivery: [82, 78] },
  mike: { home: [47, 30], boss: [23, 31], meeting: [52, 58], design: [69, 34], dev: [31, 72], review: [67, 73], delivery: [78, 75] },
  mina: { home: [78, 34], meeting: [58, 56], work: [78, 34], delivery: [84, 73] },
  jay: { home: [28, 74], meeting: [49, 68], work: [28, 74], delivery: [73, 78] },
  yuna: { home: [67, 75], meeting: [58, 68], work: [67, 75], delivery: [88, 68] },
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
  await sleep(840);
  agent.classList.remove("walking");
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

async function runBackendPipeline(request) {
  const response = await fetch("/api/run", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ request }),
  });
  const payload = await response.json();
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
        goal: "요청을 실행 가능한 업무 brief로 바꾸기",
        request: topic,
        team: ["Mina: 화면/메시지 구조", "Jay: 구현/자동화", "Yuna: 검토"],
      },
      null,
      2
    ),
    plan: [
      "# Mike's Plan",
      "",
      "1. 창우의 요청을 brief로 정리한다.",
      "2. 화면에 필요한 기능을 최소 단위로 나눈다.",
      "3. Mina는 입력창, 목록, 완료 상태, 카운터 구조를 잡는다.",
      "4. Jay는 HTML/CSS/JS 단일 파일 구현 방향을 만든다.",
      "5. Yuna가 기본 사용 흐름과 예외 상황을 검토한다.",
    ].join("\n"),
    design: [
      "# Mina's Design Notes",
      "",
      "- 상단에는 할 일 입력창과 추가 버튼을 둔다.",
      "- 중앙에는 체크 가능한 할 일 목록을 둔다.",
      "- 하단에는 남은 할 일 개수와 전체 삭제 버튼을 둔다.",
      "- 완료된 항목은 취소선과 옅은 색으로 구분한다.",
    ].join("\n"),
    dev: [
      "# Jay's Build Notes",
      "",
      "- `todo.html` 하나로 HTML/CSS/JS를 넣어 시작할 수 있다.",
      "- `todos` 배열에 `{ id, text, done }` 형태로 상태를 저장한다.",
      "- 추가, 체크 토글, 삭제 함수만 먼저 구현한다.",
      "- 나중에 `localStorage` 저장을 붙이면 새로고침 후에도 유지된다.",
    ].join("\n"),
    review: [
      "# Yuna's Review",
      "",
      "- 역할 흐름은 이해하기 쉽다.",
      "- 실제 실행판에서는 API 키와 백엔드가 필요하다.",
      "- 산출물 저장 위치를 화면에 보여주면 좋다.",
    ].join("\n"),
    final: [
      "# Final Delivery",
      "",
      `요청: ${request}`,
      "",
      "투두리스트 앱 최소 기능:",
      "- 할 일 추가",
      "- 완료 체크",
      "- 삭제",
      "- 남은 개수 표시",
      "",
      "로컬 실행판:",
      "`python3 server.py`로 열면 실제 AI가 한 번의 호출로 Mike/Mina/Jay/Yuna/Final 결과를 만든다.",
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
  addLog("창우가 새 업무 지시서를 올렸습니다.");
  await say("changwoo", "Mike, 이거 맡아서 굴려줘.", 1100);

  await moveAgent("mike", positions.mike.boss, "PM Mike is receiving the request");
  await say("mike", "네. 실제 AI 팀을 호출할게요.", 1200);
  setTask("Running", "AI agents are working on the request");
  if (shouldUseBackend()) {
    try {
      backendResult = await runBackendPipeline(request);
      pendingArtifacts = backendResult.artifacts;
      addLog(`AI pipeline completed with ${backendResult.provider}/${backendResult.model}`);
      addLog(`실제 API 호출 수: ${backendResult.calls || 1}`);
      addLog(`결과 저장 위치: ${backendResult.output_dir}`);
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
  addLog("Mike가 요청을 brief로 정리했습니다.");
  showPaper("brief");
  await moveAgent("mike", positions.mike.home, "Mike is planning");
  await say("mike", "디자인이랑 개발 같이 봐야겠네.", 1000);
  artifacts.plan = pendingArtifacts.plan;
  addLog("Mike가 실행 계획을 만들었습니다.");

  await Promise.all([
    moveAgent("mike", positions.mike.meeting, "Mike is calling a meeting"),
    moveAgent("mina", positions.mina.meeting, "Mina is joining the meeting"),
    moveAgent("jay", positions.jay.meeting, "Jay is joining the meeting"),
  ]);
  await say("mike", "Mina는 화면 구조, Jay는 자동화 흐름 맡아줘.", 1300);
  addLog("Mike, Mina, Jay가 짧은 회의를 마쳤습니다.");

  await Promise.all([
    moveAgent("mina", positions.mina.work, "Mina is designing"),
    moveAgent("jay", positions.jay.work, "Jay is building"),
    moveAgent("mike", positions.mike.home, "Mike is tracking progress"),
  ]);
  await Promise.all([say("mina", "사용자가 흐름을 보게 만들게요.", 1000), say("jay", "단계별 산출물도 남기겠습니다.", 1000)]);
  artifacts.design = pendingArtifacts.design;
  addLog("Mina가 design artifact를 만들었습니다.");
  artifacts.dev = pendingArtifacts.dev;
  addLog("Jay가 dev artifact를 만들었습니다.");
  showPaper("draft");

  await Promise.all([
    moveAgent("mike", positions.mike.review, "Mike is requesting review"),
    moveAgent("yuna", positions.yuna.work, "Yuna is reviewing"),
  ]);
  await say("yuna", "역할과 결과물이 이어지는지 볼게요.", 1200);
  addLog("Yuna가 결과물을 검토했습니다.");

  await Promise.all([
    moveAgent("mike", positions.mike.delivery, "Team is preparing delivery"),
    moveAgent("mina", positions.mina.delivery, "Team is preparing delivery"),
    moveAgent("jay", positions.jay.delivery, "Team is preparing delivery"),
    moveAgent("yuna", positions.yuna.delivery, "Team is preparing delivery"),
    moveAgent("changwoo", positions.changwoo.delivery, "Changwoo is checking final delivery"),
  ]);
  artifacts.final = pendingArtifacts.final;
  showPaper("final");
  els.deliveryBox.classList.add("complete");
  await say("mike", "최종본 준비됐습니다.", 1000);
  addLog("최종 산출물이 납품 박스에 도착했습니다.");

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
