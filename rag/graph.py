"""LangGraph RAG 파이프라인: retrieve → generate 두 노드 (F2006, F2007).

retrieve
- 선택 모델의 items 청크를 항상 [근거 1] 로 넣는다 (retrieve.item_always).
- 아직 카드가 색인되지 않은 모델이면 ensure_card_indexed 를 즉석 호출한다.
- docs 를 출처별로 따로 검색한다 (design/collections.md 4절, design/retrieval-and-ui.md): 모델 카드(doc_type=model_card)는 P1 의 영어 문구 card_query_en 으로
  retrieve.card_k 개, 위키(doc_type=wiki)는 원래 질문으로 retrieve.wiki_k 개. 둘 다 model_id 필터.
  한국어 질문으로 함께 검색하면 한국어 위키 청크에 끌려 영어 카드 청크가 빠지는 현상이 있었다.
  search_type=mmr 이면 출처별로 fetch_k=retrieve.mmr_fetch_k, 결과 수는 card_k / wiki_k 그대로.
  retrieve.card_query_mode=rrf 이면 카드는 card_query_en 과 원래 질문으로 각각 retrieve.rrf_candidates 개씩 검색해
  RRF(점수 = Σ 1/(rrf_k + 순위))로 합친 뒤 상위 card_k 개를 고른다 (P1 문구 하나에 결과가 좌우되는 것을 줄이기 위해).
- 항목 → 카드 → 위키 순으로 합쳐 청크 ID 로 중복 제거 후 번호를 매긴다. 위키가 모자라도 카드로 채우지 않는다.
generate
- 프롬프트 P3(answer.txt) + 같은 모델의 최근 대화 answer.history_turns 턴 + 근거·질문.
- 답변에서 [근거 n] 을 찾아 실제 인용된 근거만 남긴다. 하나도 없으면 no_citation=True.
"""
import time
from functools import lru_cache
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from common import perf
from common.config import fill, labels, prompt, setting, texts
from common.llm import get_llm, model_name
from data_prep.index_text import item_chunk_id
from data_prep.indexing import ensure_card_indexed
from data_prep.wiki import card_query_for
from rag.evidence import cited_evidence, format_blocks, make_evidence, strip_citations
from vectorstore import store


class RagState(TypedDict, total=False):
    model_id: str
    question: str
    card_query_en: str  # 없으면 retrieve 에서 P1 결과(질문별 저장분)를 쓴다
    history: list[dict]  # [{role, content}] 같은 모델의 이전 대화
    card_status: str  # done / indexed / failed
    evidence: list[dict]
    answer: str
    cited: list[dict]
    no_citation: bool
    usage: dict[str, Any]


def retrieve(state: RagState) -> RagState:
    mid = state["model_id"]
    try:
        with perf.step("ensure_card_indexed(retrieve)"):
            card_status = ensure_card_indexed(mid)
    except Exception:
        card_status = "failed"
    item_chunk = None
    if setting("retrieve.item_always"):
        with perf.step("item_chunk_get"):
            found = store.get_by_ids(store.ITEMS, [item_chunk_id(mid)])
        item_chunk = found[0] if found else None
    card_query = state.get("card_query_en")
    if not card_query:
        try:
            card_query = card_query_for(mid, state["question"])
        except Exception:  # P1 실패 시 원래 질문으로 카드를 검색한다
            card_query = state["question"]
    with perf.step("card_vector_search"):
        cards = search_cards(mid, state["question"], card_query)
    with perf.step("wiki_vector_search"):
        wikis = search_source(mid, "wiki", state["question"], setting("retrieve.wiki_k"))
    with perf.step("evidence_assembly"):
        evidence = make_evidence(item_chunk, cards + wikis)
    return {"card_status": card_status, "card_query_en": card_query, "evidence": evidence}


def search_cards(model_id, question, card_query):
    """모델 카드 청크 card_k 개. 검색 방식은 retrieve.card_query_mode (single / rrf)."""
    k = setting("retrieve.card_k")
    mode = setting("retrieve.card_query_mode")
    if mode == "single":
        return search_source(model_id, "model_card", card_query, k)
    if mode != "rrf":
        raise ValueError(f"지원하지 않는 retrieve.card_query_mode: {mode}")
    scores, chunks = {}, {}
    for query in dict.fromkeys([card_query, question]):  # 같은 문구면 한 번만
        for rank, c in enumerate(search_source(model_id, "model_card", query, setting("retrieve.rrf_candidates")), 1):
            scores[c["id"]] = scores.get(c["id"], 0.0) + 1.0 / (setting("retrieve.rrf_k") + rank)
            chunks.setdefault(c["id"], c)
    ranked = sorted(scores, key=lambda cid: -scores[cid])  # 동점이면 먼저 나온 순서 (sorted 는 안정 정렬)
    return [chunks[cid] for cid in ranked[:k]]


