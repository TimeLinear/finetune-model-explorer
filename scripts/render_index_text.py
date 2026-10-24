"""색인 텍스트 미리보기 (design/index-text.md, reports/evaluation.md "항목 1건의 색인 텍스트 출력"). 로직은 data_prep/index_text.py.

사용: python scripts/render_index_text.py [items.json] [model_id ...]   (모델 인자가 없으면 앞의 2개)
items.json 인자는 이전 사용법과의 호환용이며 무시한다 (항목은 data_prep/items.py 의 스냅샷을 읽는다).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from data_prep.index_text import item_metadata, item_summary_text, render  # noqa: E402
from data_prep.items import items_by_id  # noqa: E402
from data_prep.summaries import latest_summaries  # noqa: E402

items = items_by_id()
summaries = latest_summaries()
args = [a for a in sys.argv[1:] if not a.endswith(".json")]
for mid in args or list(items)[:2]:
    print(render(items[mid], item_summary_text(summaries.get(mid))))
    print("메타데이터:", json.dumps(item_metadata(items[mid]), ensure_ascii=False))
    print("-" * 40)
