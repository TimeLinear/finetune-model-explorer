/* 질의응답 화면 (index.html): 모델 선택·필터, 요약 카드, 모델별 대화(브라우저 메모리), 답변 스트리밍, 사용 조건 점검표. */
"use strict";

const state = {
  models: [], status: null, model: null,
  chats: {},      // model_id → [{role, content, evidence, no_citation, notes, stages}]
  usage: {},      // model_id → 점검표 결과
  busy: false, blocked: false, seq: 0,
};
const $ = (id) => document.getElementById(id);
const STORE_KEY = "kkc-chats";

function loadChats() {
  try { state.chats = JSON.parse(sessionStorage.getItem(STORE_KEY) || "{}") || {}; } catch (_) { state.chats = {}; }
}
function saveChats() {
  try { sessionStorage.setItem(STORE_KEY, JSON.stringify(state.chats)); } catch (_) { /* 저장 실패해도 메모리로 동작 */ }
}

/* ---------- 모델 목록·필터 ---------- */
function filteredModels() {
  const q = $("model-search").value.trim().toLowerCase();
  const size = $("f-size").value;
  const stage = $("f-stage").value;
  const image = $("f-image").checked;
  const [lo, hi] = size ? size.split("-").map(Number) : [null, null];
  return state.models.filter((m) => {
    if (q && !m.model_id.toLowerCase().includes(q) && !(m.vendor || "").toLowerCase().includes(q)) return false;
    if (size && !(m.params_b > lo && m.params_b <= hi)) return false;
    if (stage && m.stage !== stage) return false;
    if (image && !m.input_modalities.includes("image")) return false;
    return true;
  });
}

function renderModelList() {
  const list = $("model-list");
  list.replaceChildren();
  const rows = filteredModels();
  for (const m of rows) {
    const li = el("li", { role: "option", "aria-selected": m.model_id === state.model ? "true" : "false", "data-id": m.model_id },
      m.model_id, el("span", { class: "meta", text: ` · ${m.params_b}B` }));
    li.addEventListener("click", () => selectModel(m.model_id));
    list.append(li);
  }
  $("model-count").textContent = `${rows.length} / ${state.models.length}`;
}

/* ---------- 선택 모델 ---------- */
async function selectModel(modelId) {
  if (state.busy) return;
  state.model = modelId;
  const url = new URL(location.href);
  url.searchParams.set("model", modelId);
  history.replaceState(null, "", url);
  renderModelList();
  $("no-model").classList.add("hidden");
  $("workspace").classList.remove("hidden");
  $("current-model").textContent = modelId;
  renderMessages();
  renderUsage();
  const box = $("model-card");
  box.replaceChildren();
  try {
    const d = await getJSON(`/api/models/${encodeURIComponent(modelId).replace(/%2F/g, "/")}`);
    if (state.model !== modelId) return;
    box.append(modelCardNode(d));
  } catch (e) {
    showNotice(box, "error", e.message);
  }
}

function modelCardNode(d) {
  const T = App.T, f = T.card_fields, L = App.labels;
  const mods = (d.input_modalities || []).map((m) => L.modality[m] || m).join(", ");
  const card = el("div", { class: "card" },
    el("h3", { text: T.selected_card_title }),
    el("div", { class: "model-id", text: d.model_id }));
  const specs = el("dl", { class: "specs" });  // 사양: 2열 정의 목록
  const spec = (label, value, num) => specs.append(el("dt", { text: label }), el("dd", { class: num ? "num" : "", text: value }));
  if (d.vendor) spec(f.vendor, d.vendor);
  if (d.params_b != null) spec(f.params, `${d.params_b}B`, true);
  if (d.license) spec(f.license, d.license, true);
  if (mods) spec(f.modalities, mods);
  if (d.context) spec(f.context, Number(d.context).toLocaleString("ko-KR"), true);
  if (d.downloads != null) spec(f.downloads, Number(d.downloads).toLocaleString("ko-KR"), true);
  card.append(specs);
  if (d.highlights && d.highlights.length) {
    card.append(chipsNode(d.highlights));
    const det = el("details", {}, el("summary", { text: T.highlights_all }));
    const ul = el("ul");
    for (const h of d.highlights) ul.append(el("li", { text: h }));
    det.append(ul);
    card.append(det);
  }
  if (d.summary) card.append(el("p", { class: "caption", text: `${f.summary}: ${d.summary}` }));
  if (d.card_url) card.append(el("div", { class: "caption" }, externalLink(d.card_url, "Hugging Face")));
  return card;
}

