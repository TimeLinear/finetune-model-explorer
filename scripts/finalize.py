"""D-04/D-05 기준 최종 항목 목록 (2026-10-21 스냅샷).

지역·언어 중립 설계(D-08): 데이터에는 코드값(국가 코드, 분야 코드, 언어 코드)만 저장하고,
"어느 지역을 우선 그룹으로 둘지"는 설정(FEATURED_REGIONS)으로 바꾼다. 화면 표시용 이름은 별도 사전에 둔다.
"""
import csv, json, re, sys, collections
from datetime import date

SRC, OUT_JSON = sys.argv[1:3]
SNAP = date(2026, 10, 21)
rows = json.load(open(SRC))["rows"]

# ---- 설정 (나중에 config 파일로 분리) ----
ORG_COUNTRY = {  # ISO 3166-1 alpha-2
    "meta-llama": "US", "google": "US", "Qwen": "CN", "mistralai": "FR", "microsoft": "US", "deepseek-ai": "CN",
    "allenai": "US", "ibm-granite": "US", "nvidia": "US", "HuggingFaceTB": "US", "tiiuae": "AE", "internlm": "CN",
    "zai-org": "CN", "CohereLabs": "CA", "openai": "US", "LiquidAI": "US", "tencent": "CN", "baidu": "CN",
    "moonshotai": "CN", "01-ai": "CN", "swiss-ai": "CH",
    "LGAI-EXAONE": "KR", "naver-hyperclovax": "KR", "kakaocorp": "KR", "skt": "KR", "upstage": "KR",
    "K-intelligence": "KR", "trillionlabs": "KR", "NCSOFT": "KR",
}
FEATURED_REGIONS = {"KR": 0.50}       # 우선 지역 그룹과 그 그룹 내 선별 비율. 비우면 지역 구분 없이 선별
GENERAL_PCT = 0.18
SPECIAL_PCT, SPECIAL_MIN = 0.30, 2

CATEGORY_RULES = [  # 분야 코드
    ("code", r"(coder|code|codestral|devstral|starcoder)"),
    ("math", r"(math|mathstral)"),
    ("medical", r"(medgemma|medical|\bmed\b|-med-|bio|clinic|health)"),
    ("document_ocr", r"(ocr|docling)"),
    ("translation", r"(translat|seamless)"),
]
LABELS = {  # 표시용 이름 (언어별). 데이터에는 코드만 저장
    "ko": {"general": "범용", "code": "코드", "math": "수학", "medical": "의료·생명", "document_ocr": "문서·OCR",
           "translation": "번역", "region:KR": "한국 모델"},
}
# --------------------------------------


def category(n):
    for code, pat in CATEGORY_RULES:
        if re.search(pat, n):
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


DUP = re.compile(r"(-bf16$|-hf$)", re.I)  # 형식만 다른 중복본 제외 (Llama-2 *-hf 는 원본 저장소명이라 예외)
rows = [r for r in rows if not DUP.search(r["id"]) or r["org"] == "meta-llama"]

for r in rows:
    n = r["id"].split("/")[1].lower()
    r["country"] = ORG_COUNTRY.get(r["org"], "")
    r["category"] = category(n)
    r["stage"], r["stage_explicit"] = stage(n, r.get("tags") or [])
    image = r["pipeline"] == "image-text-to-text" or bool(re.search(r"(vision|-vl\b|-vl-|-v-|omni|ocr)", n))
    r["input_modalities"] = ["text", "image"] if image else ["text"]
    r["modality_needs_review"] = "omni" in n  # 오디오·영상 입력 여부는 카드/설정으로 확인 필요
    age = (SNAP - date.fromisoformat(r["created"])).days if r["created"] else 999
    r["dl30_adj"] = round((r["downloads"] or 0) * 30 / max(age, 1)) if age < 30 else (r["downloads"] or 0)
    r["group"] = f"region:{r['country']}" if r["country"] in FEATURED_REGIONS else r["category"]

groups = collections.defaultdict(list)
for r in rows:
    groups[r["group"]].append(r)

picked = []
for g, members in groups.items():
    members.sort(key=lambda r: -r["dl30_adj"])
    if g.startswith("region:"):
        k = max(1, round(len(members) * FEATURED_REGIONS[g.split(":")[1]]))
    elif g == "general":
        k = max(1, round(len(members) * GENERAL_PCT))
    else:
        k = max(round(len(members) * SPECIAL_PCT), min(SPECIAL_MIN, len(members)))
    for i, r in enumerate(members[:k], 1):
        r["group_rank"] = f"{i}/{len(members)}"
        picked.append(r)

out = []
for r in sorted(picked, key=lambda r: (r["group"], r["vendor"], r["id"])):
    out.append({
        "model_id": r["id"], "vendor": r["vendor"], "org": r["org"], "vendor_country": r["country"],
        "source_type": "official", "selection_group": r["group"], "category": r["category"],
        "stage": r["stage"], "stage_needs_review": not r["stage_explicit"],
        "input_modalities": r["input_modalities"], "modality_needs_review": r["modality_needs_review"],
        "params_b": r["params_b"], "license": r["license"], "gated": r["gated"], "languages": norm_langs(r["languages"]),
        "downloads_30d": r["downloads"], "downloads_30d_adj": r["dl30_adj"], "group_rank": r["group_rank"],
        "created_at": r["created"], "hf_url": f"https://huggingface.co/{r['id']}",
        "status": "active", "first_seen": str(SNAP), "last_qualified": str(SNAP), "snapshot_date": str(SNAP),
    })

json.dump(out, open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
print(len(out), dict(collections.Counter(o["selection_group"] for o in out)))
