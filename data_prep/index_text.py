"""항목 색인 텍스트와 Chroma 메타데이터 구성 (F2001, design/index-text.md·collections.md). scripts/render_index_text.py 에서 옮겨 왔다.

색인 텍스트 규칙
- 값이 없는 줄은 통째로 뺀다. "없음" 같은 빈 표현은 검색 노이즈가 되기 때문이다.
- 다운로드 수·등록일·정밀도처럼 의미 검색에 쓸모없는 숫자는 넣지 않는다 (메타데이터 필터로만 사용).
- 표시 문구는 언어별 라벨 파일(config/labels.{lang}.json)에서 가져온다 (D-08).
- 소개 요약이 있으면 "소개" 줄에 넣는다 (data/summaries.jsonl, 현재 프롬프트 버전).

메타데이터 규칙 (design/collections.md 1절)
- 문자열·숫자·참거짓만, None 은 키를 뺀다. 목록 필드는 플래그(mod_*, lang_*)로 펼친다.
"""
import os
import re

from common.config import CONFIG_DIR, load_json

LANG = os.environ.get("INDEX_LANG", "ko")
TEMPLATE = (CONFIG_DIR / f"index_text_template.{LANG}.txt").read_text(encoding="utf-8")
L = load_json(CONFIG_DIR / f"labels.{LANG}.json")

# design/collections.md 1절 "Chroma 메타데이터" 필드 (목록 필드·이름이 바뀌는 필드는 item_metadata 에서 따로 처리)
METADATA_FIELDS = ("model_id", "params_b", "stage", "category", "vendor_country", "license", "gated",
                   "downloads_30d_adj", "status", "snapshot_date", "source_type", "card_url", "card_revision")


def fields(it, summary=None):
    langs = it.get("languages") or []
    shown = [L["language"].get(c, c) for c in langs[:6]]
    if len(langs) > 6:
        shown.append(L["languages_more"].format(n=len(langs) - 6))
    ctx_fmt = L["context"].get(it.get("context_source") or "")
    ctx = None
    if ctx_fmt:
        v = it.get("max_position_embeddings")
        ctx = ctx_fmt.format(value=f"{v:,}" if v else "")
    if (it.get("model_type") or "").lower() in ("mamba", "mamba2"):
        arch = L["arch_ssm"]
    else:
        arch = L["arch_moe"].format(**it) if it.get("is_moe") else L["arch_dense"]
    tools = it.get("chat_template_has_tools")
    return {
        "model_id": it["model_id"], "vendor": it["vendor"],
        "vendor_country_label": L["country"].get(it.get("vendor_country"), it.get("vendor_country")),
        "family": it.get("family"), "version": it.get("version"),
        "params_b": it["params_b"], "arch_label": arch,
        "modalities_label": ", ".join(L["modality"].get(m, m) for m in it.get("input_modalities") or []),
        "stage_label": L["stage"].get(it.get("stage")),
        "category_label": L["category"].get(it.get("category")),
        "languages_label": ", ".join(shown) or None,
        "context_label": ctx,
        "license": it.get("license"), "gated_label": L["gated"] if it.get("gated") else "",
        # "없음"은 템플릿 위치 차이로 잘못 판정될 수 있어, 확인된 경우(있음)만 적는다
        "tools_label": L["tools"]["true"] if tools else None,
        "base_model": it.get("base_model"),
        "summary": summary,
    }


def render(it, summary=None):
    f = fields(it, summary)
    out = []
    for line in TEMPLATE.splitlines():
        keys = re.findall(r"{(\w+)}", line)
        main = [k for k in keys if not k.endswith("gated_label") and k != "version"]
        if any(f.get(k) in (None, "") for k in main):
            continue  # 값이 없는 줄은 뺀다
        out.append(line.format(**{k: ("" if f.get(k) is None else f[k]) for k in keys}).replace("  ", " ").rstrip())
    return "\n".join(out)


def item_metadata(it):
    meta = {k: it.get(k) for k in METADATA_FIELDS}
    meta["context_len"] = it.get("max_position_embeddings")
    for m in it.get("input_modalities") or []:
        meta[f"mod_{m}"] = True
    for code in it.get("languages") or []:
        meta[f"lang_{code}"] = True
    return {k: v for k, v in meta.items() if v is not None}


def item_chunk_id(model_id):
    return f"item:{model_id}"


def item_summary_text(record):
    return (record or {}).get("summary", {}).get(LANG)
