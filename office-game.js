const positions = {
  changwoo: { home: [14, 20], meeting: [46, 50], delivery: [73, 81] },
  mike: { home: [38, 20], boss: [22, 20], meeting: [48, 50], design: [73, 24], dev: [24, 67], review: [64, 69], delivery: [76, 75] },
  mina: { home: [83, 22], meeting: [53, 50], mike: [54, 38], work: [83, 22], delivery: [81, 75] },
  jay: { home: [16, 70], meeting: [45, 58], mike: [47, 39], work: [16, 70], delivery: [71, 75] },
  yuna: { home: [61, 72], meeting: [54, 58], work: [61, 72], delivery: [86, 72] },
  nora: { home: [45, 20], meeting: [43, 55], review: [59, 70], delivery: [78, 68] },
  dana: { home: [32, 80], meeting: [47, 58], review: [66, 70], delivery: [70, 82] },
  testkim: { home: [75, 70], meeting: [55, 60], review: [72, 70], delivery: [88, 82] },
  jason: { home: [86, 70], meeting: [59, 60], review: [80, 70], delivery: [91, 73] },
  sana: { home: [88, 82], meeting: [62, 58], review: [88, 66], delivery: [89, 62] },
  iris: { home: [59, 20], meeting: [50, 45], review: [68, 82], delivery: [76, 86] },
  vera: { home: [67, 20], meeting: [54, 45], review: [62, 82], delivery: [82, 86] },
  hallway: {
    boss: [27, 34],
    center: [52, 39],
    lower: [52, 64],
    delivery: [75, 67],
  },
};

const agentLabels = {
  changwoo: "창우",
  mike: "Mike",
  mina: "Mina",
  jay: "Jay",
  yuna: "Yuna",
  nora: "Nora",
  dana: "Dana",
  testkim: "Test Kim",
  jason: "Jason",
  sana: "Sana",
  iris: "Iris",
  vera: "Vera",
};

const agentRoles = {
  changwoo: "Boss",
  mike: "PM",
  mina: "UX Planner",
  jay: "Tech Writer",
  yuna: "QA Reviewer",
  nora: "Scope Manager",
  dana: "Developer Experience",
  testkim: "QA Engineer",
  jason: "Red Team",
  sana: "Security",
  iris: "Prompt Editor",
  vera: "Validation Judge",
};

const simulationAnswers = {
  changwoo: "나는 최종 의사결정자 역할이야. 지금 봐야 할 건 재미보다도 이 도구가 Codex에 넣을 좋은 프롬프트를 안정적으로 뽑는지야.",
  mike: "PM은 요청을 목표, 범위, 산출물, 우선순위로 바꾸는 역할입니다. Codex가 어디까지 해야 하는지 먼저 정리합니다.",
  mina: "UX는 사용자가 실제로 보게 될 흐름과 화면 상태를 정리합니다. 빈 상태, 오류 상태, 확인해야 할 핵심 화면을 놓치지 않게 합니다.",
  jay: "제 역할은 Codex가 바로 실행할 수 있게 파일 구조, 구현 순서, 명령어, 테스트 지시를 구체화하는 것입니다.",
  yuna: "QA는 결과가 맞는지 증명하는 역할입니다. 자동 검증 완료 항목, 직접 검수할 항목, 위험한 항목을 분리합니다.",
  nora: "Scope는 일을 줄이는 역할입니다. 이번에 할 것과 하지 않을 것을 나눠서 Codex가 쓸데없이 커지지 않게 막습니다.",
  dana: "DX는 개발자 경험 담당입니다. 실행 방법, 환경 전제, 오류 메시지, 재현 가능한 명령어를 쉽게 만드는 역할입니다.",
  testkim: "QA Engineer는 자동화 가능한 검증을 담당합니다. 테스트 명령, 실패 조건, 수동 검수 시나리오를 구분합니다.",
  jason: "Red Team은 위험만 봅니다. 요구사항이 모호한 곳, 실패할 가능성, 결과물이 허접해질 지점을 먼저 지적합니다.",
  sana: "Security는 API 키, .env, 개인정보, 위험 명령을 봅니다. 공개 저장소에 비밀값이 올라가지 않게 막는 역할입니다.",
  iris: "Prompt Editor는 문장을 다듬습니다. Codex가 오해할 표현을 줄이고, 산출물 형식과 보고 방식을 명확하게 만듭니다.",
  vera: "Validation Judge는 점수를 매깁니다. 명확성, 범위, 테스트 가능성, 안전성, Codex 사용성을 기준으로 통과 여부를 판단합니다.",
};

