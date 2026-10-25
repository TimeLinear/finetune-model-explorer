"""모델 소개 요약 (프롬프트 S, design/prompts.md). 카드 본문 → 한국어 2~3문장 + 특징·단계·언어.

- 출력 스키마는 Pydantic 모델로 정의하고 with_structured_output 으로 강제한다.
- 저장 시 카드 URL·리비전, 생성 일시, 생성 모델명을 함께 남긴다 (D-07). 생성 텍스트는 언어 코드 키 (D-08).
- stage_from_card·languages_from_card 는 항목 원본 값을 덮어쓰지 않고 별도 필드로만 둔다.
- 구조화 출력 방식은 모델별 설정(config/llm.json)을 따른다. 파싱 실패 시 1회 재시도 후 실패로 넘긴다.
  출력이 잘리면(max_tokens) 재시도 없이 실패로 넘긴다.
- 건너뛰기 기준은 model_id + 카드 본문 해시(card_body_sha256, manifest 의 body_sha256 과 같은 값) + prompt_version.
  카드 리비전만 바뀌고 본문이 같으면(가중치 파일 변경 등) 다시 만들지 않는다. 프롬프트가 바뀌면 다시 생성된다.
"""
import json
import os
import threading
from datetime import datetime, timezone
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field

from common.config import CONFIG_DIR, DATA_DIR, ROOT, load_json, setting
from common.llm import TruncatedOutput, check_truncated, get_structured_llm, model_name
from data_prep.cards import load_manifest, read_card_body, sha256

LANG = os.environ.get("INDEX_LANG", "ko")
TASK = "LLM_SUMMARY"
PROMPT_VERSION = "v0.2"  # docs/design/prompts.md 의 S 프롬프트 버전
PARSE_RETRIES = 1
SUMMARIES_PATH = DATA_DIR / "summaries.jsonl"
_write_lock = threading.Lock()


class CardSummary(BaseModel):
    """Hugging Face 모델 카드 요약 결과."""
    summary_ko: str = Field(description="2~3문장")
    highlights: list[str] = Field(
        max_length=5,
        description='카드에 명시된 특징, 최대 5개, 각 15자 이내 한국어 (예: "도구 호출 지원", "다국어 지원")')
    stage_from_card: Literal["base", "instruct", "unknown"]
    languages_from_card: list[str] = Field(description="ISO 639-1 코드. 카드에 명시된 것만")
    card_quality: Literal["sufficient", "thin"] = Field(description="카드 정보가 빈약하면 thin")


def prompt_template():
    return (ROOT / "prompts" / LANG / "summary.txt").read_text(encoding="utf-8")


def build_prompt(item, card_text):
    labels = load_json(CONFIG_DIR / f"labels.{LANG}.json")
    modalities = ", ".join(labels["modality"].get(m, m) for m in item.get("input_modalities") or [])
    return prompt_template().format_map({
        "model_id": item["model_id"], "vendor": item["vendor"], "params_b": item["params_b"],
        "modalities": modalities, "card_text": card_text,
    })


def load_records():
    if not SUMMARIES_PATH.exists():
        return []
    return [json.loads(line) for line in SUMMARIES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def record_key(r):
    return r["model_id"], r.get("card_body_sha256"), r.get("prompt_version", "v0.1")  # v0.1 샘플에는 필드가 없다


def done_keys():
    """이미 만든 요약의 키. 본문 해시가 없는 기록은 어떤 항목과도 맞추지 않는다."""
    return {record_key(r) for r in load_records() if r.get("card_body_sha256")}


def card_body_hash(item, manifest=None):
    """항목의 카드 리비전에 해당하는 본문 해시 (manifest). 그 리비전의 카드를 아직 받지 않았으면 None."""
    rec = (manifest if manifest is not None else load_manifest()).get(item["model_id"]) or {}
    if rec.get("card_revision") != item["card_revision"] or rec.get("status") not in ("ok", "mismatch"):
        return None
    return rec.get("body_sha256")


def item_key(item, manifest=None):
    """본문 해시를 모르면 (model_id, None, 버전) → done_keys 에 없으므로 생성 대상."""
    return item["model_id"], card_body_hash(item, manifest), PROMPT_VERSION


@lru_cache
def latest_summaries():
    """현재 프롬프트 버전의 요약만 model_id 별로 (같은 키가 여럿이면 마지막 줄).
    프로세스당 1회만 읽는다 (앱 재실행마다 파일을 다시 읽지 않도록). 요약을 새로 만든 뒤에는 프로세스를 다시 시작한다."""
    return {r["model_id"]: r for r in load_records() if r.get("prompt_version") == PROMPT_VERSION}


class SummaryParseError(RuntimeError):
    def __init__(self, message, usages):
        super().__init__(message)
        self.usages = usages  # 실패한 호출도 토큰은 소비했으므로 합계에 넣는다


def summarizer():
    return get_structured_llm(TASK, CardSummary)


def summarize(item, chain):
    """요약 1건을 만들어 jsonl 에 추가한다. 반환: (record, 호출별 usage_metadata 목록). 카드가 없으면 None."""
    body = read_card_body(item["model_id"])
    if body is None:
        return None
    prompt = build_prompt(item, body[: setting("summary.card_max_chars")])
    usages = []
    for _ in range(PARSE_RETRIES + 1):
        out = chain.invoke(prompt)
        usages.append(out["raw"].usage_metadata or {})
        try:  # 잘린 출력은 다시 불러도 같은 상한에 걸리므로 재시도하지 않고 실패로 넘긴다
            check_truncated(out, TASK, "S summary")
        except TruncatedOutput as e:
            raise SummaryParseError(f"TruncatedOutput: {e}", usages) from e
        if out["parsing_error"] is None and out["parsed"] is not None:
            break
    else:
        err = out["parsing_error"]
        raise SummaryParseError(f"{type(err).__name__}: {str(err)[:300]}", usages)
    s = out["parsed"]
    record = {
        "model_id": item["model_id"],
        "summary": {LANG: s.summary_ko},
        "highlights": s.highlights,
        "stage_from_card": s.stage_from_card,
        "languages_from_card": s.languages_from_card,
        "card_quality": s.card_quality,
        "summary_model": model_name(TASK),
        "prompt_version": PROMPT_VERSION,
        "summary_generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "card_revision": item["card_revision"],
        "card_body_sha256": sha256(body),
        "card_url": item["card_url"],
    }
    with _write_lock, SUMMARIES_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record, usages
