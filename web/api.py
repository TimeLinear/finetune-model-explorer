"""웹 화면 백엔드 (F2013, FastAPI). Streamlit 화면(app.py)과 별도로 두고, 같은 모듈을 불러 쓴다.

- 서버는 대화 상태를 갖지 않는다. 모델별 대화 기록은 브라우저가 들고 있다가 질문할 때 함께 보낸다.
  기록 속 [근거 n] 표기는 기존 규칙대로 서버(rag.graph.build_messages)에서 지운다.
- 질의응답 흐름은 app.py 와 같다: 카드 색인 확인 → 위키 수집 → retrieve/generate 스트리밍 → 인용 근거만 표시.
- 화면·응답에는 짧은 안내 문구(i18n)만 보내고, 오류 상세·프롬프트·키는 logs/app.log 에만 남긴다 (NF2004).
- 성능·토큰 기록은 요청 단위(common.perf.start_request_trace)로 logs/perf.jsonl 에 한 줄씩 남긴다 (mode: web_chat /
  web_explore / web_usage_check). 질의응답은 전용 스레드 하나에서 끝까지 실행해 요청 기록이 단계 사이에 끊기지 않게 한다.

실행 (프로젝트 루트): .venv\\Scripts\\python.exe -m uvicorn web.api:app --host 127.0.0.1 --port 8000
"""
import contextvars
import json
from contextlib import asynccontextmanager
import queue
import threading
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from common import last_asked, perf
from common.config import labels, setting, texts
from common.llm import missing_api_keys, profile_name
from common.logs import get_logger
from data_prep.index_text import item_summary_text
from data_prep.indexing import ensure_card_indexed
from data_prep.items import items_by_id
from data_prep.summaries import latest_summaries
from data_prep.wiki import collect_for_question
from rag.evidence import display_fields
from rag.graph import stream_answer
from services.condition_search import search_by_conditions
from services.usage_check import build_usage_check
from vectorstore import store
from vectorstore.embeddings import get_embeddings

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_QUESTION_CHARS = 2000
MAX_HISTORY_CHARS = 8000  # 기록 메시지 1건의 최대 길이 (그 이상은 자른다)

T = texts()
log = get_logger("web")


@asynccontextmanager
async def lifespan(_app):
    """임베딩 모델을 서버 시작 때 한 번 적재한다 (첫 질문에서 약 8초가 빠진다. app.py 의 preload_embeddings 와 같은 목적)."""
    get_embeddings()
    yield


app = FastAPI(title="finetune-model-explorer", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


class ChatRequest(BaseModel):
    model_id: str
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    history: list[dict] = Field(default_factory=list)


class ExploreRequest(BaseModel):
    request: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)


class UsageRequest(BaseModel):
    model_id: str


def error_response(message, status_code):
    return JSONResponse({"error": message}, status_code=status_code)


def index_counts():
    return {"items": store.count(store.ITEMS), "docs": store.count(store.DOCS)}


def blocked_message():
    """API 키 없음·색인 없음이면 화면 안내 문구, 아니면 None (app.py 의 blocked 와 같은 조건)."""
    if missing_api_keys():
        return T["missing_key"]
    if store.count(store.ITEMS) == 0:
        return T["empty_index"]
    return None


def modalities(it):
    return list(it.get("input_modalities") or [])


@app.get("/api/status")
def status():
    return {**index_counts(), "api_key": "missing" if missing_api_keys() else "ok", "profile": profile_name(),
            "history_turns": setting("answer.history_turns")}


@app.get("/api/i18n")
def i18n():
    return texts()


@app.get("/api/models")
def models():
    """선택 상자와 필터에 필요한 필드만. 순서는 항목 파일 순서(Streamlit 선택 상자와 같음)."""
    L = labels()
    return {"labels": {"modality": L["modality"], "stage": L["stage"]},
            "models": [{"model_id": mid, "vendor": it.get("vendor"), "params_b": it.get("params_b"),
                        "input_modalities": modalities(it), "stage": it.get("stage"), "license": it.get("license")}
                       for mid, it in items_by_id().items()]}


@app.get("/api/models/{model_id:path}")
def model_detail(model_id: str):
    it = items_by_id().get(model_id)
    if not it:
        return error_response(T["error_generic"], 404)
    rec = latest_summaries().get(model_id) or {}
    return {"model_id": model_id, "vendor": it.get("vendor"), "params_b": it.get("params_b"),
            "license": it.get("license"), "input_modalities": modalities(it), "stage": it.get("stage"),
            "context": it.get("max_position_embeddings"), "downloads": it.get("downloads_30d_adj"),
            "card_url": it.get("card_url"), "summary": item_summary_text(rec), "highlights": rec.get("highlights") or []}


def clean_history(history):
    """브라우저가 보낸 기록에서 role 이 user/assistant 인 글만, 최근 answer.history_turns 턴만 남긴다."""
    turns = setting("answer.history_turns")
    out = [{"role": h["role"], "content": str(h.get("content", ""))[:MAX_HISTORY_CHARS]}
           for h in history if isinstance(h, dict) and h.get("role") in ("user", "assistant")]
    return out[-2 * turns:] if turns else []


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


_END = object()


