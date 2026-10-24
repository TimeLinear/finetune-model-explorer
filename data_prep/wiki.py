"""추가 문서 수집: 한국어 위키백과 (F2003, F2004, NF2002, NF2006, design/collections.md 3절).

질문 시: 검색어 추출(P1) → 검색어마다 후보(제목·요약) 수집 → 후보 선별(P2) → 선택 문서만 본문 수집 → docs 컬렉션 색인(doc_type=wiki).
- 이미 수집한 검색어는 다시 수집하지 않는다. 다른 모델 질문에서 수집한 검색어라면 저장해 둔 선별 결과·본문으로
  이 모델 범위에만 청크를 복제해 넣는다 (design/collections.md 5절 "여러 모델에 걸친 문서는 모델마다 청크를 복제").
- 수집 기록(검색어, 후보, 선택/제외와 이유)을 남겨 검증(reports/evaluation.md)에 쓴다.
- User-Agent 에 WIKI_CONTACT 를 넣는다. 값은 로그·화면에 남기지 않는다.
- 모델 카드(선택 항목 자체 문서)는 이 선별을 거치지 않고 항상 색인된다 (data_prep/indexing.py).
"""
import contextvars
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
from pydantic import BaseModel, Field

from common import perf
from common.config import CHROMA_DIR, fill, prompt, setting
from common.llm import invoke_structured, model_name
from data_prep.index_text import item_chunk_id
from vectorstore import store
from vectorstore.docs_index import SourceDoc, index_document

LOG_PATH = CHROMA_DIR / "wiki_log.json"
PAGES_DIR = CHROMA_DIR / "wiki_pages"
USER_AGENT = "finetune-model-explorer/0.1"
P2_PROMPT_VERSION = "v0.3"  # docs/design/prompts.md 의 P2 버전 (설명 주석을 프롬프트 밖으로)
P1_PROMPT_VERSION = "v0.3"  # docs/design/prompts.md 의 P1 버전 (card_query_en 추가)
SNIPPET_CHARS = 200
MAX_QUERIES = 3
_lock = threading.Lock()
_last_request = [0.0]


class SearchQuery(BaseModel):
    query: str
    reason: str


class QueryExtraction(BaseModel):
    """위키백과 검색어 0~3개와 모델 카드 검색용 영어 문구"""
    queries: list[SearchQuery] = Field(description="0~3개 (위키백과 검색용)")
    card_query_en: str = Field(description="모델 카드 검색용 영어 문구 1개")


class Decision(BaseModel):
    index: int
    selected: bool
    reason: str


class DocSelection(BaseModel):
    """후보마다 선택 여부와 이유"""
    decisions: list[Decision]


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def api_url():
    return f"https://{setting('wiki.lang')}.wikipedia.org/w/api.php"


def headers():
    contact = os.environ.get("WIKI_CONTACT")
    return {"User-Agent": f"{USER_AGENT} ({contact})" if contact else USER_AGENT}


def wiki_get(params):
    """호출 간격(wiki.request_interval_sec)과 재시도(http.max_retries)를 지킨다 (NF2006)."""
    params = {**params, "format": "json", "formatversion": 2}
    for attempt in range(setting("http.max_retries") + 1):
        with _lock:
            wait = setting("wiki.request_interval_sec") - (time.time() - _last_request[0])
            if wait > 0:
                time.sleep(wait)
            _last_request[0] = time.time()
        try:
            r = requests.get(api_url(), params=params, headers=headers(), timeout=30)
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After") or 10))
        elif r.status_code < 500:
            break
        else:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("위키백과 API 요청 실패")


def search_candidates(query):
    """검색 결과 후보: [{pageid, title, summary}] (본문 받기 전, 제목·요약만)"""
    with perf.step("wiki_search_api"):
        data = wiki_get({"action": "query", "generator": "search", "gsrsearch": query,
                         "gsrlimit": setting("wiki.candidates_per_query"), "prop": "extracts",
                         "exintro": 1, "explaintext": 1, "exlimit": "max"})
    pages = sorted((data.get("query") or {}).get("pages") or [], key=lambda p: p.get("index", 0))
    return [{"pageid": p["pageid"], "title": p["title"],
             "summary": re.sub(r"\s+", " ", p.get("extract") or "")[:SNIPPET_CHARS]} for p in pages]


def wiki_to_markdown(text):
    """'== 제목 ==' 형식 소제목을 마크다운 소제목으로 바꿔 청킹에서 section 으로 쓴다."""
    def repl(m):
        level = min(len(m.group(1)), 3)
        return f"{'#' * level} {m.group(2).strip()}"
    return re.sub(r"^(={2,6})\s*(.+?)\s*=+\s*$", repl, text, flags=re.M)