/* ---------- 대화 ---------- */
function messageNode(msg, idx) {
  const T = App.T;
  const node = el("div", { class: `msg ${msg.role}` });
  node.append(el("div", { class: "who", text: msg.role === "user" ? "질문" : "답변" }));
  if (msg.role === "user") {
    node.append(el("div", { class: "body", text: msg.content }));
    return node;
  }
  const prefix = `ev-${idx}`;
  if (msg.stages && msg.stages.length) {
    const ul = el("ul", { class: "stages" });
    for (const s of msg.stages) ul.append(el("li", { text: s }));
    node.append(ul);
  }
  const body = el("div", { class: "body" });
  body.innerHTML = renderMarkdown(msg.content, prefix, T.citation_label); // renderMarkdown 은 전체를 이스케이프한 뒤 변환
  node.append(body);
  for (const n of msg.notes || []) node.append(el("div", { class: "caption", text: n }));
  if (msg.no_citation) node.append(el("div", { class: "caption", text: "ⓘ " + T.no_citation }));
  else if (msg.evidence && msg.evidence.length) node.append(evidenceNode(msg.evidence, prefix));
  return node;
}

function renderMessages() {
  const box = $("messages");
  box.replaceChildren();
  (state.chats[state.model] || []).forEach((m, i) => box.append(messageNode(m, i)));
}

function setBusy(busy) {
  state.busy = busy;
  $("ask-btn").disabled = busy || state.blocked;
  $("question").disabled = busy || state.blocked;
  $("clear-chat").disabled = busy;
  $("usage-btn").disabled = busy || state.blocked;
}

/* fetch 스트림에서 SSE 이벤트를 하나씩 꺼낸다: {event, data} */
async function* readSSE(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let cut;
    while ((cut = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, cut);
      buf = buf.slice(cut + 2);
      let event = "message", data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (data) yield { event, data: JSON.parse(data) };
    }
  }
}

async function ask(question) {
  const T = App.T, modelId = state.model;
  const chat = (state.chats[modelId] = state.chats[modelId] || []);
  const turns = state.status.history_turns || 0;
  const history = turns ? chat.slice(-2 * turns).map((m) => ({ role: m.role, content: m.content })) : [];
  chat.push({ role: "user", content: question });
  const msg = { role: "assistant", content: "", stages: [], evidence: [], no_citation: false, notes: [] };
  renderMessages();

  const live = el("div", { class: "msg assistant" }, el("div", { class: "who", text: "답변" }));
  const stages = el("ul", { class: "stages" });
  const body = el("div", { class: "body streaming" });
  live.append(stages, body);
  $("messages").append(live);
  setBusy(true);
  let failed = null;
  try {
    const res = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: modelId, question, history }),
    });
    if (!res.ok) {
      let err = T.error_generic;
      try { err = (await res.json()).error || err; } catch (_) { /* 본문 없음 */ }
      throw new Error(err);
    }
    for await (const { event, data } of readSSE(res)) {
      if (event === "stage") { msg.stages.push(data.text); stages.append(el("li", { text: data.text })); }
      else if (event === "token") { msg.content += data.text; body.textContent = msg.content; }
      else if (event === "done") {
        msg.content = data.answer; msg.evidence = data.evidence; msg.no_citation = data.no_citation; msg.notes = data.notes || [];
        msg.stages.push(T.status_done);
      } else if (event === "error") { throw new Error(data.text); }
    }
    if (!msg.stages.includes(T.status_done)) throw new Error(T.error_generic);
    chat.push(msg);
  } catch (e) {
    failed = e.message || T.error_generic;
    chat.pop(); // 실패한 질문은 기록에 남기지 않는다 (다시 물을 수 있게)
  }
  saveChats();
  setBusy(false);
  if (state.model === modelId) {
    renderMessages();
    if (failed) {
      showNotice($("messages"), "error", `${T.status_failed}: ${failed}`);
      $("question").value = question;
    }
  }
}

