"""모델별 마지막 질문 일시 기록 (design/data-refresh.md 4절 "보호 기간").

- Streamlit·웹 화면의 질의응답에서 질문을 처리할 때 data/state/last_asked.json 의 해당 모델 값을 지금 시각으로 바꾼다.
- 기록 실패는 질의응답을 막지 않는다: 예외를 삼키고 logs/app.log 에만 남긴다.
- 파일은 임시 파일에 쓴 뒤 바꿔 끼운다 (쓰는 도중 읽어도 깨진 내용이 보이지 않게). 같은 프로세스 안의 동시 기록은 잠금으로 순서를 맞춘다.
- 실행 환경마다 다른 상태라 저장소에 올리지 않는다 (.gitignore).
"""
import json
import os
import threading
from datetime import datetime, timezone

from common.config import DATA_DIR
from common.logs import get_logger

STATE_PATH = DATA_DIR / "state" / "last_asked.json"
_lock = threading.Lock()


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load(path=None):
    """모델 ID → 마지막 질문 일시(ISO). 파일이 없거나 읽을 수 없으면 빈 dict."""
    path = path or STATE_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record(model_id, when=None):
    """기록하고 True. 실패하면 False (예외를 밖으로 내지 않는다)."""
    path = STATE_PATH
    try:
        with _lock:
            data = load(path)
            data[model_id] = when or now_iso()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(tmp, path)
        return True
    except Exception as e:  # 질의응답을 막지 않는다
        get_logger("app").warning("마지막 질문 기록 실패: %s", type(e).__name__)
        return False
