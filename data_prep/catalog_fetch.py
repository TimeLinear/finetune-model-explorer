"""공식 조직 계정의 모델 목록 조회 (D-04, design/data-refresh.md 3절 "조회").

- 조직·조회 항목·필터 규칙은 config/catalog.json 에 둔다.
- 조회 항목(expand)에 커밋 해시(sha)와 마지막 수정 시각(lastModified)을 넣어, 카드 본문을 받지 않고도 변경 여부를 먼저 가린다.
- 요청 간격(hf.request_interval_sec)과 재시도(http.max_retries)는 설정값을 쓰고, HF_TOKEN 이 있으면 함께 보낸다 (NF2006).
- 카드 본문은 받지 않는다. 받은 요청 수는 HFClient.requests 로 센다 (갱신 보고서에 기록).
"""
import os
import re
import time
import urllib.parse

import requests

from common.config import CONFIG_DIR, load_json, setting

USER_AGENT = "finetune-model-explorer/0.1"
API_URL = "https://huggingface.co/api/models"
NO_RETRY_STATUS = {401, 403, 404}


def catalog_config():
    return load_json(CONFIG_DIR / "catalog.json")


class HFRequestError(RuntimeError):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status = status


class HFClient:
    """Hugging Face 요청 (간격·재시도·토큰·요청 수). session 과 sleep 은 테스트에서 가짜로 바꾼다."""

    def __init__(self, session=None, sleep=time.sleep, interval=None, max_retries=None):
        self.session = session or requests.Session()
        self.sleep = sleep
        self.interval = setting("hf.request_interval_sec") if interval is None else interval
        self.max_retries = setting("http.max_retries") if max_retries is None else max_retries
        self.requests = 0
        self._last = None

    def headers(self):
        h = {"User-Agent": USER_AGENT}
        token = os.environ.get("HF_TOKEN")
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    def get(self, url):
        status = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                self.sleep(2 * attempt)
            if self._last is not None:
                wait = self.interval - (time.monotonic() - self._last)
                if wait > 0:
                    self.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            try:
                r = self.session.get(url, headers=self.headers(), timeout=30)
            except requests.RequestException:
                status = "network"
                continue
            if r.status_code == 200:
                return r
            status = r.status_code
            if status in NO_RETRY_STATUS:
                break
            if status == 429:
                self.sleep(float(r.headers.get("Retry-After") or 10))
        raise HFRequestError(status)

    def get_text(self, url):
        return self.get(url).content.decode("utf-8", errors="replace")


def list_org_models(client, org, expand):
    """조직 하나의 모델 목록 (다음 페이지 링크를 따라간다)."""
    q = urllib.parse.urlencode([("author", org), ("limit", 1000)] + [("expand[]", e) for e in expand])
    url, models = f"{API_URL}?{q}", []
    while url:
        r = client.get(url)
        models += r.json()
        m = re.search(r'<([^>]+)>;\s*rel="next"', r.headers.get("Link") or "")
        url = m.group(1) if m else None
    return models


def size_bounds(cfg):
    lo, hi = cfg["params_range_b"]
    return float(f"{lo}e9"), float(f"{hi}e9")


def to_row(m, org, cfg):
    """조회 결과 1건 → (행, None) 또는 (None, 제외 사유). 언어 모델·크기 범위·제외 패턴을 여기서 거른다."""
    mid = m["id"]
    pipe = m.get("pipeline_tag")
    total = (m.get("safetensors") or {}).get("total")
    tags = m.get("tags") or []
    tagset = set(tags)
    lm_like = pipe in cfg["pipelines"] or (pipe is None and bool(tagset & set(cfg["lm_tags_without_pipeline"])))
    if not lm_like:
        return None, "언어 모델 아님"
    if not total:
        return None, "파라미터 수 정보 없음"
    if re.search(cfg["exclude_pattern"], mid, re.I) or re.search(cfg["exclude_audio_pattern"], mid, re.I):
        return None, "제외 패턴"
    lo, hi = size_bounds(cfg)
    if not (lo <= total <= hi):
        return None, "크기 범위 밖"
    card = m.get("cardData") or {}
    name = mid.split("/")[1].lower()
    base_tags = [t for t in tags if t.startswith("base_model:")]
    is_instruct = bool(re.search(r"(instruct|chat|-it\b|-it-|thinking|reasoning)", name)) or (
        "conversational" in tags and not re.search(r"(base|-pt\b|-pt-)", name))
    org_cfg = cfg["orgs"][org]
    return {
        "id": mid, "org": org, "vendor": org_cfg["vendor"], "korean": org_cfg["country"] == "KR",
        "params_b": round(total / 1e9, 2), "pipeline": pipe,
        "stage": "instruct" if is_instruct else "base",
        "license": card.get("license") or next((t[8:] for t in tags if t.startswith("license:")), None),
        "languages": card.get("language"), "gated": m.get("gated"),
        "downloads": m.get("downloads"), "downloads_all": m.get("downloadsAllTime"), "likes": m.get("likes"),
        "trending": m.get("trendingScore"), "tags": tags, "created": (m.get("createdAt") or "")[:10],
        "derived": any(t.startswith("base_model:finetune:") or t.startswith("base_model:quantized:") for t in base_tags),
        "sha": m.get("sha"), "last_modified": m.get("lastModified"),
    }, None


def fetch_catalog(client=None, cfg=None):
    """반환: {"rows", "missing_orgs"(결과 없음), "failed_orgs"(조회 실패: 조직→사유), "excluded"(모델→제외 사유)}"""
    cfg = cfg or catalog_config()
    client = client or HFClient()
    rows, missing, failed, excluded = [], [], {}, {}
    for org in cfg["orgs"]:
        try:
            models = list_org_models(client, org, cfg["expand"])
        except HFRequestError as e:
            failed[org] = str(e)
            continue
        if not models:
            missing.append(org)
            continue
        for m in models:
            row, reason = to_row(m, org, cfg)
            if row:
                rows.append(row)
            else:
                excluded[m["id"]] = reason
    return {"rows": rows, "missing_orgs": missing, "failed_orgs": failed, "excluded": excluded}
