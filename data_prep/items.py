"""항목(모델) 목록 로드 (F2001). 스냅샷 파일은 읽기만 하고 수정하지 않는다 (D-05·D-06)."""
import json
from functools import lru_cache

from common.config import DATA_DIR

ITEMS_PATH = DATA_DIR / "items.json"


@lru_cache
def load_items():
    return json.loads(ITEMS_PATH.read_text(encoding="utf-8"))


def items_by_id():
    return {it["model_id"]: it for it in load_items()}
