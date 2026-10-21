/* 社群决策 AI · 前端逻辑
 * 流程：上传文件 → 开始分析（后台流水线）→ 轮询进度 → 渲染意图 / 智能体 / 决策报告
 */

const $ = (selector, root = document) => root.querySelector(selector);

const state = {
  session: null, // 当前会话完整数据
  pollTimer: null,
};

const el = {
  modelBadge: $("#modelBadge"),
  dropzone: $("#dropzone"),
  fileInput: $("#fileInput"),
  uploadStatus: $("#uploadStatus"),
  historyList: $("#historyList"),
  historyCount: $("#historyCount"),
  introCard: $("#introCard"),
  conversationCard: $("#conversationCard"),
  convMeta: $("#convMeta"),
  conversation: $("#conversation"),
  pipelineCard: $("#pipelineCard"),
  runBtn: $("#runBtn"),
  progressFill: $("#progressFill"),
  stepper: $("#stepper"),
  intentCard: $("#intentCard"),
  intentBody: $("#intentBody"),
  collabCard: $("#collabCard"),
  collabHint: $("#collabHint"),
  agentsGrid: $("#agentsGrid"),
  reportCard: $("#reportCard"),
  reportBody: $("#reportBody"),
  copyBtn: $("#copyBtn"),
  errorBanner: $("#errorBanner"),
};

const AVATAR_COLORS = ["#5b6cf9", "#e88a2b", "#2ea36f", "#d6597c", "#8b5cf6", "#0891b2", "#b45309", "#4b5563"];

init();

function init() {
  bindEvents();
  checkHealth();
  refreshHistory();
}

/* ---------------- 工具 ---------------- */

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function hashText(text) {
  let hash = 0;
  for (const ch of String(text)) hash = (hash * 31 + ch.codePointAt(0)) % 997;
  return hash;
}

function avatarColor(name) {
  return AVATAR_COLORS[hashText(name) % AVATAR_COLORS.length];
}

function listItems(items, className = "") {
  if (!items || !items.length) return `<li>—</li>`;
  return items.map((item) => `<li>${esc(item)}</li>`).join("");
}

const STATUS_TEXT = {
  uploaded: "待分析",
  running: "分析中",
  done: "已完成",
  failed: "失败",
};

/* ---------------- 事件绑定 ---------------- */

function bindEvents() {
  el.dropzone.addEventListener("click", () => el.fileInput.click());
  el.dropzone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      el.fileInput.click();
    }
  });
  el.fileInput.addEventListener("change", () => {
    const file = el.fileInput.files[0];
    if (file) handleFile(file);
    el.fileInput.value = "";
  });
  ["dragenter", "dragover"].forEach((type) =>
    el.dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      el.dropzone.classList.add("dragging");
    })
  );
  ["dragleave", "drop"].forEach((type) =>
    el.dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      el.dropzone.classList.remove("dragging");
    })
  );
  el.dropzone.addEventListener("drop", (event) => {
    const file = event.dataTransfer.files[0];
    if (file) handleFile(file);
  });

  el.runBtn.addEventListener("click", runAnalysis);
  el.copyBtn.addEventListener("click", copyReport);
  el.historyList.addEventListener("click", onHistoryClick);
}

/* ---------------- 服务状态 ---------------- */

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    const info = await response.json();
    if (info.mock) {
      el.modelBadge.textContent = "离线演示模式（LLM_MOCK）";
      el.modelBadge.className = "badge badge-warn";
    } else if (!info.has_key) {
      el.modelBadge.textContent = "未配置 LLM_API_KEY";
      el.modelBadge.className = "badge badge-warn";
    } else {
      el.modelBadge.textContent = `模型：${info.model}`;
      el.modelBadge.className = "badge badge-ok";
    }
  } catch {
    el.modelBadge.textContent = "服务未连接";
    el.modelBadge.className = "badge badge-err";
  }
}

/* ---------------- 上传 ---------------- */

function showUploadStatus(message, isError = false) {
  el.uploadStatus.textContent = message;
  el.uploadStatus.classList.remove("hidden");
  el.uploadStatus.classList.toggle("error", isError);
}

