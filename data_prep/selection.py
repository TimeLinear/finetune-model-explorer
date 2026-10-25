"""항목 선별 규칙 (D-04/D-05, D-08). 조회 결과(catalog_fetch)에서 그룹별 순위로 목록을 고른다.

지역·언어 중립 설계(D-08): 데이터에는 코드값(국가 코드, 분야 코드, 언어 코드)만 저장하고,
"어느 지역을 우선 그룹으로 둘지"는 설정(config/catalog.json 의 featured_regions)으로 바꾼다.
화면 표시용 이름은 config/labels.{lang}.json 에 둔다.

- 지표: 최근 30일 다운로드. 공개 30일 미만 모델은 30일 기준으로 환산한다 (dl30_adj).
- 그룹별 선발 수 k: 우선 지역 = 크기 × 지역 비율, 범용 = 크기 × general_pct, 특수 분야 = max(크기 × special_pct, special_min)
  갱신의 진입 순위도 이 k 를 쓴다 (design/data-refresh.md 4절).
"""
import collections
import re
from datetime import date

from data_prep.catalog_fetch import catalog_config


def category(name, cfg):
    for code, pat in cfg["category_rules"]:
        if re.search(pat, name):
            return code
    return "general"


def stage(n, tags):
    """(단계, 이름에 명시됐는지). 이름에 단계 표기가 없으면 추정값이므로 검토 대상으로 표시한다."""
    if re.search(r"(instruct|chat|-it\b|-it-|thinking|think|reasoning|-rl\b|-rl-|-dpo|-sft)", n):
        return "instruct", True
    if re.search(r"(base|pretrain|-pt\b|-pt-)", n):
        return "base", True
    if re.match(r"qwen2(\.5)?-", n):  # Qwen2/2.5 는 접미사 없음 = 베이스
        return "base", True
    if "conversational" in tags:
        return "instruct", False
    return "base", False


def norm_langs(v):
    if not v:
        return []
    v = v if isinstance(v, list) else [v]
    return sorted({str(x).strip().lower() for x in v if x})


def dl30_adjusted(downloads, created, snap):
    age = (snap - date.fromisoformat(created)).days if created else 999
    return round((downloads or 0) * 30 / max(age, 1)) if age < 30 else (downloads or 0)


def annotate(rows, snap, cfg=None):
    """중복본을 빼고 그룹·분야·단계·환산 다운로드를 붙인 사본 목록. 입력 행은 바꾸지 않는다."""
    cfg = cfg or catalog_config()
    dup = re.compile(cfg["duplicate_pattern"], re.I)  # 형식만 다른 중복본 (Llama-2 *-hf 는 원본 저장소명이라 예외)
    out = []
    for src in rows:
        if dup.search(src["id"]) and src["org"] not in cfg["duplicate_exempt_orgs"]:
            continue
        r = dict(src)
        n = r["id"].split("/")[1].lower()
        r["country"] = (cfg["orgs"].get(r["org"]) or {}).get("country", "")
        r["category"] = category(n, cfg)
        r["stage"], r["stage_explicit"] = stage(n, r.get("tags") or [])
        image = r["pipeline"] == "image-text-to-text" or bool(re.search(r"(vision|-vl\b|-vl-|-v-|omni|ocr)", n))
        r["input_modalities"] = ["text", "image"] if image else ["text"]
        r["modality_needs_review"] = "omni" in n  # 오디오·영상 입력 여부는 카드/설정으로 확인 필요
        r["dl30_adj"] = dl30_adjusted(r["downloads"], r["created"], snap)
        r["group"] = f"region:{r['country']}" if r["country"] in cfg["featured_regions"] else r["category"]
        out.append(r)
    return out


def group_k(group, size, cfg=None):
    """그룹 크기 → 선발 수 k (진입 순위)."""
    cfg = cfg or catalog_config()
    if group.startswith("region:"):
        return max(1, round(size * cfg["featured_regions"][group.split(":")[1]]))
    if group == "general":
        return max(1, round(size * cfg["general_pct"]))
    return max(round(size * cfg["special_pct"]), min(cfg["special_min"], size))


def rank_groups(annotated):
    """그룹 → 환산 다운로드 내림차순 구성원 목록 (같으면 입력 순서 유지)."""
    groups = collections.defaultdict(list)
    for r in annotated:
        groups[r["group"]].append(r)
    for members in groups.values():
        members.sort(key=lambda r: -r["dl30_adj"])
    return dict(groups)


def item_record(r, rank, size, snap):
    return {
        "model_id": r["id"], "vendor": r["vendor"], "org": r["org"], "vendor_country": r["country"],
        "source_type": "official", "selection_group": r["group"], "category": r["category"],
        "stage": r["stage"], "stage_needs_review": not r["stage_explicit"],
        "input_modalities": r["input_modalities"], "modality_needs_review": r["modality_needs_review"],
        "params_b": r["params_b"], "license": r["license"], "gated": r["gated"], "languages": norm_langs(r["languages"]),
        "downloads_30d": r["downloads"], "downloads_30d_adj": r["dl30_adj"], "group_rank": f"{rank}/{size}",
        "created_at": r["created"], "hf_url": f"https://huggingface.co/{r['id']}",
        "status": "active", "first_seen": str(snap), "last_qualified": str(snap), "snapshot_date": str(snap),
    }


def select(rows, snap, cfg=None):
    """조회 결과 행 → 기준 날짜 snap 의 항목 목록 (그룹·업체·모델 ID 순)."""
    cfg = cfg or catalog_config()
    picked = []
    for g, members in rank_groups(annotate(rows, snap, cfg)).items():
        k = group_k(g, len(members), cfg)
        picked += [(r, i, len(members)) for i, r in enumerate(members[:k], 1)]
    picked.sort(key=lambda p: (p[0]["group"], p[0]["vendor"], p[0]["id"]))
    return [item_record(r, i, n, snap) for r, i, n in picked]
