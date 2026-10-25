"""데이터 갱신 작업 공간 안의 작업 (data_prep/refresh_apply.py 가 별도 프로세스로 부른다).

APP_DATA_DIR·CHROMA_DIR 를 작업 공간으로 바꿔 실행하므로, 기존 함수(fetch_card, summarize, ensure_card_indexed,
index_items, load_items, latest_summaries)가 경로를 바꾸지 않고 그대로 작업 공간의 목록·카드·manifest·요약·색인을 쓴다.
서비스가 읽는 data/ 아래 파일은 이 프로세스에서 열지 않는다.

사용 (refresh_apply 가 부른다):
  python -m data_prep.refresh_worker build --out build.json
  python -m data_prep.refresh_worker eval --cases cases.jsonl --out eval.json
  python -m data_prep.refresh_worker count            (항목 수·청크 수를 표준 출력에 JSON 으로)

build
- 신규·재활성 행 보강 (data_prep.enrich.enrich_fields)
- 메타데이터만 바뀐 모델: 카드 리비전 갱신 (카드를 같은 리비전으로 받고 다시 색인. LLM 호출 없음)
- 요약 대상: 우선순위대로 카드 수집 → 요약(일반 API) → 카드 청크 교체. 하나라도 실패하면 그 모델 전체를 이월하고 작업 공간을 되돌린다.
  비용은 실제 토큰으로 누적한다 (refresh_apply.run_targets). LLM 호출은 --max-llm-calls 까지 (SDK 자동 재시도는 끄고 직접 센다)
- 새 목록 쓰기 → items 컬렉션 전체 재색인 → 점검(5절) → 평가 세트 정답 다시 연결(5절)
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common.config import CHROMA_DIR, DATA_DIR  # noqa: E402
from data_prep.refresh_apply import (ModelFailed, Timer, apply_fallback, chunk_check, important_changes,  # noqa: E402
                                     order_keys, read_json, relink_case, run_targets, write_json)

P1_CACHE = ROOT / "tests" / "retrieval_eval" / "p1_cache.jsonl"


def load_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def check_workspace():
    """서비스 폴더에서 실행되는 것을 막는다."""
    service = (ROOT / "data").resolve()
    if DATA_DIR.resolve() == service or CHROMA_DIR.resolve() == (service / "chroma"):
        sys.exit("refresh_worker 는 APP_DATA_DIR·CHROMA_DIR 를 작업 공간으로 바꿔 실행해야 한다")


class LLMCallLimit(RuntimeError):
    pass


class CappedChain:
    """구조화 출력 체인의 호출 수를 세고 상한에서 멈춘다. 호출별 usage_metadata 를 모은다."""

    def __init__(self, chain, max_calls):
        self.chain, self.max_calls, self.calls, self.usages = chain, max_calls, 0, []

    def invoke(self, prompt):
        if self.calls >= self.max_calls:
            raise LLMCallLimit(f"LLM 호출 상한 {self.max_calls}회")
        self.calls += 1
        out = self.chain.invoke(prompt)
        self.usages.append(out["raw"].usage_metadata or {})
        return out


def summary_chain(max_calls):
    from common.llm import get_llm, structured_output_method
    from data_prep.summaries import TASK, CardSummary
    llm = get_llm(TASK).model_copy(update={"max_retries": 0})  # 재시도도 상한에 세도록 SDK 자동 재시도를 끈다
    return CappedChain(llm.with_structured_output(CardSummary, method=structured_output_method(TASK), include_raw=True),
                       max_calls)


# ---------- 모델 단위 반영과 되돌리기 ----------

def snapshot(mid):
    from data_prep.cards import body_path, front_matter_path, load_manifest
    from data_prep.summaries import SUMMARIES_PATH
    from vectorstore.docs_index import load_status
    read = lambda p: p.read_text(encoding="utf-8") if p.exists() else None  # noqa: E731
    return {"body": read(body_path(mid)), "front": read(front_matter_path(mid)),
            "manifest": load_manifest().get(mid), "status": load_status().get(mid),
            "summary_lines": len(SUMMARIES_PATH.read_text(encoding="utf-8").splitlines()) if SUMMARIES_PATH.exists() else 0}


def restore(mid, snap, old_item):
    """작업 공간에서 이 모델의 카드·manifest·요약·색인을 반영 전으로 돌린다 (모델 단위로 전부 반영 아니면 전부 이월)."""
    from data_prep.cards import body_path, front_matter_path, load_manifest, save_manifest
    from data_prep.indexing import card_doc_id, ensure_card_indexed
    from data_prep.summaries import SUMMARIES_PATH
    from vectorstore import store
    from vectorstore.docs_index import drop_status, load_status
    for path, text in ((body_path(mid), snap["body"]), (front_matter_path(mid), snap["front"])):
        if text is not None:
            path.write_text(text, encoding="utf-8", newline="")
        # 이전에 없던 카드 파일은 지우지 않고 남긴다 (manifest 에서 빠지므로 쓰이지 않는다)
    manifest = load_manifest()
    if snap["manifest"] is None:
        manifest.pop(mid, None)
    else:
        manifest[mid] = snap["manifest"]
    save_manifest(manifest)
    if SUMMARIES_PATH.exists():
        lines = SUMMARIES_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
        if len(lines) > snap["summary_lines"]:
            SUMMARIES_PATH.write_text("".join(lines[:snap["summary_lines"]]), encoding="utf-8", newline="")
    if load_status().get(mid) != snap["status"]:
        if snap["status"] and old_item:
            ensure_card_indexed(mid, item=old_item)  # 되돌린 카드(이전 리비전)로 다시 색인
        else:
            store.delete_where(store.DOCS, {"$and": [{"model_id": mid}, {"doc_id": card_doc_id(mid)}]})
            drop_status(mid)


def apply_model(item, old_item, chain, summarize_card, step):
    """카드 수집 → (요약) → 색인. 실패하면 되돌리고 ModelFailed. 반환: 이번 모델의 호출별 usage 목록."""
    from data_prep.cards import fetch_card, load_manifest, save_manifest
    from data_prep.indexing import ensure_card_indexed
    from data_prep.summaries import SummaryParseError, done_keys, item_key, summarize
    mid = item["model_id"]
    snap = snapshot(mid)
    first = len(chain.usages) if chain else 0
    used = lambda: list(chain.usages[first:]) if chain else []  # noqa: E731
    try:
        with step("cards"):
            manifest = load_manifest()
            result = fetch_card(item, manifest)
            save_manifest(manifest)
        if result in ("failed", "mismatch"):
            err = (manifest.get(mid) or {}).get("error") or result
            raise ModelFailed(f"카드 수집 실패 ({err})", gated=err in ("HTTP 401", "HTTP 403"))
        if summarize_card and item_key(item) not in done_keys():  # 이어서 실행할 때 이미 만든 요약은 다시 부르지 않는다
            with step("summaries"):
                try:
                    out = summarize(item, chain)
                except SummaryParseError as e:
                    raise ModelFailed(f"요약 실패: {e}", used()) from e
                except LLMCallLimit as e:
                    raise ModelFailed(str(e), used(), stop=True) from e
            if out is None:
                raise ModelFailed("카드 본문 없음", used())
        with step("index"):
            if ensure_card_indexed(mid, item=item) == "failed":
                raise ModelFailed("카드 색인 실패", used())
        return used()
    except ModelFailed:
        restore(mid, snap, old_item)
        raise
    except Exception as e:
        restore(mid, snap, old_item)
        raise ModelFailed(f"{type(e).__name__}: {str(e)[:200]}", used()) from e


# ---------- build ----------

def build(out_path):
    from data_prep import items as items_mod
    from data_prep.enrich import enrich_fields
    from data_prep.indexing import card_doc_id, index_items
    from data_prep.summaries import latest_summaries
    from vectorstore import store
    from vectorstore.docs_index import load_status

    work = DATA_DIR
    plan = read_json(work / "plan.json")
    timings = {}
    step = Timer(timings)
    counts_before = {"items": len(items_mod.load_items()), "items_chunks": store.count(store.ITEMS),
                     "docs_chunks": store.count(store.DOCS)}
    status_before = load_status()
    rows = {it["model_id"]: it for it in plan["items"]}
    old_items = plan["old_items"]

    with step("enrich"):
        for mid in plan["enrich"]:
            fields = {k: v for k, v in enrich_fields(mid).items() if k != "card_revision"}
            rows[mid].update(fields)
            print(f"보강 {mid}", flush=True)

    carried = []
    for m in plan["metadata_only"]:
        mid = m["model_id"]
        try:
            apply_model(rows[mid], old_items.get(mid), None, False, step)
            print(f"메타데이터만 변경 반영 {mid}", flush=True)
        except ModelFailed as e:
            carried.append({**m, "reason": e.reason, "gated": e.gated})

    chain = summary_chain(plan["max_llm_calls"]) if plan["targets"] else None

    def process(t):
        mid = t["model_id"]
        print(f"반영 {mid} ({t['decision']}, {t['card_result']})", flush=True)
        return apply_model(rows[mid], old_items.get(mid), chain, True, step)

    applied, carried_t, spent = run_targets(plan["targets"], process, plan["max_cost_usd"])
    carried += carried_t
    for c in carried_t:
        print(f"이월 {c['model_id']}: {c['reason']}", flush=True)

    keys = plan["item_keys"]
    final = apply_fallback(list(rows.values()), plan["fallback"], [c["model_id"] for c in carried])
    final = [order_keys(it, keys) for it in final]
    with step("index"):
        items_mod.write_items(final)
        items_mod.load_items.cache_clear()
        latest_summaries.cache_clear()
        index_items()

    # 점검 (5절): 카드가 바뀐 모델(카드 변경·새 카드)
    status_after = load_status()
    final_by = {it["model_id"]: it for it in final}
    checks = []
    for t in applied:
        mid = t["model_id"]
        old = old_items.get(mid)
        ctx = None
        if old and mid in plan["context_check"]:
            ctx = enrich_fields(mid)["max_position_embeddings"]
        checks.append({"model_id": mid, "decision": t["decision"], "card_result": t["card_result"],
                       "important_changes": important_changes(old, final_by[mid], ctx) if old else {},
                       "chunks": chunk_check(status_before.get(mid), status_after.get(mid))})

    # 평가 세트 정답 다시 연결 (5절): 카드가 바뀐 평가 세트 모델의 사례
    cases_path = work / "cases.jsonl"
    cases = load_jsonl(cases_path)
    changed_eval = {t["model_id"] for t in applied if t["card_result"] == "card_changed"} & set(plan["eval_models"])
    important = {c["model_id"] for c in checks if c["important_changes"]}
    relinks, new_cases = [], []
    for case in cases:
        mid = case["model_id"]
        if mid not in changed_eval:
            new_cases.append(case)
            continue
        chunks = store.get_where(store.DOCS, {"$and": [{"model_id": mid}, {"doc_id": card_doc_id(mid)}]})
        new_case, info = relink_case(case, chunks, b_possible=mid in important)
        new_cases.append(new_case)
        relinks.append(info)
    cases_changed = new_cases != cases
    if cases_changed:
        cases_path.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in new_cases), encoding="utf-8")

    result = {
        "applied": applied, "carried": carried,
        "metadata_only_applied": [m["model_id"] for m in plan["metadata_only"]
                                  if m["model_id"] not in {c["model_id"] for c in carried}],
        "enriched": plan["enrich"], "summary_usage": spent, "llm_calls": {"sonnet": chain.calls if chain else 0},
        "checks": checks, "relink": relinks, "cases_changed": cases_changed,
        "a_cases": sorted(r["case_id"] for r in relinks if r["status"] == "A"),
        "b_possible_cases": sorted(r["case_id"] for r in relinks if r["b_possible"]),
        "items_count": len(final),
        "counts": {"before": counts_before,
                   "after": {"items": len(final), "items_chunks": store.count(store.ITEMS),
                             "docs_chunks": store.count(store.DOCS)}},
        "timings_sec": timings,
    }
    write_json(out_path, result)


# ---------- eval ----------

def evaluate(cases_path, out_path, p1_path=P1_CACHE):
    """평가 세트를 작업 공간 색인으로 돌린다. 저장된 P1 캐시의 검색 문구를 쓰므로 LLM 호출이 없다 (scripts/eval_retrieval.py 와 같은 방식)."""
    from rag.graph import search_cards
    p1 = {}
    for r in load_jsonl(p1_path):
        p1.setdefault((r["model_id"], r["question"]), []).append((r.get("rep", 0), r["card_query_en"]))
    rows = []
    t0 = time.perf_counter()
    for c in load_jsonl(cases_path):
        gold = set(c["gold_chunk_ids"])
        for q in c["phrasings"]:
            for rep, cq in sorted(p1[(c["model_id"], q)]):
                ids = [g["id"] for g in search_cards(c["model_id"], q, cq)]
                rows.append({"case_id": c["case_id"], "model_id": c["model_id"], "question": q, "rep": rep,
                             "retrieved": ids, "hit": bool(gold & set(ids))})
    write_json(out_path, {"rows": rows, "hits": sum(r["hit"] for r in rows), "queries": len(rows),
                          "elapsed_sec": round(time.perf_counter() - t0, 1)})
    print(f"평가: {sum(r['hit'] for r in rows)}/{len(rows)}", flush=True)


def count():
    from data_prep.items import load_items
    from vectorstore import store
    print(json.dumps({"items": len(load_items()), "items_chunks": store.count(store.ITEMS),
                      "docs_chunks": store.count(store.DOCS)}))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["build", "eval", "count"])
    ap.add_argument("--out")
    ap.add_argument("--cases")
    args = ap.parse_args()
    if args.command != "count" or os.environ.get("APP_DATA_DIR"):
        check_workspace()
    if args.command == "build":
        build(Path(args.out))
    elif args.command == "eval":
        evaluate(Path(args.cases), Path(args.out))
    else:
        count()