const CHAT_HISTORY_KEY = "changwooPromptAgency.agentChatHistory";

const els = {
  requestInput: document.querySelector("#requestInput"),
  startButton: document.querySelector("#startButton"),
  resetButton: document.querySelector("#resetButton"),
  statusText: document.querySelector("#statusText"),
  taskText: document.querySelector("#taskText"),
  artifactOutput: document.querySelector("#artifactOutput"),
  artifactCount: document.querySelector("#artifactCount"),
  artifactPanel: document.querySelector("#artifactPanel"),
  artifactToggle: document.querySelector("#artifactToggle"),
  teamDrawer: document.querySelector(".team-drawer"),
  agentChatForm: document.querySelector("#agentChatForm"),
  agentQuestion: document.querySelector("#agentQuestion"),
  agentChatStatus: document.querySelector("#agentChatStatus"),
  agentChatLog: document.querySelector("#agentChatLog"),
  askAgentButton: document.querySelector("#askAgentButton"),
  exportChatButton: document.querySelector("#exportChatButton"),
  clearChatButton: document.querySelector("#clearChatButton"),
  selectedAgentLabel: document.querySelector("#selectedAgentLabel"),
  deliveryBox: document.querySelector("#deliveryBox"),
  scoreBoard: document.querySelector("#scoreBoard"),
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
let selectedAgent = "dana";
let chatHistory = loadChatHistory();

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function loadChatHistory() {
  try {
    const raw = window.localStorage.getItem(CHAT_HISTORY_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveChatHistory() {
  window.localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(chatHistory.slice(-80)));
}

function formatChatHistoryMarkdown() {
  if (!chatHistory.length) return "# Changwoo Prompt Agency Chat Log\n\n아직 기록이 없습니다.\n";
  const lines = ["# Changwoo Prompt Agency Chat Log", ""];
  chatHistory.forEach((item, index) => {
    lines.push(`## ${index + 1}. ${item.agentName} ${item.agentRole}`);
    lines.push("");
    lines.push(`- Time: ${item.time}`);
    lines.push(`- Agent: ${item.agent}`);
    lines.push("");
    lines.push("### Question");
    lines.push(item.question);
    lines.push("");
    lines.push("### Answer");
    lines.push(item.answer);
    lines.push("");
  });
  return lines.join("\n");
}

function exportChatHistory() {
  const blob = new Blob([formatChatHistoryMarkdown()], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  link.href = url;
  link.download = `changwoo-agent-chat-${stamp}.md`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function clearChatHistory() {
  if (chatHistory.length && !window.confirm("직원 질문 기록을 모두 삭제할까요? 내보내지 않은 기록은 사라집니다.")) return;
  chatHistory = [];
  window.localStorage.removeItem(CHAT_HISTORY_KEY);
  renderChatHistory();
  els.agentChatStatus.textContent = "질문 기록을 비웠습니다.";
}

function renderChatHistory() {
  els.agentChatLog.textContent = "";
  if (!chatHistory.length) {
    const empty = document.createElement("p");
    empty.className = "chat-empty";
    empty.textContent = "아직 질문 기록이 없습니다. 팀원을 고르고 질문하면 여기에 계속 쌓입니다.";
    els.agentChatLog.append(empty);
    return;
  }

  chatHistory.forEach((item) => {
    const entry = document.createElement("article");
    entry.className = "chat-entry";

    const meta = document.createElement("span");
    meta.textContent = `${item.time} · ${item.agentName} ${item.agentRole}`;

    const question = document.createElement("p");
    question.className = "chat-question";
    question.textContent = `Q. ${item.question}`;

    const answerTitle = document.createElement("strong");
    answerTitle.textContent = "A.";

    const answer = document.createElement("p");
    answer.className = "chat-answer";
    answer.textContent = item.answer;

    entry.append(meta, question, answerTitle, answer);
    els.agentChatLog.append(entry);
  });
  els.agentChatLog.scrollTop = els.agentChatLog.scrollHeight;
}

function addChatHistory(agentKey, question, answer, source) {
  const now = new Date();
  chatHistory.push({
    agent: agentKey,
    agentName: agentLabels[agentKey],
    agentRole: agentRoles[agentKey],
    question,
    answer: source ? `${answer}\n\n(${source})` : answer,
    time: now.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }),
  });
  saveChatHistory();
  renderChatHistory();
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

function selectAgent(agentKey, announce = true) {
  if (!els.agents[agentKey]) return;
  selectedAgent = agentKey;
  setActiveAgent(agentKey);
  els.selectedAgentLabel.textContent = agentLabels[agentKey];
  els.agentChatStatus.textContent = `${agentLabels[agentKey]} ${agentRoles[agentKey]} 선택됨`;
  if (announce) {
    showSpeech(agentKey, "저에게 물어보세요.");
    window.setTimeout(() => hideSpeech(agentKey), 1440);
  }
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
  await sleep(ms * 1.2);
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
        team: ["Nora: 범위", "Mina: UX", "Dana/Jay: 실행성", "Test Kim/Yuna: 검증", "Jason/Sana/Vera: 위험과 점수"],
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
      "4. Nora/Dana/Jay는 범위, 실행 환경, 구현 지시를 쓴다.",
      "5. Test Kim/Yuna/Jason/Sana/Vera가 테스트, 위험, 보안, 품질 점수를 검토한다.",
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
      "- output_contract.md로 Codex의 최종 보고 형식을 고정한다.",
    ].join("\n"),
    review: [
      "# Yuna's Review",
      "",
      "- 성공 기준이 검증 가능해야 한다.",
      "- 자동 검증/수동 검수/위험 항목을 구분해야 한다.",
      "- Codex가 임의로 다음 기능으로 넘어가지 않게 제한해야 한다.",
      "- Jason은 실패 가능성만 지적하고, Vera는 품질 점수를 매긴다.",
      "",
      "Vera score: 88/100",
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
      "- scope.md",
      "- output_contract.md",
      "- security_notes.md",
      "- quality_score.md",
      "",
      "로컬 실행판:",
      "`python3 server.py`로 열면 실제 AI가 Codex용 프롬프트 패키지를 만든다.",
    ].join("\n"),
    qualityScore: 88,
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

function setScoreBoard(score, label = "SCORE") {
  const value = typeof score === "number" ? `${score}/100` : "--";
  els.scoreBoard.innerHTML = `${label}<br><strong>${value}</strong>`;
}

function parseScoreFromText(text) {
  if (!text) return null;
  const slash = text.match(/(\d{1,3})\s*\/\s*100/);
  const named = text.match(/(?:총점|점수|score|total)[^\d]{0,12}(\d{1,3})/i);
  const raw = slash?.[1] || named?.[1];
  if (!raw) return null;
  return Math.max(0, Math.min(100, Number(raw)));
}

function updateScoreFromResult(result, fallbackArtifacts = {}) {
  const apiScore = result?.quality_score?.score;
  if (typeof apiScore === "number") {
    setScoreBoard(apiScore, "VERA");
    return;
  }
  const parsed = parseScoreFromText([fallbackArtifacts.review, fallbackArtifacts.final, fallbackArtifacts.dev].join("\n"));
  setScoreBoard(parsed, parsed === null ? "SCORE" : "VERA");
}

function toggleArtifactPanel(forceOpen) {
  const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : els.artifactPanel.classList.contains("collapsed");
  els.artifactPanel.classList.toggle("collapsed", !shouldOpen);
  els.artifactToggle.setAttribute("aria-expanded", String(shouldOpen));
}

async function askAgent(agentKey, question) {
  if (!shouldUseBackend()) {
    await sleep(250);
    return {
      answer: simulationAnswers[agentKey] || "공개 링크에서는 데모 답변만 가능합니다. 로컬 서버를 켜면 실제 모델 답변을 받을 수 있습니다.",
      provider: "simulation",
      model: "github-pages",
    };
  }

  const response = await fetch("/api/agent-chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ agent: agentKey, question }),
  });
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || "Agent chat failed");
  }
  return payload;
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
  Object.keys(els.agents).forEach((agentKey) => {
    if (positions[agentKey]?.home) setAgentPosition(agentKey, positions[agentKey].home);
  });
  Object.values(els.papers).forEach((paper) => paper.classList.remove("visible"));
  els.deliveryBox.classList.remove("complete");
  hideAllSpeech();
  setActiveAgent(null);
  setScoreBoard(null);
  setTask("Idle", "Waiting for request");
  selectAgent("dana", false);
  els.teamDrawer.removeAttribute("open");
  toggleArtifactPanel(true);
  updateArtifactCount();
  renderArtifact();
  els.startButton.disabled = false;
}

async function sendEveryoneHome() {
  setTask("Wrapping up", "Team is returning to desks");
  await say("mike", "오늘 회의는 여기까지. 모두 고생했어요.", 1500);
  await Promise.all(
    Object.keys(els.agents).map((agentKey) => {
      const home = positions[agentKey]?.home;
      if (!home) return Promise.resolve();
      return moveAgentPath(agentKey, [positions.hallway.delivery, home], `${agentLabels[agentKey]} is returning to desk`);
    })
  );
  await Promise.all([
    say("dana", "기록은 남겨둘게요.", 900),
    say("yuna", "검수 항목도 정리됐습니다.", 900),
  ]);
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
      if (backendResult.model_candidates && backendResult.model_candidates.length > 1) {
        addLog(`대기 모델: ${backendResult.model_candidates.join(" -> ")}`);
      }
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
    backendResult = { quality_score: { score: pendingArtifacts.qualityScore } };
    addLog("공개 링크에서는 시뮬레이션 모드로 실행됩니다.");
  }
  updateScoreFromResult(backendResult, pendingArtifacts);
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
    moveAgentPath("nora", [positions.nora.meeting, positions.nora.home], "Nora is trimming scope"),
    moveAgentPath("dana", [positions.dana.meeting, positions.dana.home], "Dana is checking execution"),
    moveAgentPath("mike", [positions.hallway.center, positions.mike.home], "Mike is tracking progress"),
  ]);
  await Promise.all([
    say("mina", "핵심 화면과 상태 기준을 정리했어요.", 1200),
    say("jay", "파일 구조와 테스트 명령을 넣었습니다.", 1200),
    say("nora", "이번 작업 범위와 제외 범위를 잘랐습니다.", 1200),
    say("dana", "실행 명령과 환경 전제를 고정했어요.", 1200),
  ]);
  artifacts.design = pendingArtifacts.design;
  addLog("Mina가 design artifact를 만들었습니다.");
  artifacts.dev = pendingArtifacts.dev;
  addLog("Jay가 dev artifact를 만들었습니다.");
  showPaper("draft");

  await Promise.all([
    moveAgentPath("mike", [positions.hallway.center, positions.mike.review], "Mike is requesting review"),
    moveAgentPath("yuna", [positions.yuna.meeting, positions.yuna.work], "Yuna is reviewing"),
    moveAgentPath("testkim", [positions.testkim.meeting, positions.testkim.review], "Test Kim is writing tests"),
    moveAgentPath("jason", [positions.jason.meeting, positions.jason.review], "Jason is red-teaming"),
    moveAgentPath("sana", [positions.sana.meeting, positions.sana.review], "Sana is checking safety"),
    moveAgentPath("iris", [positions.iris.meeting, positions.iris.review], "Iris is editing prompt"),
    moveAgentPath("vera", [positions.vera.meeting, positions.vera.review], "Vera is scoring quality"),
  ]);
  await say("mike", "Yuna, 검증 가능한 프롬프트인지 봐주세요.", 1200);
  await Promise.all([
    say("yuna", "체크리스트, 테스트, 위험 항목을 나눠볼게요.", 1300),
    say("testkim", "자동 테스트와 수동 검수를 분리합니다.", 1300),
    say("jason", "망할 지점만 보겠습니다.", 1300),
  ]);
  await Promise.all([
    say("sana", "비밀값과 위험 명령을 차단합니다.", 1200),
    say("iris", "Codex가 오해하지 않게 문장을 다듬습니다.", 1200),
    say("vera", "품질 점수와 blocking issue를 매깁니다.", 1200),
  ]);
  addLog("Yuna가 프롬프트 패키지를 검토했습니다.");

  await Promise.all([
    moveAgentPath("mike", [positions.hallway.delivery, positions.mike.delivery], "Team is preparing delivery"),
    moveAgentPath("mina", [positions.hallway.delivery, positions.mina.delivery], "Team is preparing delivery"),
    moveAgentPath("jay", [positions.hallway.delivery, positions.jay.delivery], "Team is preparing delivery"),
    moveAgentPath("yuna", [positions.hallway.delivery, positions.yuna.delivery], "Team is preparing delivery"),
    moveAgentPath("jason", [positions.hallway.delivery, positions.jason.delivery], "Red team signs off"),
    moveAgentPath("vera", [positions.hallway.delivery, positions.vera.delivery], "Vera sends score"),
    moveAgentPath("changwoo", [positions.hallway.center, positions.hallway.delivery, positions.changwoo.delivery], "Changwoo is checking final delivery"),
  ]);
  artifacts.final = pendingArtifacts.final;
  showPaper("final");
  els.deliveryBox.classList.add("complete");
  await say("mike", "Codex용 최종 프롬프트 준비됐습니다.", 1200);
  await say("changwoo", "좋아. 이걸 Codex에 넣어볼게.", 1100);
  addLog("프롬프트 패키지가 납품 박스에 도착했습니다.");
  await sendEveryoneHome();
  addLog("회의 종료 후 팀원이 각자 자리로 돌아갔습니다.");

  activeArtifact = "final";
  renderArtifact();
  toggleArtifactPanel(true);
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

