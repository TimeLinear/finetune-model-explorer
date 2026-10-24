"""일괄 색인 (F2002·F2005). 앱 실행 전에 한 번 돌린다.

- items 컬렉션: 202개 항목 색인 텍스트 (소개 요약 포함)
- docs 컬렉션: 모델 카드 전체 (ensure_card_indexed, 멱등)
두 번 실행해도 청크 수가 늘지 않아야 한다 (reports/evaluation.md).

사용: python scripts/build_index.py [--items-only | --cards-only] [model_id ...]
"""
import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from common.config import CHROMA_DIR, setting  # noqa: E402
from data_prep.indexing import ensure_card_indexed, index_items  # noqa: E402
from data_prep.items import load_items  # noqa: E402
from vectorstore import store  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("models", nargs="*")
group = ap.add_mutually_exclusive_group()
group.add_argument("--items-only", action="store_true")
group.add_argument("--cards-only", action="store_true")
args = ap.parse_args()

print(f"색인 폴더 {CHROMA_DIR} | 임베딩 {setting('embedding.model')} | "
      f"청크 {setting('chunk.size')}자 / 중복 {setting('chunk.overlap')}자")
before = {name: store.count(name) for name in (store.ITEMS, store.DOCS)}
print("색인 전 청크 수", before, flush=True)

t0 = time.time()
if not args.cards_only:
    print("items 색인:", index_items(), "건", f"({time.time() - t0:.0f}초)", flush=True)

if not args.items_only:
    targets = args.models or [it["model_id"] for it in load_items()]
    results = Counter()
    for n, mid in enumerate(targets, 1):
        try:
            r = ensure_card_indexed(mid)
        except Exception as e:  # 한 모델 실패로 전체를 멈추지 않는다 (상태는 failed 로 기록됨)
            r = "failed"
            print(f"  실패 {mid}: {type(e).__name__}", flush=True)
        results[r] += 1
        if r != "done":
            print(f"[{n}/{len(targets)}] {r:8} {mid}", flush=True)
    print("카드 색인 결과", dict(results), f"({time.time() - t0:.0f}초)")

after = {name: store.count(name) for name in (store.ITEMS, store.DOCS)}
print("색인 후 청크 수", after)
