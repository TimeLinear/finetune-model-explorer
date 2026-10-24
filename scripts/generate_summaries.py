"""모델 소개 요약 생성. data/summaries.jsonl 에 한 줄씩 추가한다.

같은 model_id + card_revision + prompt_version 이 이미 있으면 건너뛰므로, 중단 후 다시 실행하면
실패·미처리분만 처리된다. 전체 실행은 비용이 들어 --all 을 명시해야 한다.
실행마다 토큰 합계와 실패 목록을 logs/summary_runs.jsonl 에 남긴다.

사용:
  python scripts/generate_summaries.py MODEL_ID [MODEL_ID ...]
  python scripts/generate_summaries.py --all [--workers 4]
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from common.config import ROOT  # noqa: E402
from common.llm import MissingApiKey, model_name, structured_output_method  # noqa: E402
from data_prep.items import items_by_id, load_items  # noqa: E402
from data_prep.summaries import PROMPT_VERSION, TASK, SummaryParseError, done_keys, item_key, summarize, summarizer  # noqa: E402

RUN_LOG = ROOT / "logs" / "summary_runs.jsonl"

ap = argparse.ArgumentParser()
ap.add_argument("models", nargs="*")
ap.add_argument("--all", action="store_true")
ap.add_argument("--workers", type=int, default=1)
args = ap.parse_args()
if bool(args.models) == args.all:
    ap.error("모델 ID 목록 또는 --all 중 하나만 지정한다")

targets = load_items() if args.all else [items_by_id()[m] for m in args.models]
done = done_keys()
todo = [it for it in targets if item_key(it) not in done]
print(f"모델 {model_name(TASK)} / 구조화 출력 {structured_output_method(TASK)} / 프롬프트 {PROMPT_VERSION}")
print(f"대상 {len(targets)} / 이미 생성 {len(targets) - len(todo)} / 생성할 것 {len(todo)}", flush=True)

try:
    chain = summarizer()
except MissingApiKey as e:
    sys.exit(f"API 키가 설정되지 않았습니다: {e}")

totals = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
failed = {}
ok = 0


def add_usage(usages):
    for u in usages:
        totals["calls"] += 1
        for k in ("input_tokens", "output_tokens"):
            totals[k] += u.get(k, 0)


def run(item):
    try:
        return item, summarize(item, chain), None
    except Exception as e:  # 한 건 실패로 전체를 멈추지 않는다
        return item, None, e


with ThreadPoolExecutor(max_workers=args.workers) as pool:
    futures = [pool.submit(run, it) for it in todo]
    for n, fut in enumerate(as_completed(futures), 1):
        item, result, err = fut.result()
        mid = item["model_id"]
        if err is not None:
            if isinstance(err, SummaryParseError):
                add_usage(err.usages)
            failed[mid] = f"{type(err).__name__}: {str(err)[:300]}"
            print(f"[{n}/{len(todo)}] 실패 {mid} {failed[mid]}", flush=True)
            continue
        if result is None:
            failed[mid] = "카드 본문 없음"
            print(f"[{n}/{len(todo)}] 실패 {mid} 카드 본문 없음", flush=True)
            continue
        record, usages = result
        ok += 1
        add_usage(usages)
        print(f"[{n}/{len(todo)}] {mid} 호출 {len(usages)}회 "
              f"in={sum(u.get('input_tokens', 0) for u in usages)} out={sum(u.get('output_tokens', 0) for u in usages)}",
              flush=True)
        if not args.all:
            print(json.dumps(record, ensure_ascii=False, indent=1), flush=True)

print("성공", ok, "| 실패", len(failed), "| 토큰 합계", totals)
for mid, reason in failed.items():
    print("  실패:", mid, reason)
RUN_LOG.parent.mkdir(exist_ok=True)
with RUN_LOG.open("a", encoding="utf-8") as f:
    f.write(json.dumps({
        "finished_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "model": model_name(TASK), "prompt_version": PROMPT_VERSION,
        "requested": len(todo), "ok": ok, "failed": failed, "tokens": totals,
    }, ensure_ascii=False) + "\n")
