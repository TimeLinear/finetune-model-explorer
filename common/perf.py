"""성능 계측 (NF2001 조사용). 질문 1건마다 단계별 소요 시간과 LLM 호출 정보를 logs/perf.jsonl 에 한 줄로 남긴다.

동작은 바꾸지 않고 시간만 잰다. 진행 중인 계측이 없으면 아무것도 기록하지 않는다.
- start_trace(...) 로 시작, finish_trace() 로 한 줄 기록
- with step("이름"): 구간 측정 (같은 이름이 여러 번 나오면 합산하고 횟수도 남긴다)
- record_llm(용도, 작업 키, usage, 소요 시간): LLM 호출 1건
환경 변수 PERF_LABEL 이 있으면 기록에 함께 남긴다 (측정 조합 구분용).

요청 단위 기록 (웹 화면): start_request_trace / finish_request_trace. 기록을 contextvars 에 두므로 동시 요청끼리
섞이지 않는다. 같은 컨텍스트(와 그 복사본: LangGraph 노드 스레드, copy_context 로 넘긴 스레드)에서만 보인다.
요청 기록이 있으면 그쪽을, 없으면 프로세스 전역 기록(Streamlit 경로)을 쓴다. 기록 한 줄의 형식은 같다.
"""
import contextvars
import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from common.config import LOG_DIR

PERF_PATH = LOG_DIR / "perf.jsonl"
_lock = threading.Lock()
_current = {"trace": None}  # Streamlit 실행 스레드와 LangGraph 실행 스레드가 달라도 같은 기록을 쓰도록 프로세스 전역
_request_trace = contextvars.ContextVar("perf_request_trace", default=None)


def _new_trace(mode, meta):
    return {"mode": mode, "label": os.environ.get("PERF_LABEL"), "meta": meta, "events": [], "llm_calls": [],
            "t0": time.perf_counter(), "started_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")}


def start_trace(mode, **meta):
    trace = _new_trace(mode, meta)
    _current["trace"] = trace
    return trace


def start_request_trace(mode, **meta):
    """요청 하나의 기록을 이 컨텍스트에 둔다 (프로세스 전역 기록은 건드리지 않는다)."""
    trace = _new_trace(mode, meta)
    _request_trace.set(trace)
    return trace


def current():
    trace = _request_trace.get()
    return trace if trace is not None else _current["trace"]


def add_event(name, seconds, **extra):
    trace = current()
    if trace is not None:
        with _lock:
            trace["events"].append({"step": name, "sec": round(seconds, 4), **extra})


@contextmanager
def step(name, **extra):
    t = time.perf_counter()
    try:
        yield
    finally:
        add_event(name, time.perf_counter() - t, **extra)


def record_llm(purpose, model, usage, seconds, **extra):
    trace = current()
    if trace is not None:
        usage = usage or {}
        with _lock:
            trace["llm_calls"].append({"purpose": purpose, "model": model, "input_tokens": usage.get("input_tokens"),
                                       "output_tokens": usage.get("output_tokens"), "sec": round(seconds, 3), **extra})


def finish_trace(**meta):
    trace = _current["trace"]
    if trace is None:
        return None
    _current["trace"] = None
    return _write(trace, meta)


def finish_request_trace(trace, **meta):
    """start_request_trace 로 시작한 기록을 한 줄로 남기고 이 컨텍스트에서 지운다."""
    if _request_trace.get() is trace:
        _request_trace.set(None)
    return _write(trace, meta)


def _write(trace, meta):
    trace["meta"].update(meta)
    trace["total_sec"] = round(time.perf_counter() - trace.pop("t0"), 3)
    totals = {}
    for e in trace["events"]:
        s = totals.setdefault(e["step"], {"sec": 0.0, "count": 0})
        s["sec"] = round(s["sec"] + e["sec"], 4)
        s["count"] += 1
    trace["steps"] = totals
    LOG_DIR.mkdir(exist_ok=True)
    with _lock, PERF_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(trace, ensure_ascii=False) + "\n")
    return trace