def fetch_page(pageid):
    """본문·원문 URL·리비전. 받은 문서는 캐시해 다시 받지 않는다."""
    path = PAGES_DIR / f"{pageid}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    with perf.step("wiki_fetch_page"):
        data = wiki_get({"action": "query", "prop": "extracts|info|revisions", "pageids": pageid, "explaintext": 1,
                         "exsectionformat": "wiki", "inprop": "url", "rvprop": "ids"})
    p = data["query"]["pages"][0]
    page = {"pageid": pageid, "title": p["title"], "url": p.get("fullurl"),
            "revision": str((p.get("revisions") or [{}])[0].get("revid", "")),
            "text": wiki_to_markdown(p.get("extract") or ""), "fetched_at": now_iso()}
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
    return page


def load_log():
    if LOG_PATH.exists():
        return json.loads(LOG_PATH.read_text(encoding="utf-8"))
    return {"queries": {}, "indexed": {}}


def save_log(log):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def query_key(query):
    return re.sub(r"\s+", " ", query.strip()).casefold()


def extract_queries(model_id, question, template=None):
    """P1. template 을 주면 앱 프롬프트 파일 대신 그 문안을 쓴다 (프롬프트 후보 평가용)."""
    found = store.get_by_ids(store.ITEMS, [item_chunk_id(model_id)])
    item_text = found[0]["text"] if found else model_id
    t = time.perf_counter()
    out = invoke_structured("LLM_SMALL", QueryExtraction,
                            fill(template or prompt("query_extract"), item_text=item_text, question=question),
                            "P1 query_extract")
    perf.record_llm("P1_query_extract", model_name("LLM_SMALL"), out["raw"].usage_metadata, time.perf_counter() - t)
    if out["parsed"] is None:
        raise ValueError("검색어 추출 결과를 해석하지 못함")
    parsed = out["parsed"]
    return QueryExtraction(queries=parsed.queries[:MAX_QUERIES], card_query_en=parsed.card_query_en)  # 규칙 4: 최대 3개


def select_candidates(model_id, question, candidates):
    lines = "\n".join(f"[{i}] {c['title']} — {c['summary']}" for i, c in enumerate(candidates))
    t = time.perf_counter()
    with perf.step("P2"):
        out = invoke_structured("LLM_SMALL", DocSelection,
                                fill(prompt("doc_select"), model_id=model_id, question=question, candidates=lines),
                                "P2 doc_select")
    perf.record_llm("P2_doc_select", model_name("LLM_SMALL"), out["raw"].usage_metadata, time.perf_counter() - t)
    if out["parsed"] is None:
        raise ValueError("후보 선별 결과를 해석하지 못함")
    by_index = {d.index: d for d in out["parsed"].decisions}
    return [{**c, "selected": bool(by_index.get(i) and by_index[i].selected),
             "reason": by_index[i].reason if i in by_index else "판단 결과 없음"} for i, c in enumerate(candidates)]


def index_page_for_model(model_id, page, query):
    return index_document(SourceDoc(
        model_id=model_id, doc_type="wiki", doc_id=f"wiki:{page['pageid']}", title=page["title"], url=page["url"],
        text=page["text"], doc_lang=setting("wiki.lang"), revision=page["revision"], extra={"search_query": query}))


def question_key(model_id, question):
    """P1 저장 키: 모델 + P1 프롬프트 버전 + P1 모델(LLM_SMALL) + 질문. 프롬프트나 P1 모델이 바뀌면 새로 추출한다."""
    return f"{model_id}|{P1_PROMPT_VERSION}|{model_name('LLM_SMALL')}|{query_key(question)}"


def extraction_for(model_id, question, log):
    """같은 키(question_key)면 저장해 둔 P1 결과를 다시 쓴다 (P1 출력이 매번 조금씩 달라 재수집이 생기는 것을 막는다).

    card_query_en 이 없는 이전 기록이면 P1 을 다시 불러 card_query_en 만 채우고, 위키 검색어는 저장된 것을 유지한다.
    """
    qkey = question_key(model_id, question)
    saved = log.setdefault("questions", {}).get(qkey)
    if saved is None or not saved.get("card_query_en"):
        ext = extract_queries(model_id, question)
        if saved is None:
            saved = log["questions"][qkey] = {"model_id": model_id, "question": question, "extracted_at": now_iso(),
                                              "prompt_version": P1_PROMPT_VERSION, "p1_model": model_name("LLM_SMALL"),
                                              "queries": [q.model_dump() for q in ext.queries]}
        saved["card_query_en"] = ext.card_query_en
    return QueryExtraction(queries=[SearchQuery(**q) for q in saved["queries"]], card_query_en=saved["card_query_en"])


def card_query_for(model_id, question):
    """모델 카드 검색용 영어 문구 (retrieve 노드에서 사용)."""
    log = load_log()
    ext = extraction_for(model_id, question, log)
    save_log(log)
    return ext.card_query_en