def traced_stream(events, mode, **meta):
    """events(제너레이터)를 전용 스레드 하나에서 요청 기록(perf)과 함께 끝까지 돌리고, 나오는 이벤트를 그대로 넘긴다.
    StreamingResponse 는 제너레이터의 다음 값을 매번 다른 작업 스레드에서 꺼내므로, 그 안에서 바로 돌리면
    요청 기록(contextvars)이 단계 사이에 이어지지 않는다."""
    q = queue.Queue()

    def worker():
        trace = perf.start_request_trace(mode, **meta)
        try:
            for item in events:
                q.put(item)
        finally:
            perf.finish_request_trace(trace)
            q.put(_END)

    threading.Thread(target=contextvars.copy_context().run, args=(worker,), daemon=True).start()
    while (item := q.get()) is not _END:
        yield item


def chat_events(model_id, question, history):
    """이벤트: stage(진행 단계 문구) / token(답변 글자) / done(answer, evidence, no_citation, notes) / error(짧은 문구).
    app.py 의 질의응답 흐름과 같은 순서로 같은 함수를 부른다."""
    notes = []
    try:
        yield sse("stage", {"text": T["status_card"]})
        try:
            card = ensure_card_indexed(model_id)
        except Exception:  # 카드를 못 받아도 항목 메타데이터로 답한다
            log.exception("카드 색인 실패")
            card = "failed"
        if card == "failed":
            notes.append(T["card_fetch_failed"])
            yield sse("stage", {"text": T["card_fetch_failed"]})
        yield sse("stage", {"text": T["status_wiki"]})
        card_query, titles = None, []
        try:
            wiki = collect_for_question(model_id, question)
            card_query, titles = wiki["card_query_en"], wiki["new_titles"]
        except Exception:  # 위키 수집 실패는 답변을 막지 않는다
            log.exception("위키 수집 실패")
        text = T["status_wiki_done"].format(titles=", ".join(titles)) if titles else T["status_wiki_none"]
        yield sse("stage", {"text": text, "titles": titles})
        yield sse("stage", {"text": T["status_answer"]})
        final = None
        for kind, payload in stream_answer(model_id, question, history=history, card_query_en=card_query):
            if kind == "token":
                yield sse("token", {"text": payload})
            else:
                final = payload
        yield sse("done", {"answer": final["answer"], "evidence": [display_fields(ev) for ev in final["cited"]],
                           "no_citation": final["no_citation"], "notes": notes})
    except Exception:
        log.exception("웹 질의응답 실패")
        yield sse("error", {"text": T["error_generic"]})


@app.post("/api/chat")
def chat(req: ChatRequest):
    if req.model_id not in items_by_id():
        return error_response(T["error_generic"], 404)
    blocked = blocked_message()
    if blocked:
        return error_response(blocked, 503)
    question = req.question.strip()
    last_asked.record(req.model_id)  # 보호 기간 판정용 (실패해도 질의응답은 계속)
    events = chat_events(req.model_id, question, clean_history(req.history))
    return StreamingResponse(traced_stream(events, "web_chat", model_id=req.model_id, question=question),
                             media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/explore")
def explore(req: ExploreRequest):
    blocked = blocked_message()
    if blocked:
        return error_response(blocked, 503)
    trace = perf.start_request_trace("web_explore", request=req.request.strip())
    try:
        res = search_by_conditions(req.request.strip())
    except Exception:
        log.exception("조건 탐색 실패")
        perf.finish_request_trace(trace, error=True)
        return error_response(T["error_generic"], 500)
    perf.finish_request_trace(trace, results=len(res["results"]))
    summaries = latest_summaries()
    return {"candidates_count": res["candidates_count"],
            "filter": {k: v for k, v in res["filter"].items() if v not in (None, [], "", False)},
            "results": [{"model_id": r["model_id"], "params_b": r["metadata"].get("params_b"),
                         "input_modalities": [k[4:] for k, v in r["metadata"].items() if k.startswith("mod_") and v],
                         "license": r["metadata"].get("license"), "downloads": r["metadata"].get("downloads_30d_adj"),
                         "reason": r["reason"], "highlights": (summaries.get(r["model_id"]) or {}).get("highlights") or []}
                        for r in res["results"]]}


@lru_cache(maxsize=64)
def cached_usage_check(model_id, card_revision):
    """같은 모델·같은 카드 리비전의 점검표는 재사용한다 (design/retrieval-and-ui.md, app.py 의 cached_usage_check 와 같은 규칙)."""
    return build_usage_check(model_id)


@app.post("/api/usage-check")
def usage_check(req: UsageRequest):
    it = items_by_id().get(req.model_id)
    if not it:
        return error_response(T["error_generic"], 404)
    blocked = blocked_message()
    if blocked:
        return error_response(blocked, 503)
    trace = perf.start_request_trace("web_usage_check", model_id=req.model_id)
    try:
        result = cached_usage_check(req.model_id, it["card_revision"])
    except Exception:
        log.exception("점검표 생성 실패")
        perf.finish_request_trace(trace, error=True)
        return error_response(T["error_generic"], 500)
    perf.finish_request_trace(trace, rows=len(result["rows"]))
    used = {n for r in result["rows"] for n in r["evidence_ids"]}
    return {"rows": result["rows"], "evidence": [display_fields(ev) for ev in result["evidence"] if ev["n"] in used]}


FAVICON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#2b4a8b"/>'
               '<text x="16" y="22" font-family="monospace" font-size="15" font-weight="700" text-anchor="middle" '
               'fill="#fff">FT</text></svg>')


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """브라우저가 <link rel="icon"> 와 별도로 /favicon.ico 를 찾는 경우의 404 를 없앤다 (HTML 의 인라인 아이콘과 같은 그림)."""
    return Response(FAVICON_SVG, media_type="image/svg+xml", headers={"Cache-Control": "max-age=86400"})


# 정적 화면 (API 경로가 먼저 매칭되도록 마지막에 붙인다)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
