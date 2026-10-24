/* 공통: 이스케이프, 제한된 마크다운 변환, API 호출, 상단 메뉴·안내·근거 목록.
 * LLM 출력과 데이터 문자열은 textContent 로 넣거나, escapeHtml 을 거친 뒤에만 HTML 로 만든다.
 * 이 파일은 node 에서도 불러 테스트한다 (tests/test_web_api.py). 브라우저 전용 코드는 document 가 있을 때만 쓴다. */
"use strict";

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/* 이미 이스케이프된 한 줄 안에서만 쓰는 인라인 변환: **굵게**, `코드`, [근거 n] → 근거 항목 앵커 */
function inlineMarkdown(escaped, citePrefix, citeLabel) {
  let out = escaped
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  if (citePrefix) {
    const label = escapeHtml(citeLabel || "근거");
    const re = new RegExp("\\[" + label + "\\s*(\\d+)\\]", "g");
    out = out.replace(re, (_m, n) => `<a class="cite" href="#${citePrefix}-${n}">[${label} ${n}]</a>`);
  }
  return out;
}

/* 답변 마크다운: 전체를 먼저 이스케이프한 뒤 문단·목록·굵게만 변환한다 (그 밖의 마크다운은 글자 그대로). */
function renderMarkdown(text, citePrefix, citeLabel) {
  const lines = escapeHtml(text).replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let list = null; // "ul" | "ol"
  let para = [];
  const flushPara = () => {
    if (para.length) html.push("<p>" + para.map((l) => inlineMarkdown(l, citePrefix, citeLabel)).join("<br>") + "</p>");
    para = [];
  };
  const closeList = () => { if (list) { html.push(`</${list}>`); list = null; } };
  for (const raw of lines) {
    const line = raw.trimEnd();
    const ul = line.match(/^\s*[-*]\s+(.*)$/);
    const ol = line.match(/^\s*\d+\.\s+(.*)$/);
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    if (ul || ol) {
      flushPara();
      const kind = ul ? "ul" : "ol";
      if (list !== kind) { closeList(); html.push(`<${kind}>`); list = kind; }
      html.push("<li>" + inlineMarkdown((ul || ol)[1], citePrefix, citeLabel) + "</li>");
    } else if (!line.trim()) {
      flushPara(); closeList();
    } else if (heading) {
      flushPara(); closeList();
      html.push("<p><strong>" + inlineMarkdown(heading[1], citePrefix, citeLabel) + "</strong></p>");
    } else {
      closeList();
      para.push(line);
    }
  }
  flushPara(); closeList();
  return html.join("");
}

if (typeof module !== "undefined") {
  module.exports = { escapeHtml, renderMarkdown };
}

/* ---------- 이하 브라우저 전용 ---------- */

const App = { T: null, labels: null };

async function getJSON(url, options) {
  const res = await fetch(url, options);
  let body = null;
  try { body = await res.json(); } catch (_) { /* 본문 없음 */ }
  if (!res.ok) {
    const msg = (body && body.error) || (App.T && App.T.error_generic) || "오류";
    throw new Error(msg);
  }
  return body;
}

function postJSON(url, data) {
  return getJSON(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
}

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children) {
    if (c === null || c === undefined) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function fmt(template, values) {
  return String(template).replace(/\{(\w+)\}/g, (m, k) => (k in values ? values[k] : m));
}

function showNotice(container, kind, text) {
  container.append(el("div", { class: `notice ${kind}`, role: kind === "error" ? "alert" : "status", text }));
}

function externalLink(href, text) {
  if (!href || !/^https?:\/\//.test(href)) return document.createTextNode(text);
  return el("a", { href, target: "_blank", rel: "noopener noreferrer", text });
}

function chipsNode(highlights) {
  const box = el("div", { class: "chips" });
  for (const h of highlights || []) box.append(el("span", { class: "chip", title: h, text: h }));
  return box;
}

/* 백틱으로 감싼 부분만 <code> 로, 나머지는 글자 그대로 (DOM 노드로 만들어 HTML 해석을 하지 않는다). */
function codeSpans(text) {
  const frag = document.createDocumentFragment();
  String(text ?? "").split(/(`[^`]+`)/).forEach((part) => {
    if (!part) return;
    if (/^`[^`]+`$/.test(part)) frag.append(el("code", { text: part.slice(1, -1) }));
    else frag.append(document.createTextNode(part));
  });
  return frag;
}

/* 출처 배지 문구. 항목 메타데이터는 웹 화면에서 "항목 정보"로 줄여 쓴다. */
function sourceLabel(type) {
  if (type === "item") return "항목 정보";
  return App.T.source_type[type] || type;
}

/* 근거 목록 (번호, 출처 종류 배지, 제목, 섹션, 원문 링크). idPrefix 로 본문 [근거 n] 앵커와 연결한다. */
function evidenceNode(evidence, idPrefix, headerTemplate) {
  const T = App.T;
  const box = el("details", { class: "evidence", open: true });
  box.append(el("summary", { text: fmt(headerTemplate || T.evidence_header, { n: evidence.length }) }));
  const ol = el("ol");
  for (const ev of evidence) {
    const li = el("li", { class: "card", id: `${idPrefix}-${ev.n}` });
    li.append(el("span", { class: "ev-num", text: `[${ev.n}]` }));
    li.append(el("span", { class: `badge ${ev.source_type}`, text: sourceLabel(ev.source_type) }));
    li.append(document.createTextNode(ev.title || ""));
    if (ev.section) {
      const sec = el("span", { class: "caption" }, " · ");
      sec.append(codeSpans(ev.section));
      li.append(sec);
    }
    if (ev.url) { li.append(document.createTextNode(" · ")); li.append(externalLink(ev.url, T.evidence_link)); }
    ol.append(li);
  }
  box.append(ol);
  return box;
}

function renderNav(current) {
  const T = App.T;
  const nav = el("header", { class: "topnav" },
    el("span", { class: "brand" }, el("span", { class: "logo", "aria-hidden": "true", text: "FT" }), T.app_title),
    el("nav", {},
      el("a", { href: "index.html", "aria-current": current === "chat" ? "page" : null, text: T.tab_chat }),
      el("a", { href: "explore.html", "aria-current": current === "explore" ? "page" : null, text: T.condition.title }),
      el("a", { href: "research.html", "aria-current": current === "research" ? "page" : null, text: T.research.title })));
  document.body.prepend(nav);
}

/* [근거 n] 링크: 접힌 근거 목록을 펼치고 해당 항목으로 이동해 잠깐 강조한다. */
if (typeof document !== "undefined") {
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a.cite");
    if (!a) return;
    const target = document.getElementById(a.getAttribute("href").slice(1));
    if (!target) return;
    e.preventDefault();
    const details = target.closest("details");
    if (details) details.open = true;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.remove("flash");
    void target.offsetWidth; // 같은 항목을 다시 눌러도 강조가 다시 보이게
    target.classList.add("flash");
  });
}

async function loadCommon() {
  App.T = await getJSON("/api/i18n");
  document.title = App.T.app_title;
  return App.T;
}

/* 키 없음·색인 없음 안내. 반환: 막혔으면 true */
function renderStatusNotices(container, status) {
  const T = App.T;
  let blocked = false;
  if (status.api_key !== "ok") { showNotice(container, "warn", T.missing_key); blocked = true; }
  if (!status.items) { showNotice(container, "warn", T.empty_index); blocked = true; }
  return blocked;
}
