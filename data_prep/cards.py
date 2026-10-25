"""Hugging Face 모델 카드 수집 (항목 자체 문서, design/collections.md 3절).

- 카드 리비전(card_revision)에 고정된 README.md 를 받는다. 게이트 저장소는 HF_TOKEN 이 필요하다.
- YAML 머리말(--- 로 둘러싸인 앞부분)은 본문과 분리해 따로 저장한다.
- 요청 간격(hf.request_interval_sec)을 두고, 실패 시 최대 http.max_retries 회 재시도한다 (NF2006).
- 카드 원문은 저장소에 올리지 않고 manifest(모델 ID·리비전·URL·본문 해시·길이)만 올린다.
  clone 후 다시 받으면 본문 해시를 manifest 와 대조해 같은 카드인지 확인한다 (결정사항 "저장소에 올리는 데이터 범위").
"""
import hashlib
import json
import os
import time
from datetime import datetime, timezone

import requests
import yaml

from common.config import DATA_DIR, setting

CARDS_DIR = DATA_DIR / "cards"
MANIFEST_PATH = CARDS_DIR / "_manifest.json"
USER_AGENT = "finetune-model-explorer/0.1"
NO_RETRY_STATUS = {401, 403, 404}
STATS = {"requests": 0}  # 카드 다운로드 요청 수 (재시도 포함, 갱신 보고서용)


class CardFetchError(RuntimeError):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status = status


def card_stem(model_id):
    return model_id.replace("/", "__")


def body_path(model_id):
    return CARDS_DIR / f"{card_stem(model_id)}.md"


def front_matter_path(model_id):
    return CARDS_DIR / f"{card_stem(model_id)}.frontmatter.yaml"


def raw_url(model_id, revision):
    return f"https://huggingface.co/{model_id}/resolve/{revision}/README.md"


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_front_matter(text):
    """(머리말, 본문). 머리말이 없으면 (None, 원문)."""
    lines = text.lstrip("﻿").splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "".join(lines[1:i]), "".join(lines[i + 1:]).lstrip("\r\n")
    return None, text


def download(model_id, revision):
    headers = {"User-Agent": USER_AGENT}
    token = os.environ.get("HF_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    status = None
    for attempt in range(setting("http.max_retries") + 1):
        if attempt:
            time.sleep(2 * attempt)
        STATS["requests"] += 1
        try:
            r = requests.get(raw_url(model_id, revision), headers=headers, timeout=30)
        except requests.RequestException:
            status = "network"
            continue
        if r.status_code == 200:
            r.encoding = "utf-8"
            return r.text
        status = r.status_code
        if status in NO_RETRY_STATUS:
            break
        if status == 429:
            time.sleep(float(r.headers.get("Retry-After") or 10))
    raise CardFetchError(status)


def load_manifest():
    if not MANIFEST_PATH.exists():
        return {}
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for mid, rec in manifest.items():  # 초기 기록(revision 키, model_id 없음)을 현재 형식으로 맞춘다
        if "revision" in rec:
            rec["card_revision"] = rec.pop("revision")
        rec.setdefault("model_id", mid)
    return manifest


def save_manifest(manifest):
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    data = {m: manifest[m] for m in sorted(manifest)}
    MANIFEST_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def fetch_card(item, manifest):
    """카드 하나를 확보하고 manifest 를 갱신한다.

    반환: 'skipped'(이미 같은 본문 보유) | 'ok'(새로 받음) | 'verified'(다시 받아 해시 일치)
          | 'mismatch'(다시 받았으나 해시 불일치) | 'failed'
    """
    mid, rev = item["model_id"], item["card_revision"]
    rec = manifest.get(mid) or {}
    same_rev = rec.get("card_revision") == rev and rec.get("status") in ("ok", "mismatch")
    path = body_path(mid)

    if same_rev and path.exists():
        local = path.read_text(encoding="utf-8")
        if rec.get("body_sha256") in (None, sha256(local)):
            rec.update(body_sha256=sha256(local), body_chars=len(local))  # 해시가 없던 기록은 채운다
            return "skipped"

    base = {"model_id": mid, "card_revision": rev, "url": raw_url(mid, rev), "fetched_at": now_iso()}
    try:
        text = download(mid, rev)
    except CardFetchError as e:
        manifest[mid] = {**rec, **base, "status": "failed", "error": str(e)}
        return "failed"
    front, body = split_front_matter(text)
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="")
    if front is not None:
        front_matter_path(mid).write_text(front, encoding="utf-8", newline="")
    else:
        front_matter_path(mid).unlink(missing_ok=True)

    digest = sha256(body)
    if same_rev and rec.get("body_sha256"):
        result = "verified" if digest == rec["body_sha256"] else "mismatch"
        # 기록된 해시는 유지하고, 불일치면 받은 본문의 해시를 따로 남긴다
        manifest[mid] = {**rec, "status": "ok" if result == "verified" else "mismatch",
                         "verified_at": now_iso(), **({"received_sha256": digest} if result == "mismatch" else {})}
        return result
    manifest[mid] = {**base, "status": "ok", "body_sha256": digest, "body_chars": len(body),
                     "has_front_matter": front is not None}
    return "ok"


def read_card_body(model_id):
    p = body_path(model_id)
    return p.read_text(encoding="utf-8") if p.exists() else None


def read_front_matter(model_id):
    """카드 머리말(YAML)을 dict 로. 없거나 읽을 수 없으면 빈 dict."""
    p = front_matter_path(model_id)
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _plain(value):
    if isinstance(value, list):
        return ", ".join(_plain(v) for v in value)
    if isinstance(value, dict):
        return yaml.safe_dump(value, allow_unicode=True, sort_keys=False).strip()
    return str(value).strip()


def front_matter_text(front_matter, keys):
    """머리말에서 정해 둔 키만 "키: 값" 줄로 (design/collections.md 3절 "카드 머리말과 섹션 처리"). 해당 키가 없으면 빈 문자열."""
    lines = [f"{k}: {_plain(front_matter[k])}" for k in keys if front_matter.get(k) not in (None, "", [], {})]
    return "\n".join(lines)