/* ---------- 사용 조건 점검표 ---------- */
function renderUsage() {
  const T = App.T, U = T.usage, box = $("usage-result");
  box.replaceChildren();
  $("usage-status").textContent = "";
  const r = state.usage[state.model];
  if (!r) return;
  const table = el("table");
  table.append(el("thead", {}, el("tr", {},
    el("th", { class: "col-aspect", text: U.col_aspect }), el("th", { text: U.col_finding }),
    el("th", { class: "col-evidence", text: U.col_evidence }), el("th", { class: "col-status", text: U.col_status }))));
  const tbody = el("tbody");
  for (const row of r.rows) {  // data-label: 640px 이하에서 행을 카드로 바꿀 때 칸 이름
    tbody.append(el("tr", {},
      el("td", { class: "aspect", "data-label": U.col_aspect, text: U.aspect[row.aspect] || row.aspect }),
      el("td", { "data-label": U.col_finding, text: row.finding }),
      el("td", { class: "num", "data-label": U.col_evidence, text: row.evidence_ids.map((n) => `[${n}]`).join(" ") || "-" }),
      el("td", { "data-label": U.col_status },
        el("span", { class: `status ${row.status}`, text: U.status[row.status] || row.status }))));
  }
  table.append(tbody);
  box.append(el("div", { class: "table-wrap" }, table));
  if (r.evidence.length) box.append(evidenceNode(r.evidence, "usage-ev", `${U.evidence_title} ({n})`));
  box.append(el("p", { class: "caption", text: T.disclaimer }));
}

async function buildUsage() {
  const T = App.T, modelId = state.model;
  setBusy(true);
  $("usage-status").textContent = T.usage.spinner;
  try {
    state.usage[modelId] = await postJSON("/api/usage-check", { model_id: modelId });
    if (state.model === modelId) renderUsage();
  } catch (e) {
    $("usage-status").textContent = "";
    showNotice($("usage-result"), "error", e.message);
  } finally {
    setBusy(false);
    if ($("usage-status").textContent === T.usage.spinner) $("usage-status").textContent = "";
  }
}

/* ---------- 탭·초기화 ---------- */
function showTab(name) {
  const chat = name === "chat";
  $("tab-chat").classList.toggle("hidden", !chat);
  $("tab-usage").classList.toggle("hidden", chat);
  $("tab-chat-btn").setAttribute("aria-selected", String(chat));
  $("tab-usage-btn").setAttribute("aria-selected", String(!chat));
}

async function init() {
  const T = await loadCommon();
  renderNav("chat");
  loadChats();
  $("sidebar-title").textContent = T.sidebar_title;
  $("select-label").textContent = T.select_label;
  $("model-search").placeholder = T.select_placeholder;
  $("app-title").textContent = T.app_title;
  $("app-caption").textContent = T.app_caption;
  $("disclaimer").textContent = T.disclaimer;
  $("no-model").textContent = T.choose_model_first;
  $("tab-chat-btn").textContent = T.tab_chat;
  $("tab-usage-btn").textContent = T.tab_usage;
  $("question").placeholder = T.chat_placeholder;
  $("clear-chat").textContent = T.clear_chat;
  $("usage-intro").textContent = T.usage.intro;
  $("usage-btn").textContent = T.usage.button;

  try {
    const [status, models] = await Promise.all([getJSON("/api/status"), getJSON("/api/models")]);
    state.status = status;
    state.models = models.models;
    App.labels = models.labels;
    $("index-counts").textContent = fmt(T.index_counts, status);
    state.blocked = renderStatusNotices($("notices"), status);
  } catch (e) {
    showNotice($("notices"), "error", e.message);
    return;
  }
  const stageSel = $("f-stage");
  stageSel.append(el("option", { value: "", text: "학습 단계 전체" }));
  for (const [k, v] of Object.entries(App.labels.stage)) stageSel.append(el("option", { value: k, text: v }));
  $("f-image-label").textContent = "이미지 입력";
  for (const id of ["model-search", "f-size", "f-stage", "f-image"]) $(id).addEventListener("input", renderModelList);
  renderModelList();

  $("tab-chat-btn").addEventListener("click", () => showTab("chat"));
  $("tab-usage-btn").addEventListener("click", () => showTab("usage"));
  $("usage-btn").addEventListener("click", buildUsage);
  $("clear-chat").addEventListener("click", () => { state.chats[state.model] = []; saveChats(); renderMessages(); });
  $("ask-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("question").value.trim();
    if (!q || state.busy || state.blocked || !state.model) return;
    $("question").value = "";
    ask(q);
  });
  $("question").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("ask-form").requestSubmit(); }
  });
  setBusy(false);

  const pre = new URLSearchParams(location.search).get("model");
  if (pre && state.models.some((m) => m.model_id === pre)) selectModel(pre);
  else $("no-model").classList.remove("hidden");
}

init();
