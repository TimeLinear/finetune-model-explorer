"""메인 페이지: 모델 질의응답 + 사용 조건 점검표 (F2002 표시·F2009·F2010·F2012, design/retrieval-and-ui.md).

실행: streamlit run app.py
"""
import time

_RERUN_T0 = time.perf_counter()  # 계측: 재실행 시작 시각 (Streamlit 은 이벤트마다 이 파일을 처음부터 다시 실행한다)

import streamlit as st  # noqa: E402

from common import perf  # noqa: E402
from common.config import texts  # noqa: E402
from common.logs import get_logger  # noqa: E402
from data_prep.index_text import item_summary_text  # noqa: E402
from data_prep.indexing import ensure_card_indexed  # noqa: E402
from data_prep.items import items_by_id  # noqa: E402
from data_prep.summaries import latest_summaries  # noqa: E402
from data_prep.wiki import collect_for_question  # noqa: E402
from rag.evidence import display_fields  # noqa: E402
from rag.graph import stream_answer  # noqa: E402
from services.usage_check import build_usage_check  # noqa: E402
from vectorstore.embeddings import get_embeddings  # noqa: E402
from ui.components import (index_counts, init_state, keys_missing, model_option_label,  # noqa: E402
                           render_assistant_extras, render_disclaimer, render_evidence_list, render_model_card,
                           show_error)

T = texts()
log = get_logger("app")
st.set_page_config(page_title=T["app_title"], layout="wide")


@st.cache_resource(show_spinner=False)
def preload_embeddings():
    """임베딩 모델을 앱 시작 때 한 번 적재해, 프로세스의 첫 질문에서 적재 시간(약 3초)이 빠지게 한다 (3-3)."""
    with perf.step("embedding_model_preload"):
        return get_embeddings()


preload_embeddings()
init_state()
ss = st.session_state
items = items_by_id()
summaries = latest_summaries()


def on_model_change():
    ss.selected_model_id = ss["_model_select"]


# ---- 사이드바: 모델 선택, 색인 수, 선택 모델 요약, 면책 ----
with st.sidebar:
    st.header(T["sidebar_title"])
    ss["_model_select"] = ss.selected_model_id  # 다른 페이지(조건 탐색)에서 고른 모델도 반영
    st.selectbox(T["select_label"], list(items), key="_model_select", format_func=model_option_label,
                 placeholder=T["select_placeholder"], on_change=on_model_change)
    counts = index_counts()
    st.caption(T["index_counts"].format(**counts))
    mid = ss.selected_model_id
    if mid:
        rec = summaries.get(mid)
        render_model_card(mid, item_summary_text(rec), (rec or {}).get("highlights"))
        if st.button(T["clear_chat"]):
            ss.chats[mid] = []
    st.divider()
    render_disclaimer()

st.title(T["app_title"])
st.caption(T["app_caption"])

missing = keys_missing()
if missing:
    st.warning(T["missing_key"])
if counts["items"] == 0:
    st.warning(T["empty_index"])
blocked = bool(missing) or counts["items"] == 0

if not mid:
    st.info(T["choose_model_first"])
    st.stop()

st.subheader(mid)
tab_chat, tab_usage = st.tabs([T["tab_chat"], T["tab_usage"]])

# ---- 탭 1: 질의응답 (F2009, F2012) ----
with tab_chat:
    history = ss.chats.setdefault(mid, [])
    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                render_assistant_extras(msg)

question = st.chat_input(T["chat_placeholder"], disabled=blocked)
if question:
    perf.start_trace("app", model_id=mid, question=question)
    perf.add_event("rerun_to_question_start", time.perf_counter() - _RERUN_T0)
    with tab_chat:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            notes = []
            status = None
            try:
                # 상태 표시를 연 채로 아래에 답변을 스트리밍하려고 with 문 대신 직접 연다 (끝나면 complete 로 바꾼다)
                status = st.status(T["status_working"], expanded=True)
                status.write(T["status_card"])
                try:
                    with perf.step("ensure_card_indexed"):
                        card = ensure_card_indexed(mid)
                except Exception as e:  # 카드를 못 받아도 항목 메타데이터로 답한다
                    show_error(e)
                    card = "failed"
                if card == "failed":
                    notes.append(T["card_fetch_failed"])
                    status.write(T["card_fetch_failed"])
                status.write(T["status_wiki"])
                card_query = None
                wiki = {}
                try:
                    with perf.step("wiki_collect_total"):
                        wiki = collect_for_question(mid, question)
                    titles, card_query = ", ".join(wiki["new_titles"]), wiki["card_query_en"]
                except Exception as e:  # 위키 수집 실패는 답변을 막지 않는다 (상세는 로그 파일)
                    log.exception("위키 수집 실패: %s", type(e).__name__)
                    titles = ""
                status.write(T["status_wiki_done"].format(titles=titles) if titles else T["status_wiki_none"])
                status.write(T["status_answer"])
                final = {}

                def answer_tokens():  # 답변을 나오는 대로 화면에 쓴다 (3-1). 인용 근거 목록은 끝난 뒤에 붙인다
                    for kind, payload in stream_answer(mid, question, card_query_en=card_query,
                                                       history=[{"role": m["role"], "content": m["content"]}
                                                                for m in history]):
                        if kind == "token":
                            yield payload
                        else:
                            final.update(payload)

                with perf.step("graph_total"):
                    st.write_stream(answer_tokens())
                status.update(label=T["status_done"], state="complete", expanded=False)
                out = final
                with perf.step("render"):  # 서버에서 화면 요소를 보내는 시간 (브라우저 그리기 시간은 포함하지 않음)
                    msg = {"role": "assistant", "content": out["answer"], "notes": notes,
                           "evidence": [display_fields(ev) for ev in out["cited"]], "no_citation": out["no_citation"]}
                    render_assistant_extras({**msg, "notes": []})
                history += [{"role": "user", "content": question}, msg]
                perf.finish_trace(card=card, wiki=[q.get("status") for q in wiki.get("queries", [])],
                                  cited=len(out["cited"]))
            except Exception as e:
                perf.finish_trace(error=type(e).__name__)
                if status is not None:
                    status.update(label=T["status_failed"], state="error", expanded=False)
                show_error(e)


# ---- 탭 2: 사용 조건 점검표 (F2010) ----
@st.cache_data(show_spinner=False)
def cached_usage_check(model_id, card_revision):
    """같은 모델·같은 카드 리비전의 점검표는 재사용한다 (design/retrieval-and-ui.md)."""
    return build_usage_check(model_id)


with tab_usage:
    st.caption(T["usage"]["intro"])
    U = T["usage"]
    if st.button(U["button"], disabled=blocked):
        try:
            with st.spinner(U["spinner"]):
                ss.setdefault("usage_checks", {})[mid] = cached_usage_check(mid, items[mid]["card_revision"])
        except Exception as e:
            show_error(e)
    result = ss.get("usage_checks", {}).get(mid)
    if result:
        st.table([{U["col_aspect"]: U["aspect"].get(r["aspect"], r["aspect"]),
                   U["col_finding"]: r["finding"],
                   U["col_evidence"]: " ".join(f"[{n}]" for n in r["evidence_ids"]) or "-",
                   U["col_status"]: U["status"].get(r["status"], r["status"])} for r in result["rows"]])
        used = {n for r in result["rows"] for n in r["evidence_ids"]}
        cited = [display_fields(ev) for ev in result["evidence"] if ev["n"] in used]
        if cited:
            render_evidence_list(cited, U["evidence_title"] + f" ({len(cited)})")
        else:
            st.caption("ⓘ " + T["no_citation"])
        render_disclaimer()
