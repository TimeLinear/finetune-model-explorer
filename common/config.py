"""설정 파일 읽기. 검색·청킹 값은 config/settings.json, LLM 배정은 config/llm.json (design/retrieval-and-ui.md, design/models.md).

비밀 값은 .env 에서 환경 변수로만 읽는다 (NF2003).
검증 단계에서 설정을 바꿔 비교할 때는 APP_SETTINGS(설정 파일 경로), CHROMA_DIR(색인 폴더)로 바꿔 실행한다.
"""
import json
import os
import re
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"

load_dotenv(ROOT / ".env")

CHROMA_DIR = Path(os.environ.get("CHROMA_DIR") or DATA_DIR / "chroma")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@lru_cache
def settings():
    return load_json(os.environ.get("APP_SETTINGS") or CONFIG_DIR / "settings.json")


def setting(key):
    """점 표기 키로 값을 꺼낸다. 예: setting("chunk.size")"""
    node = settings()
    for part in key.split("."):
        node = node[part]
    return node


@lru_cache
def llm_config():
    return load_json(CONFIG_DIR / "llm.json")


def ui_lang():
    return setting("answer.lang")


@lru_cache
def texts(lang=None):
    """화면 문구·면책 문구 (i18n/{lang}.json, D-08)."""
    return load_json(ROOT / "i18n" / f"{lang or ui_lang()}.json")


@lru_cache
def labels(lang=None):
    """데이터 코드값의 표시 이름 (config/labels.{lang}.json)."""
    return load_json(CONFIG_DIR / f"labels.{lang or ui_lang()}.json")


def prompt(name, lang=None):
    return (ROOT / "prompts" / (lang or ui_lang()) / f"{name}.txt").read_text(encoding="utf-8")


def fill(template, **values):
    """{이름} 자리만 채운다. 프롬프트 예시의 {query: ...} 같은 중괄호는 그대로 둔다."""
    return re.sub(r"\{(\w+)\}", lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template)
