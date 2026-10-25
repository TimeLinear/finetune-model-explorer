"""항목(모델) 목록 로드 (F2001). 앱은 목록을 읽기만 하고 수정하지 않는다 (D-05·D-06).

목록을 바꾸는 것은 데이터 갱신(design/data-refresh.md)뿐이다: 작업 공간(APP_DATA_DIR)에서 write_items 로 새 목록을 쓰고,
교체 단계에서 서비스 위치로 옮긴다.
"""
import csv
import json
from functools import lru_cache

from common.config import DATA_DIR

ITEMS_PATH = DATA_DIR / "items.json"
ITEMS_CSV_PATH = DATA_DIR / "items.csv"


@lru_cache
def load_items():
    return json.loads(ITEMS_PATH.read_text(encoding="utf-8"))


def items_by_id():
    return {it["model_id"]: it for it in load_items()}


def write_items_csv(items, path):
    """목록 → CSV (엑셀에서 열리도록 BOM, 목록 값은 쉼표로 잇는다). 열은 첫 항목의 키 순서."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(items[0].keys()))
        w.writeheader()
        for it in items:
            w.writerow({k: (",".join(v) if isinstance(v, list) else v) for k, v in it.items()})


def write_items(items, json_path=None, csv_path=None):
    """목록 JSON·CSV 를 쓴다 (기본: 현재 데이터 폴더의 items.json / items.csv)."""
    json_path, csv_path = json_path or ITEMS_PATH, csv_path or ITEMS_CSV_PATH
    json_path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    write_items_csv(items, csv_path)