async function handleFile(file) {
  const name = file.name.toLowerCase();
  if (!name.endsWith(".txt") && !name.endsWith(".json")) {
    showUploadStatus("仅支持 .txt 或 .json 文件", true);
    return;
  }
  if (file.size > 2 * 1024 * 1024) {
    showUploadStatus("文件不能超过 2MB", true);
    return;
  }
  showUploadStatus("正在解析文件…", false);
  try {
    const response = await fetch(`/api/sessions?filename=${encodeURIComponent(file.name)}`, {
      method: "POST",
      body: file,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "解析失败");
    showUploadStatus(`解析成功：共 ${data.messages.length} 条消息`, false);
    enterSession(data);
    refreshHistory();
  } catch (error) {
    showUploadStatus(error.message, true);
  }
}

/* ---------------- 会话加载 / 轮询 ---------------- */

function enterSession(session) {
  stopPolling();
  state.session = session;
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function loadSession(id) {
  stopPolling();
  try {
    const response = await fetch(`/api/sessions/${id}`);
    if (!response.ok) throw new Error("会话不存在");
    enterSession(await response.json());
    if (state.session.status === "running") startPolling();
    refreshHistory();
  } catch (error) {
    showUploadStatus(error.message, true);
  }
}

async function runAnalysis() {
  const session = state.session;
  if (!session) return;
  el.runBtn.disabled = true;
  el.runBtn.textContent = "启动中…";
  try {
    const response = await fetch(`/api/sessions/${session.id}/run`, { method: "POST" });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.detail || "启动失败");
    }
    await pollOnce();
    startPolling();
  } catch (error) {
    el.runBtn.disabled = false;
    el.runBtn.textContent = "开始分析";
    showError(error.message);
  }
}

function startPolling() {
  stopPolling();
  el.runBtn.disabled = true;
  el.runBtn.textContent = "分析中…";
  state.pollTimer = setInterval(pollOnce, 1500);
}

function stopPolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
  if (state.session) {
    const status = state.session.status;
    el.runBtn.disabled = false;
    el.runBtn.textContent = status === "done" || status === "failed" ? "重新分析" : "开始分析";
  }
}

async function pollOnce() {
  const session = state.session;
  if (!session) return;
  try {
    const response = await fetch(`/api/sessions/${session.id}`);
    if (!response.ok) throw new Error("会话不存在");
    state.session = await response.json();
    render();
    if (state.session.status === "done" || state.session.status === "failed") {
      stopPolling();
      refreshHistory();
    }
  } catch (error) {
    stopPolling();
    showError(error.message);
  }
}

/* ---------------- 渲染 ---------------- */

function render() {
  const session = state.session;
  if (!session) return;

  el.conversationCard.classList.remove("hidden");
  el.pipelineCard.classList.remove("hidden");
  el.introCard.classList.add("hidden");

  renderConversation(session);
  renderPipeline(session);
  renderIntent(session);
  renderCollab(session);
  renderReport(session);
  renderError(session);
}

function renderConversation(session) {
  const messages = session.messages || [];
  el.convMeta.textContent = `${session.source_file} · ${messages.length} 条消息`;
  const visible = messages.slice(0, 200);
  el.conversation.innerHTML = visible
    .map(
      (message) => `
      <div class="msg">
        <div class="msg-avatar" style="background:${avatarColor(message.speaker)}">${esc((message.speaker || "?").slice(0, 1))}</div>
        <div class="msg-main">
          <div class="msg-head">
            <span class="msg-name">${esc(message.speaker || "未知")}</span>
            ${message.time ? `<span class="msg-time">${esc(message.time)}</span>` : ""}
          </div>
          <div class="msg-text">${esc(message.content)}</div>
        </div>
      </div>`
    )
    .join("");
  if (messages.length > 200) {
    el.conversation.insertAdjacentHTML("beforeend", `<p class="muted-note">…还有 ${messages.length - 200} 条消息未显示</p>`);
  }
}

function renderPipeline(session) {
  const steps = session.steps || [];
  el.stepper.innerHTML = steps
    .map((step, index) => {
      const status = step.status || "pending";
      const dot =
        status === "running" ? '<span class="spinner"></span>' : status === "done" ? "✓" : status === "failed" ? "✕" : String(index + 1);
      return `
      <li class="step ${status}">
        <span class="step-dot">${dot}</span>
        <div class="step-body">
          <span class="step-label">${esc(step.label)}</span>
          ${step.detail ? `<span class="step-detail">${esc(step.detail)}</span>` : ""}
        </div>
      </li>`;
    })
    .join("");
  el.progressFill.style.width = `${session.progress || 0}%`;
}