Object.entries(els.cards).forEach(([agentKey, card]) => {
  card.addEventListener("click", () => selectAgent(agentKey));
});

Object.entries(els.agents).forEach(([agentKey, agent]) => {
  agent.addEventListener("click", () => {
    els.teamDrawer.setAttribute("open", "");
    selectAgent(agentKey);
  });
});

els.agentChatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = els.agentQuestion.value.trim();
  if (!question) return;
  const agentKey = selectedAgent;
  els.askAgentButton.disabled = true;
  els.agentChatStatus.textContent = `${agentLabels[agentKey]}에게 질문 중...`;
  setTask("Asking", `${agentLabels[agentKey]} is answering`);
  showSpeech(agentKey, "잠깐만요. 답변 정리 중입니다.");
  try {
    const payload = await askAgent(agentKey, question);
    const source = payload.provider ? `${payload.provider}/${payload.model}` : "";
    addChatHistory(agentKey, question, payload.answer, source);
    els.agentChatStatus.textContent = `${agentLabels[agentKey]} 답변 기록됨`;
    showSpeech(agentKey, "답변했습니다.");
    addLog(`${agentLabels[agentKey]} 질문 기록: ${question}`);
  } catch (error) {
    addChatHistory(agentKey, question, `ERROR. ${error.message}`, "error");
    els.agentChatStatus.textContent = "질문 처리 오류";
    showSpeech(agentKey, "오류가 났어요.");
    addLog(`${agentLabels[agentKey]} 질문 오류: ${question}`);
  } finally {
    await sleep(1080);
    hideSpeech(agentKey);
    setTask(running ? "Running" : "Idle", running ? "Pipeline is running" : "Waiting for request");
    els.askAgentButton.disabled = false;
  }
});

els.exportChatButton.addEventListener("click", exportChatHistory);
els.clearChatButton.addEventListener("click", clearChatHistory);
els.artifactToggle.addEventListener("click", () => toggleArtifactPanel());
els.startButton.addEventListener("click", runOffice);
els.resetButton.addEventListener("click", resetOffice);

resetOffice();
renderChatHistory();
