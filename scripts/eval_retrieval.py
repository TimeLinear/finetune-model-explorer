"""카드 검색 평가. LLM 을 호출하지 않고 P1 캐시(tests/retrieval_eval/p1_cache.jsonl)의 card_query_en 으로 재현한다.

지표
- hit@card_k: 표현(질문 1개) 단위로, 정답 청크 중 하나라도 카드 상위 card_k 안에 있으면 hit
- 안정성: 사례의 모든 실행(표현 3개 x P1 캐시의 반복 수)이 hit 인 사례의 비율
- 사례별 적중 수, 검색 문구 길이 중앙값(단어 수)
검색은 앱과 같은 함수(rag.graph.search_cards)를 쓴다. 정답은 cases.jsonl 에 고정돼 있고 결과를 보고 바꾸지 않는다.

사용 (프로젝트 루트에서):
  python scripts/eval_retrieval.py --label baseline [--chroma-dir PATH] [--set retrieve.card_query_mode=rrf ...]
  python scripts/eval_retrieval.py --label rrf --set retrieve.card_query_mode=rrf --compare baseline
  python scripts/eval_retrieval.py --label haiku_v04 --p1-cache p1_cache_haiku_v04.jsonl   (표현마다 여러 번 뽑은 캐시도 됨)
결과 파일의 경로는 프로젝트 기준 상대 경로, 프로젝트 밖이면 "scratch:<폴더 이름>" 으로만 남긴다.
결과: tests/retrieval_eval/results/{label}.json
"""
import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT_DIR / "tests" / "retrieval_eval"

ap = argparse.ArgumentParser()
ap.add_argument("--label", required=True)
ap.add_argument("--chroma-dir")
ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="설정 덮어쓰기 (값은 JSON)")
ap.add_argument("--compare", help="비교할 기준 결과 라벨")
ap.add_argument("--p1-cache", default="p1_cache.jsonl", help="tests/retrieval_eval/ 아래 P1 캐시 파일 이름")
args = ap.parse_args()

# 설정·색인 폴더는 모듈을 불러오기 전에 정해야 한다 (common.config 가 import 시점에 읽음)
if args.chroma_dir:
    os.environ["CHROMA_DIR"] = args.chroma_dir
settings = json.loads((ROOT_DIR / "config" / "settings.json").read_text(encoding="utf-8"))
for kv in args.set:
    key, _, raw = kv.partition("=")
    a, b = key.split(".")
    settings[a][b] = json.loads(raw)
if args.set:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(settings, tmp)
    tmp.close()
    os.environ["APP_SETTINGS"] = tmp.name

sys.path.insert(0, str(ROOT_DIR))
sys.stdout.reconfigure(encoding="utf-8")

from common.config import CHROMA_DIR, setting  # noqa: E402
from rag.graph import search_cards  # noqa: E402
from vectorstore.embeddings import get_embeddings  # noqa: E402


def load_jsonl(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


cases = load_jsonl(EVAL_DIR / "cases.jsonl")
def shown_path(path):
    """결과 파일에 남길 경로: 프로젝트 안이면 상대 경로, 밖이면 scratch:<폴더 이름> (로컬 경로·사용자 이름을 남기지 않는다)."""
    path = Path(path).resolve()
    try:
        return path.relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return f"scratch:{path.name}"


p1 = {}
for r in load_jsonl(EVAL_DIR / args.p1_cache):
    p1.setdefault((r["model_id"], r["question"]), []).append((r.get("rep", 0), r["card_query_en"]))
get_embeddings()  # 모델 적재 시간을 검색 시간에서 뺀다
search_cards(cases[0]["model_id"], "warm up", "warm up")

rows, times = [], []
for c in cases:
    gold = set(c["gold_chunk_ids"])
    for q in c["phrasings"]:
        for rep, cq in sorted(p1[(c["model_id"], q)]):
            t = time.perf_counter()
            got = search_cards(c["model_id"], q, cq)
            times.append(time.perf_counter() - t)
            ids = [g["id"] for g in got]
            rows.append({"case_id": c["case_id"], "model_id": c["model_id"], "topic": c["topic"], "question": q,
                         "rep": rep, "card_query_en": cq, "retrieved": ids, "hit": bool(gold & set(ids))})

by_case = {}
for r in rows:
    by_case.setdefault(r["case_id"], []).append(r["hit"])
summary = {
    "label": args.label, "chroma_dir": shown_path(CHROMA_DIR), "p1_cache": args.p1_cache, "overrides": args.set,
    "card_k": setting("retrieve.card_k"), "card_query_mode": setting("retrieve.card_query_mode"),
    "chunk_header": setting("index.chunk_header"),
    "phrasings": len(rows), "hits": sum(r["hit"] for r in rows),
    "hit_at_k": round(sum(r["hit"] for r in rows) / len(rows), 4),
    "cases": len(by_case), "stable_cases": sum(all(v) for v in by_case.values()),
    "stability": round(sum(all(v) for v in by_case.values()) / len(by_case), 4),
    "search_ms_median": round(statistics.median(times) * 1000, 1), "search_ms_max": round(max(times) * 1000, 1),
    "query_words_median": statistics.median(len(r["card_query_en"].split()) for r in rows),
    "hits_by_case": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_case.items())},
}
by_topic = {}
for r in rows:
    by_topic.setdefault(r["topic"], []).append(r["hit"])
summary["hit_by_topic"] = {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_topic.items())}

out_dir = EVAL_DIR / "results"
out_dir.mkdir(exist_ok=True)
(out_dir / f"{args.label}.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False))

if args.compare:
    base_rows = json.loads((out_dir / f"{args.compare}.json").read_text(encoding="utf-8"))["rows"]
    if {r.get("rep", 0) for r in base_rows} == {r["rep"] for r in rows}:  # 같은 실행 단위면 실행별 비교
        base = {(r["case_id"], r["question"], r.get("rep", 0)): r["hit"] for r in base_rows}
        lost = [(r["case_id"], r["question"]) for r in rows if base[(r["case_id"], r["question"], r["rep"])] and not r["hit"]]
        gained = [(r["case_id"], r["question"]) for r in rows if not base[(r["case_id"], r["question"], r["rep"])] and r["hit"]]
        print(f"{args.compare} 대비: hit→miss {len(lost)}건 {lost} / miss→hit {len(gained)}건")
    base_case = {}
    for r in base_rows:
        base_case[r["case_id"]] = base_case.get(r["case_id"], 0) + r["hit"]
    now_case = {k: sum(v) for k, v in by_case.items()}
    diff = {k: (base_case.get(k, 0), now_case[k]) for k in sorted(now_case) if base_case.get(k, 0) != now_case[k]}
    print(f"{args.compare} 대비 사례별 적중 수가 달라진 사례 (기준, 이번): {diff}")