function renderIntent(session) {
  const intent = session.intent;
  el.intentCard.classList.toggle("hidden", !intent);
  if (!intent) return;
  const participants = intent.participants || [];
  el.intentBody.innerHTML = `
    <div class="kv"><span class="kv-key">讨论主题</span><span>${esc(intent.topic || "—")}</span></div>
    <div class="decision-q">
      <span class="kv-key">核心决策问题</span>
      <p>${esc(intent.decision_question || "—")}</p>
    </div>
    ${intent.summary ? `<p class="intent-summary">${esc(intent.summary)}</p>` : ""}
    <div class="sub-head">各方立场</div>
    <div class="participants">
      ${participants
        .map(
          (participant) => `
        <div class="participant">
          <div class="participant-name">${esc(participant.name)}</div>
          <div class="participant-stance">${esc(participant.stance)}</div>
          <div class="tags">${(participant.key_points || []).map((point) => `<span class="tag">${esc(point)}</span>`).join("")}</div>
        </div>`
        )
        .join("")}
    </div>
    <div class="two-col">
      <div>
        <div class="sub-head">已有共识</div>
        <ul class="dot-list">${listItems(intent.shared_views)}</ul>
      </div>
      <div>
        <div class="sub-head">主要分歧</div>
        <ul class="dot-list warn">${listItems(intent.disagreements)}</ul>
      </div>
    </div>`;
}

function renderCollab(session) {
  const round1 = session.agents_round1 || [];
  el.collabCard.classList.toggle("hidden", round1.length === 0);
  if (!round1.length) return;

  const round2 = session.agents_round2 || [];
  const changedCount = round2.filter((item) => item.changed).length;
  el.collabHint.textContent = round2.length ? `${round1.length} 位智能体 · ${changedCount} 位调整了立场` : `${round1.length} 位智能体 · 第一轮意见`;

  el.agentsGrid.innerHTML = round1
    .map((agent) => {
      const revision = round2.find((item) => item.key === agent.key);
      const revisionHtml = revision
        ? `
        <div class="agent-section round2">
          <span class="agent-section-title">第二轮
            <span class="change-badge ${revision.changed ? "" : "keep"}">${revision.changed ? "立场调整" : "立场坚持"}</span>
          </span>
          <p class="agent-stance">「${esc(revision.final_stance)}」</p>
          ${revision.key_argument ? `<p class="agent-text">${esc(revision.key_argument)}</p>` : ""}
          ${revision.change_reason ? `<p class="agent-reason">${esc(revision.change_reason)}</p>` : ""}
          ${revision.agreements.length ? `<div class="tags">${revision.agreements.map((item) => `<span class="tag">认同：${esc(item)}</span>`).join("")}</div>` : ""}
          ${revision.disagreements.length ? `<div class="tags">${revision.disagreements.map((item) => `<span class="tag">保留：${esc(item)}</span>`).join("")}</div>` : ""}
        </div>`
        : "";

      return `
      <div class="agent-card">
        <div class="agent-head">
          <span class="agent-emoji">${esc(agent.emoji || "🤖")}</span>
          <div>
            <div class="agent-name">${esc(agent.name)}</div>
            <div class="agent-role">${esc(agent.desc || "")}</div>
          </div>
        </div>
        <div class="agent-section">
          <span class="agent-section-title">首轮意见</span>
          <p class="agent-stance">「${esc(agent.stance)}」</p>
          <p class="agent-text">${esc(agent.proposal)}</p>
          ${agent.reasoning ? `<p class="agent-reason">理由：${esc(agent.reasoning)}</p>` : ""}
          ${agent.concerns.length ? `<div class="tags">${agent.concerns.map((item) => `<span class="tag">担忧：${esc(item)}</span>`).join("")}</div>` : ""}
        </div>
        ${revisionHtml}
      </div>`;
    })
    .join("");
}

function renderReport(session) {
  const report = session.report;
  el.reportCard.classList.toggle("hidden", !report);
  if (!report) return;

  const confidenceClass = report.confidence === "高" ? "高" : report.confidence === "低" ? "低" : "中";
  const participants = (report.participant_summary || [])
    .map((item) => `<div class="p-row"><span class="p-name">${esc(item.name)}</span><span>${esc(item.view)}</span></div>`)
    .join("");

  el.reportBody.innerHTML = `
    <h3 class="report-title">${esc(report.title)}</h3>
    ${report.decision_question ? `<p class="report-sub">决策问题：${esc(report.decision_question)}</p>` : ""}
    <div class="decision-box">
      <span class="decision-label">最终决策</span>
      <p>${esc(report.final_decision)}</p>
      <span class="conf conf-${confidenceClass}">置信度 ${esc(report.confidence)}</span>
    </div>
    ${report.background ? `<div class="report-section"><span class="kv-key">背景</span><p class="report-p">${esc(report.background)}</p></div>` : ""}
    ${report.rationale ? `<div class="report-section"><span class="kv-key">决策依据</span><p class="report-p">${esc(report.rationale)}</p></div>` : ""}
    ${participants ? `<div class="report-section"><div class="sub-head">参与者诉求</div>${participants}</div>` : ""}
    <div class="report-section">
      <div class="two-col">
        <div>
          <div class="sub-head">共识</div>
          <ul class="check-list">${listItems(report.consensus)}</ul>
        </div>
        <div>
          <div class="sub-head">仍存在的分歧</div>
          <ul class="check-list amber">${listItems(report.disagreements)}</ul>
        </div>
      </div>
    </div>
    <div class="report-section">
      <div class="sub-head">风险提示</div>
      <ul class="check-list risk">${listItems(report.risks)}</ul>
    </div>
    <div class="report-section">
      <div class="sub-head">行动清单</div>
      <ol class="num-list">${report.action_items.map((item) => `<li>${esc(item)}</li>`).join("")}</ol>
    </div>`;
}

