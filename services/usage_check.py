"""사용 조건 점검표 (F2010, 프롬프트 U).

근거: 항목 메타데이터 1개 + 모델 카드에서 점검 항목별 고정 검색어로 찾은 청크 (중복 제거 후 최대 usage_check.card_k 개).
모델 고유 조건만 다루므로 위키 문서는 쓰지 않는다 (design/prompts.md U).
출력: 점검 항목마다 근거에 적힌 내용, 사용한 근거 번호, 확인 여부. 라이선스 가부 판단은 하지 않는다.
"""
import time
from typing import Literal

from pydantic import BaseModel

from common import perf
from common.config import fill, prompt, setting
from common.llm import invoke_structured, model_name
from data_prep.index_text import item_chunk_id
from data_prep.indexing import ensure_card_indexed
from rag.evidence import format_blocks, make_evidence
from vectorstore import store

# design/prompts.md U의 "근거 수집" 예시 검색어 + 나머지 점검 항목용 (모델 카드가 영어라 영어로 검색)
ASPECT_QUERIES = {
    "license": "license terms commercial use",
    "gated": "access request agree to license terms",
    "languages": "supported languages",
    "context": "context length",
    "modality": "image input",
    "intended_use": "intended use",
    "limitations": "limitations risks bias",
}
PER_QUERY_K = 2

Aspect = Literal["license", "gated", "languages", "context", "modality", "intended_use", "limitations"]


class UsageRow(BaseModel):
    aspect: Aspect
    finding: str
    evidence_ids: list[int]
    status: Literal["confirmed", "not_in_documents"]


class UsageCheck(BaseModel):
    """점검 항목별 결과"""
    rows: list[UsageRow]


def gather_evidence(model_id):
    ensure_card_indexed(model_id)
    found = store.get_by_ids(store.ITEMS, [item_chunk_id(model_id)])
    chunks, seen = [], set()
    max_chunks = setting("usage_check.card_k")
    where = {"$and": [{"model_id": model_id}, {"doc_type": "model_card"}]}
    for q in ASPECT_QUERIES.values():
        for c in store.search(store.DOCS, q, k=PER_QUERY_K, where=where):
            if c["id"] not in seen and len(chunks) < max_chunks:
                seen.add(c["id"])
                chunks.append(c)
    return make_evidence(found[0] if found else None, chunks)


def build_usage_check(model_id):
    """반환: {rows: [...], evidence: [...]} — rows 의 evidence_ids 는 실제 있는 근거 번호만 남긴다."""
    evidence = gather_evidence(model_id)
    t = time.perf_counter()
    out = invoke_structured("LLM_ANSWER", UsageCheck, fill(prompt("usage_check"), evidence_blocks=format_blocks(evidence)),
                            "U usage_check")
    perf.record_llm("U_usage_check", model_name("LLM_ANSWER"), out["raw"].usage_metadata, time.perf_counter() - t)
    if out["parsed"] is None:
        raise ValueError("점검표 결과를 해석하지 못함")
    valid = {ev["n"] for ev in evidence}
    rows = [{**r.model_dump(), "evidence_ids": [n for n in r.evidence_ids if n in valid]} for r in out["parsed"].rows]
    return {"rows": rows, "evidence": evidence, "usage": out["raw"].usage_metadata or {}}