def search_and_select(model_id, question, query):
    """처음 보는 검색어 하나: 위키 검색(후보 제목·요약) → P2 선별. 반환: 수집 기록(qlog)"""
    candidates = search_candidates(query)
    decided = select_candidates(model_id, question, candidates) if candidates else []
    return {"query": query, "first_model_id": model_id, "question": question, "searched_at": now_iso(),
            "select_model": model_name("LLM_SMALL"), "prompt_version": P2_PROMPT_VERSION, "candidates": decided}


def needs_reselect(qlog):
    """선별 결과가 0건이고, 그때의 선별 모델이나 P2 프롬프트 버전이 지금과 다르면 다시 수집한다.
    1건 이상 고른 검색어는 다시 수집하지 않는다 (NF2002). 0건이어도 같은 모델·같은 버전이면 다시 부르지 않는다."""
    if any(c.get("selected") for c in qlog.get("candidates", [])):
        return False
    return qlog.get("select_model") != model_name("LLM_SMALL") or qlog.get("prompt_version") != P2_PROMPT_VERSION


def keys_to_select(model_id, queries, log):
    """이번 질문에서 위키 검색·P2 선별을 (다시) 해야 하는 검색어: {key: 검색어}.
    처음 보는 검색어, 또는 선별 0건이라 needs_reselect 인 검색어."""
    keys = {}
    for q in queries:
        key = query_key(q.query)
        qlog = log["queries"].get(key)
        if qlog is not None and needs_reselect(qlog):
            keys.setdefault(key, q.query)
        elif qlog is None and f"{model_id}|{key}" not in log["indexed"]:
            keys.setdefault(key, q.query)
    return keys


def collect_for_question(model_id, question):
    """반환: {card_query_en, queries: [{query, reason, status}], new_titles: [...]}
    status: collected / reselected(선별 0건 재시도) / reused / cached / failed

    처음 보는 검색어들의 "위키 검색 → P2 선별"은 wiki.p2_concurrency 개까지 동시에 처리한다
    (위키 API 호출 간격 규칙은 wiki_get 의 잠금으로 그대로 지킨다). 본문 수집·색인과 기록은 순서대로 한다."""
    log = load_log()
    with perf.step("P1"):  # 같은 질문이면 저장분을 다시 써서 LLM 호출 없이 끝난다
        ext = extraction_for(model_id, question, log)
    save_log(log)
    report = {"card_query_en": ext.card_query_en, "queries": [], "new_titles": []}

    new_keys = keys_to_select(model_id, ext.queries, log)
    selected = {}
    if new_keys:
        with perf.step("wiki_search_select_parallel"),                 ThreadPoolExecutor(max_workers=max(1, setting("wiki.p2_concurrency"))) as pool:
            # 성능 기록(요청 단위)이 작업 스레드에도 보이도록 컨텍스트를 복사해 넘긴다 (전역 기록 경로는 그대로)
            futures = {key: pool.submit(contextvars.copy_context().run, search_and_select, model_id, question, query)
                       for key, query in new_keys.items()}
            for key, fut in futures.items():
                try:
                    selected[key] = fut.result()
                except Exception as e:  # 검색어 하나의 실패는 그 검색어만 실패로 남긴다
                    selected[key] = e

    for q in ext.queries:
        key = query_key(q.query)
        entry = {"query": q.query, "reason": q.reason}
        pair = f"{model_id}|{key}"
        if pair in log["indexed"] and key not in selected:
            report["queries"].append({**entry, "status": "cached"})  # NF2002: 이 모델에서 이미 수집한 검색어
            continue
        try:
            qlog = log["queries"].get(key)
            status = "reused"
            if key in selected:  # 처음 보는 검색어, 또는 선별 0건 재시도 (위에서 병렬로 검색·선별해 둠)
                result = selected[key]
                if isinstance(result, Exception):
                    raise result
                if qlog is not None:  # 재시도: 이전 선별 정보를 남긴다
                    result["previous"] = {k: qlog.get(k) for k in ("select_model", "prompt_version", "searched_at")}
                status = "reselected" if qlog is not None else "collected"
                qlog = log["queries"][key] = result
            titles = []
            for c in qlog["candidates"]:
                if c["selected"]:
                    page = fetch_page(c["pageid"])
                    if page["text"].strip():
                        index_page_for_model(model_id, page, q.query)
                        titles.append(page["title"])
            log["indexed"][pair] = {"model_id": model_id, "query": q.query, "titles": titles, "indexed_at": now_iso()}
            report["queries"].append({**entry, "status": status})
            report["new_titles"] += titles
        except Exception as e:  # 위키 수집 실패는 답변을 막지 않는다 (모델 카드 근거로 답한다)
            report["queries"].append({**entry, "status": "failed", "error": type(e).__name__})
        finally:
            save_log(log)
    return report