function renderError(session) {
  const error = session.error;
  if (!error) {
    el.errorBanner.classList.add("hidden");
    el.errorBanner.textContent = "";
    return;
  }
  el.errorBanner.textContent = `分析失败：${error}`;
  el.errorBanner.classList.remove("hidden");
}

function showError(message) {
  el.errorBanner.textContent = message;
  el.errorBanner.classList.remove("hidden");
}

/* ---------------- 复制报告 ---------------- */

async function copyReport() {
  const report = state.session && state.session.report;
  if (!report) return;
  const lines = [
    `# ${report.title}`,
    "",
    report.decision_question ? `决策问题：${report.decision_question}` : "",
    "",
    `最终决策：${report.final_decision}`,
    report.confidence ? `置信度：${report.confidence}` : "",
    "",
    report.rationale ? `决策依据：${report.rationale}` : "",
    "",
    `共识：\n${(report.consensus || []).map((item) => `- ${item}`).join("\n")}`,
    "",
    `分歧：\n${(report.disagreements || []).map((item) => `- ${item}`).join("\n")}`,
    "",
    `风险：\n${(report.risks || []).map((item) => `- ${item}`).join("\n")}`,
    "",
    `行动清单：\n${(report.action_items || []).map((item, index) => `${index + 1}. ${item}`).join("\n")}`,
  ];
  try {
    await navigator.clipboard.writeText(lines.join("\n").trim());
    el.copyBtn.textContent = "已复制";
    setTimeout(() => (el.copyBtn.textContent = "复制报告"), 1500);
  } catch {
    showError("复制失败，请检查浏览器剪贴板权限");
  }
}

/* ---------------- 历史会话 ---------------- */

async function refreshHistory() {
  try {
    const response = await fetch("/api/sessions");
    const sessions = await response.json();
    el.historyCount.textContent = sessions.length ? `${sessions.length} 个` : "";
    if (!sessions.length) {
      el.historyList.innerHTML = `<li class="history-empty">暂无会话</li>`;
      return;
    }
    el.historyList.innerHTML = sessions
      .map(
        (item) => `
      <li class="history-item ${state.session && state.session.id === item.id ? "active" : ""}" data-id="${esc(item.id)}">
        <div class="history-main">
          <div class="history-title">${esc(item.title)}</div>
          <div class="history-meta">${esc(item.created_at)} · ${item.message_count} 条 · ${STATUS_TEXT[item.status] || item.status}</div>
        </div>
        <button class="icon-btn" data-del="${esc(item.id)}" title="删除该会话">✕</button>
      </li>`
      )
      .join("");
  } catch {
    /* 服务未启动时静默 */
  }
}

function onHistoryClick(event) {
  const deleteBtn = event.target.closest("[data-del]");
  if (deleteBtn) {
    event.stopPropagation();
    deleteSession(deleteBtn.dataset.del);
    return;
  }
  const item = event.target.closest(".history-item");
  if (item) loadSession(item.dataset.id);
}

async function deleteSession(id) {
  if (!confirm("确定删除该会话吗？")) return;
  try {
    await fetch(`/api/sessions/${id}`, { method: "DELETE" });
    if (state.session && state.session.id === id) {
      state.session = null;
      stopPolling();
      el.conversationCard.classList.add("hidden");
      el.pipelineCard.classList.add("hidden");
      el.intentCard.classList.add("hidden");
      el.collabCard.classList.add("hidden");
      el.reportCard.classList.add("hidden");
      el.errorBanner.classList.add("hidden");
      el.introCard.classList.remove("hidden");
    }
    refreshHistory();
  } catch {
    showError("删除失败");
  }
}
