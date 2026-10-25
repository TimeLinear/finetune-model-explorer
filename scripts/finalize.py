"""D-04/D-05 기준 최종 항목 목록 (로직은 data_prep/selection.py, 설정은 config/catalog.json).

사용: python scripts/finalize.py data/raw_models.json data/items_base.json --date 2026-10-21
입력이 .gz 면 압축을 풀어 읽는다 (tests/fixtures/raw_models_2026-10-21.json.gz).
"""
import argparse
import collections
import gzip
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_prep.selection import select  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("out_json")
ap.add_argument("--date", required=True, help="기준 날짜 YYYY-MM-DD (공개 30일 미만 다운로드 환산, first_seen 등)")
args = ap.parse_args()

opener = gzip.open if args.src.endswith(".gz") else open
with opener(args.src, "rt", encoding="utf-8") as f:
    rows = json.load(f)["rows"]
out = select(rows, date.fromisoformat(args.date))
with open(args.out_json, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(len(out), dict(collections.Counter(o["selection_group"] for o in out)))
