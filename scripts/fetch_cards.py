"""모델 카드 일괄 수집. 가중치는 받지 않는다.

사용: python scripts/fetch_cards.py [model_id ...]   (인자가 없으면 전체 항목)
결과: data/cards/{조직}__{모델}.md (본문), .frontmatter.yaml (머리말), _manifest.json, _failed.json

카드 본문은 저장소에 올리지 않는다. clone 후 이 스크립트를 실행하면 manifest 의 리비전으로 다시 받고
본문 해시를 manifest 와 대조한다 (verified / mismatch). 게이트 모델은 각자 라이선스 동의가 필요하다.
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from common.config import setting  # noqa: E402
from data_prep.cards import CARDS_DIR, fetch_card, load_manifest, save_manifest  # noqa: E402
from data_prep.items import items_by_id, load_items  # noqa: E402

targets = [items_by_id()[m] for m in sys.argv[1:]] if sys.argv[1:] else load_items()
manifest = load_manifest()
counts = Counter()
for n, item in enumerate(targets, 1):
    result = fetch_card(item, manifest)
    counts[result] += 1
    if result != "skipped":
        save_manifest(manifest)
        print(f"[{n}/{len(targets)}] {result:8} {item['model_id']}", flush=True)
        time.sleep(setting("hf.request_interval_sec"))
save_manifest(manifest)

failed = {m: r.get("error") for m, r in manifest.items() if r["status"] == "failed"}
mismatch = [m for m, r in manifest.items() if r["status"] == "mismatch"]
(CARDS_DIR / "_failed.json").write_text(json.dumps(failed, ensure_ascii=False, indent=1), encoding="utf-8")
print("결과", dict(counts), "| 실패 누적", len(failed), "| 해시 불일치", len(mismatch))
for m, err in failed.items():
    print("  실패:", m, err)
for m in mismatch:
    print("  해시 불일치:", m)
