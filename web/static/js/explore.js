/* 조건 탐색 화면 (explore.html): 자연어 조건 → 결과 카드 → "이 모델에 질문하기"로 index.html?model=<id> */
"use strict";

const $ = (id) => document.getElementById(id);
let blocked = false;

function resultCard(r) {
  const T = App.T, C = T.condition, L = App.labels;
  const mods = (r.input_modalities || []).map((m) => L.modality[m] || m).join(", ");
  const card = el("article", { class: "card" }, el("div", { class: "model-id", text: r.model_id }));
  if (r.downloads != null) {  // 주요 수치: 최근 30일 다운로드
    card.append(el("div", { class: "figure" },
      el("span", { class: "value", text: Number(r.downloads).toLocaleString("ko-KR") }),
      el("span", { class: "unit", text: T.card_fields.downloads })));
  }
  const facts = el("ul", { class: "facts" });
  facts.append(el("li", {}, el("span", { class: "num", text: `${r.params_b}B` }), mods ? ` · ${mods}` : "",
    r.license ? ` · ${r.license}` : ""));
  card.append(facts);
  if (r.highlights && r.highlights.length) card.append(chipsNode(r.highlights));
  card.append(el("div", { class: "reason" }, el("strong", { text: C.reason }), r.reason));
  card.append(el("div", { class: "actions" },
    el("a", { href: `index.html?model=${encodeURIComponent(r.model_id)}`, text: C.ask_button,
              "aria-label": `${r.model_id} — ${C.ask_button}` })));
  return card;
}

async function run(request) {
  const T = App.T, C = T.condition;
  const btn = $("explore-btn");
  btn.disabled = true;
  $("explore-status").textContent = C.spinner;
  $("results").replaceChildren();
  $("summary-line").textContent = "";
  $("applied").classList.add("hidden");
  try {
    const res = await postJSON("/api/explore", { request });
    $("summary-line").textContent = fmt(C.candidates, { n: res.candidates_count, m: res.results.length });
    const list = $("applied-list");
    list.replaceChildren();
    for (const [k, v] of Object.entries(res.filter)) {
      list.append(el("li", {}, el("span", { class: "mono", text: k }), `: ${Array.isArray(v) ? v.join(", ") : v}`));
    }
    $("applied").classList.toggle("hidden", !list.children.length);
    if (!res.results.length) showNotice($("results"), "info", T.no_results);
    for (const r of res.results) $("results").append(resultCard(r));
  } catch (e) {
    showNotice($("results"), "error", e.message);
  } finally {
    $("explore-status").textContent = "";
    btn.disabled = blocked;
  }
}

async function init() {
  const T = await loadCommon();
  const C = T.condition;
  renderNav("explore");
  document.title = C.title;
  $("title").textContent = C.title;
  $("caption").textContent = C.caption;
  $("input-label").textContent = C.input_label;
  $("request").placeholder = C.input_placeholder;
  $("request").setAttribute("aria-label", C.input_label);
  $("explore-btn").textContent = C.button;
  $("applied-title").textContent = C.applied_filters;
  $("popularity").textContent = T.popularity_note;
  $("disclaimer").textContent = T.disclaimer;
  try {
    const [status, models] = await Promise.all([getJSON("/api/status"), getJSON("/api/models")]);
    App.labels = models.labels;
    blocked = renderStatusNotices($("notices"), status);
  } catch (e) {
    showNotice($("notices"), "error", e.message);
    blocked = true;
  }
  $("explore-btn").disabled = blocked;
  $("explore-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("request").value.trim();
    if (q && !blocked) run(q);
  });
}

init();
