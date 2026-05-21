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

function createArtifacts(request) {
  const topic = request.split(".")[0].trim() || request.trim();
  return {
    brief: JSON.stringify(
      {
        owner: "Mike",
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
      "2. 디자이너 Mina와 개발자 Jay를 불러 산출물 방향을 맞춘다.",
      "3. Mina는 고객이 보는 구조를 만든다.",
      "4. Jay는 자동화 실행 흐름과 결과 저장을 만든다.",
      "5. Yuna가 품질 기준으로 검토한다.",
    ].join("\n"),
    design: [
      "# Mina's Design Notes",
      "",
      "- 첫 화면에서 핵심 제안을 바로 보여준다.",
      "- 요청, 초안, 검토, 최종본을 탭으로 분리한다.",
      "- 사장/PM/실무자 역할이 눈에 보이게 배치한다.",
    ].join("\n"),
    dev: [
      "# Jay's Build Notes",
      "",
      "- 입력값을 request artifact로 저장한다.",
      "- 각 agent step을 순서대로 실행한다.",
      "- 나중에 이 step들을 실제 AI API 호출로 바꿀 수 있게 분리한다.",
    ].join("\n"),
    final: [
      "# Final Delivery",
      "",
      `요청: ${request}`,
      "",
      "완성된 흐름:",
      "창우 지시 -> Mike 기획 -> Mina 디자인 -> Jay 구현 -> Yuna 검토 -> 납품",
      "",
      "다음 확장 지점:",
      "- Mike를 실제 planning prompt로 교체",
      "- Mina를 design/content prompt로 교체",
      "- Jay를 코드 생성 또는 자동화 실행 agent로 교체",
      "- Yuna를 reviewer prompt로 교체",
    ].join("\n"),
  };
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
  pendingArtifacts = createArtifacts(request);

  showPaper("request");
  addLog("창우가 새 업무 지시서를 올렸습니다.");
  await say("changwoo", "Mike, 이거 맡아서 굴려줘.", 1100);

  await moveAgent("mike", positions.mike.boss, "PM Mike is receiving the request");
  await say("mike", "네. 목표랑 산출물부터 쪼개볼게요.", 1200);
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
