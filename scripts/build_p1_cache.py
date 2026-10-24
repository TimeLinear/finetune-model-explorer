"""검색 평가용 P1 캐시 만들기. 평가 세트의 표현마다 P1(검색어 추출)을 실행해 card_query_en 을 저장한다.
이후 평가는 이 캐시로 재현한다 (LLM 호출 없이). 이미 캐시에 있는 (모델, 질문, 반복 번호)는 건너뛴다.

사용: python scripts/build_p1_cache.py [--workers 4]
      python scripts/build_p1_cache.py --out p1_cache_haiku_v04.jsonl --repeats 2 --prompt-version v0.4           --prompt-file tests/retrieval_eval/prompt_candidates/query_extract_v04.txt
P1 모델은 LLM_SMALL 설정을 따른다 (예: 환경 변수 LLM_SMALL=anthropic:claude-haiku-5-5).
--out 은 tests/retrieval_eval/ 아래 파일 이름. --prompt-file 이 없으면 앱 프롬프트(prompts/ko/query_extract.txt).
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from common import perf  # noqa: E402
from common.config import ROOT  # noqa: E402
from common.llm import model_name  # noqa: E402
from data_prep.wiki import extract_queries  # noqa: E402
from vectorstore import store  # noqa: E402

EVAL_DIR = ROOT / "tests" / "retrieval_eval"
CASES = EVAL_DIR / "cases.jsonl"


def load_jsonl(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []


ap = argparse.ArgumentParser()
ap.add_argument("--workers", type=int, default=4)
ap.add_argument("--out", default="p1_cache.jsonl")
ap.add_argument("--repeats", type=int, default=1, help="표현마다 실행 횟수")
ap.add_argument("--prompt-file", help="프로젝트 기준 경로. 없으면 앱 프롬프트")
ap.add_argument("--prompt-version", help="기록용 프롬프트 버전")
args = ap.parse_args()
CACHE = EVAL_DIR / args.out
TEMPLATE = (ROOT / args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else None

done = {(r["model_id"], r["question"], r.get("rep", 0)) for r in load_jsonl(CACHE)}
todo = sorted({(c["model_id"], q, rep) for c in load_jsonl(CASES) for q in c["phrasings"]
               for rep in range(args.repeats)} - done)
print("캐시", len(done), "/ 새로 실행", len(todo), flush=True)


def run(job):
    mid, q, rep = job
    ext = extract_queries(mid, q, template=TEMPLATE)
    rec = {"model_id": mid, "question": q, "card_query_en": ext.card_query_en,
           "wiki_queries": [x.query for x in ext.queries], "p1_model": model_name("LLM_SMALL"),
           "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")}
    if args.repeats > 1 or args.prompt_version:
        rec.update(rep=rep, prompt_version=args.prompt_version, prompt_file=args.prompt_file or "prompts/ko/query_extract.txt")
    return rec


store.count(store.ITEMS)  # Chroma 클라이언트를 스레드 시작 전에 한 번 만든다 (동시 생성 충돌 방지)
perf.start_trace("p1_cache", n=len(todo))
with ThreadPoolExecutor(max_workers=args.workers) as pool, CACHE.open("a", encoding="utf-8", newline="\n") as f:
    for rec in pool.map(run, todo):
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
tr = perf.finish_trace()
tin = sum(c["input_tokens"] or 0 for c in tr["llm_calls"])
tout = sum(c["output_tokens"] or 0 for c in tr["llm_calls"])
print("P1 호출", len(tr["llm_calls"]), "입력 토큰", tin, "출력 토큰", tout, "소요", tr["total_sec"], "초")