def search_source(model_id, doc_type, query, k):
    if k <= 0:
        return []
    return store.search(store.DOCS, query, k=k, where={"$and": [{"model_id": model_id}, {"doc_type": doc_type}]},
                        search_type=setting("retrieve.search_type"), fetch_k=setting("retrieve.mmr_fetch_k"),
                        lambda_mult=setting("retrieve.mmr_lambda"))


def message_text(content):
    """LLM 응답 내용에서 답변 글자만. 내용이 블록 목록이면 text 블록과 문자열 조각만 잇고 thinking 같은 블록은 뺀다.
    (스트리밍으로 받은 응답을 합치면 text 조각이 블록이 아니라 문자열로 목록에 들어온다)"""
    if isinstance(content, str):
        return content
    return "".join(p if isinstance(p, str) else p.get("text", "") for p in content
                   if isinstance(p, str) or (isinstance(p, dict) and p.get("type", "text") == "text"))


def build_messages(state):
    lang = setting("answer.lang")
    system = fill(prompt("answer"), answer_lang_name=labels()["language"].get(lang, lang))
    turns = setting("answer.history_turns")
    history = (state.get("history") or [])[-2 * turns:] if turns else []
    msgs = [SystemMessage(system)]
    for h in history:
        if h["role"] == "user":
            msgs.append(HumanMessage(h["content"]))
        else:
            # 근거 번호는 질문마다 새로 매기므로, 지난 답변의 [근거 n] 은 이번 근거 목록과 맞지 않는다. 표기를 지우고 넘긴다.
            msgs.append(AIMessage(strip_citations(h["content"])))
    msgs.append(HumanMessage(fill(texts()["answer_user_message"],
                                  evidence_blocks=format_blocks(state["evidence"]), question=state["question"])))
    return msgs


def generate(state: RagState) -> RagState:
    msgs = build_messages(state)
    t = time.perf_counter()
    with perf.step("answer_generation"):  # 첫 글자 시각은 stream_answer 의 answer_first_token
        res = None  # stream 으로 받아 합친다: 결과는 invoke 와 같고, 그래프를 stream 으로 돌리면 토큰이 바로 화면으로 간다
        for chunk in get_llm("LLM_ANSWER").stream(msgs):
            res = chunk if res is None else res + chunk
    perf.record_llm("answer", model_name("LLM_ANSWER"), res.usage_metadata, time.perf_counter() - t)
    answer = message_text(res.content)
    cited = cited_evidence(answer, state["evidence"])
    return {"answer": answer, "cited": cited, "no_citation": not cited, "usage": res.usage_metadata or {}}


@lru_cache
def get_graph():
    g = StateGraph(RagState)
    g.add_node("retrieve", retrieve)
    g.add_node("generate", generate)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", END)
    return g.compile()


def initial_state(model_id, question, history=None, card_query_en=None):
    state = {"model_id": model_id, "question": question, "history": history or []}
    if card_query_en:
        state["card_query_en"] = card_query_en
    return state


def answer_question(model_id, question, history=None, card_query_en=None):
    return get_graph().invoke(initial_state(model_id, question, history, card_query_en))




def stream_answer(model_id, question, history=None, card_query_en=None):
    """답변 생성 토큰을 나오는 대로 ("token", 텍스트) 로 내보내고, 끝나면 ("final", 최종 상태) 를 내보낸다.
    그래프 구성(retrieve → generate)과 결과는 answer_question 과 같다. 인용 근거 확인은 최종 상태로 한다."""
    final, retrieved_at, first = None, None, None
    for mode, data in get_graph().stream(initial_state(model_id, question, history, card_query_en),
                                         stream_mode=["messages", "values"]):
        if mode == "values":
            final = data
            if retrieved_at is None and "evidence" in data:
                retrieved_at = time.perf_counter()
            continue
        chunk, meta = data
        if meta.get("langgraph_node") != "generate":
            continue
        text = message_text(getattr(chunk, "content", ""))
        if text:
            if first is None:
                first = time.perf_counter()
                perf.add_event("answer_first_token", first - (retrieved_at or first))
            yield "token", text
    yield "final", final
