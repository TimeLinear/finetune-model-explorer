"""조건 기반 항목 탐색 (F2011, 프롬프트 C1·C2, design/prompts-services.md 처리 흐름).

자연어 조건 → C1(필터·정렬 변환) → items 컬렉션 메타데이터 필터 + semantic_query 의미 검색(비어 있으면 필터만)
→ 후보 최대 condition.candidate_k 개 → sort_by 가 있으면 파이썬에서 정렬 → C2(최종 선별) → 맞는 모델만 limit 개.

C2 는 v0.4 부터 맞는 후보만 출력한다 (후보마다 match 를 쓰던 v0.3 은 후보 30개에서 출력 상한에 걸렸다).
출력은 코드에서 다시 검증한다: 후보에 없는 model_id 는 버리고, 중복을 없애고, 원래 후보 순서로 정렬하고, limit 에서 자른다.
"""
import time
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from common import perf
from common.config import fill, prompt, setting
from common.llm import invoke_structured, model_name
from data_prep.items import items_by_id
from vectorstore import store

Modality = Literal["text", "image", "audio", "video"]
Category = Literal["general", "code", "math", "medical", "document_ocr", "translation"]
C2_PROMPT_VERSION = "v0.4"  # prompts/ko/condition_select.txt (v0.3: 후보마다 match, v0.4: 맞는 후보만)


class ConditionFilter(BaseModel):
    """사용자 조건을 검색 필터로 바꾼 결과"""
    params_min_b: float | None = None
    params_max_b: float | None = None
    input_modalities_required: list[Modality] = Field(default_factory=list)
    languages_required: list[str] = Field(default_factory=list, description="ISO 639-1")
    stage: Literal["base", "instruct"] | None = None
    categories: list[Category] = Field(default_factory=list)
    context_min_tokens: int | None = None
    exclude_gated: bool = False
    license_names: list[str] = Field(default_factory=list, description="사용자가 특정 라이선스를 지목한 경우만")
    sort_by: Literal["downloads", "params_asc", "params_desc", "newest"] | None = None
    semantic_query: str = Field("", description="필터로 표현 못 한 나머지 조건 (의미 검색용, 한국어)")
    limit: int = Field(5, description="기본 5, 최대 10")


class Pick(BaseModel):
    model_id: str
    reason: str


class Picks(BaseModel):
    """조건에 맞는 후보만 (후보 순서대로, 최대 개수까지)"""
    picks: list[Pick]


def build_where(f):
    conds = [{"status": "active"}]
    if f.params_min_b is not None:
        conds.append({"params_b": {"$gte": f.params_min_b}})
    if f.params_max_b is not None:
        conds.append({"params_b": {"$lte": f.params_max_b}})
    conds += [{f"mod_{m}": True} for m in f.input_modalities_required]
    conds += [{f"lang_{c}": True} for c in f.languages_required]
    if f.stage:
        conds.append({"stage": f.stage})
    if f.categories:
        conds.append({"category": {"$in": list(f.categories)}})
    if f.context_min_tokens:
        conds.append({"context_len": {"$gte": f.context_min_tokens}})
    if f.exclude_gated:
        conds.append({"gated": False})
    if f.license_names:
        conds.append({"license": {"$in": list(f.license_names)}})
    return conds[0] if len(conds) == 1 else {"$and": conds}


def sort_candidates(cands, sort_by):
    items = items_by_id()
    keys = {
        "downloads": (lambda c: -(c["metadata"].get("downloads_30d_adj") or 0)),
        "params_asc": (lambda c: c["metadata"].get("params_b") or 0),
        "params_desc": (lambda c: -(c["metadata"].get("params_b") or 0)),
        "newest": (lambda c: items[c["metadata"]["model_id"]].get("created_at") or ""),
    }
    if sort_by == "newest":
        return sorted(cands, key=keys["newest"], reverse=True)
    return sorted(cands, key=keys[sort_by]) if sort_by else cands


def parse_conditions(request):
    # C1 프롬프트에는 입력 자리가 없어, 프롬프트는 시스템 메시지로 두고 사용자 조건은 사용자 메시지로 보낸다
    t = time.perf_counter()
    out = invoke_structured("LLM_SMALL", ConditionFilter,
                            [SystemMessage(prompt("condition_parse")), HumanMessage(request)], "C1 condition_parse")
    perf.record_llm("C1_condition_parse", model_name("LLM_SMALL"), out["raw"].usage_metadata, time.perf_counter() - t)
    if out["parsed"] is None:
        raise ValueError("조건 변환 결과를 해석하지 못함")
    return out["parsed"]


def find_candidates(f):
    where = build_where(f)
    k = setting("condition.candidate_k")
    if f.semantic_query.strip():
        cands = store.search(store.ITEMS, f.semantic_query, k=k, where=where)
        return sort_candidates(cands, f.sort_by)
    # 의미 검색어가 없으면 필터만. 순서 기준이 없으므로 sort_by 가 없을 때는 다운로드 순으로 자른다.
    return sort_candidates(store.get_where(store.ITEMS, where), f.sort_by or "downloads")[:k]


def result_limit(f):
    return max(1, min(f.limit or 5, 10))


def select(request, f, cands):
    """C2. 반환: 맞는 후보의 [(model_id, reason)] — 후보 순서, 중복 없음, limit 개까지."""
    limit = result_limit(f)
    blocks = "\n\n".join(f"[{c['metadata']['model_id']}]\n{c['text']}" for c in cands)
    t = time.perf_counter()
    out = invoke_structured("LLM_SMALL", Picks,
                            fill(prompt("condition_select"), request=request, semantic_query=f.semantic_query or "-",
                                 limit=limit, candidate_item_texts=blocks), "C2 condition_select")
    perf.record_llm("C2_condition_select", model_name("LLM_SMALL"), out["raw"].usage_metadata, time.perf_counter() - t)
    if out["parsed"] is None:
        raise ValueError("후보 선별 결과를 해석하지 못함")
    return validate_picks(out["parsed"].picks, cands, limit)


def validate_picks(picks, cands, limit):
    """후보에 없는 model_id 는 버리고, 중복을 없애고, 원래 후보 순서로 정렬하고, limit 에서 자른다."""
    order = {c["metadata"]["model_id"]: i for i, c in enumerate(cands)}
    reasons = {}
    for p in picks:
        if p.model_id in order and p.model_id not in reasons:
            reasons[p.model_id] = p.reason
    return sorted(reasons.items(), key=lambda kv: order[kv[0]])[:limit]


def search_by_conditions(request):
    """반환: {filter, candidates_count, results: [{model_id, metadata, reason}], c2_prompt_version}"""
    f = parse_conditions(request)
    cands = find_candidates(f)
    results = []
    if cands:
        meta = {c["metadata"]["model_id"]: c["metadata"] for c in cands}
        results = [{"model_id": mid, "metadata": meta[mid], "reason": reason} for mid, reason in select(request, f, cands)]
    return {"filter": f.model_dump(), "candidates_count": len(cands), "results": results,
            "c2_prompt_version": C2_PROMPT_VERSION}
