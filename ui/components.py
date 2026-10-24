"""화면 공통 부품. 화면에는 짧은 안내만 보이고 상세 오류·프롬프트 전문·키는 노출하지 않는다 (NF2004)."""
import html

import streamlit as st

from common.config import labels, texts
from common.llm import missing_api_keys
from common.logs import get_logger
from data_prep.items import items_by_id
from vectorstore import store

T = texts()
L = labels()
log = get_logger("ui")


def init_state():
    ss = st.session_state
    ss.setdefault("selected_model_id", None)
    ss.setdefault("chats", {})  # model_id → [message] (F2009: 모델별로 대화 분리)
    ss.setdefault("research", {})  # 2단계 전용, 채팅과 분리


def index_counts():
    return {"items": store.count(store.ITEMS), "docs": store.count(store.DOCS)}


def keys_missing():
    return missing_api_keys()


def show_error(e):
    """예외는 로그 파일에만 자세히 남기고 화면에는 짧은 안내만."""
    log.exception("처리 실패: %s", type(e).__name__)
    st.error(T["error_generic"])


def model_option_label(model_id):
    it = items_by_id().get(model_id) or {}
    return f"{model_id} · {it.get('params_b')}B" if it else model_id


def render_evidence_list(evidence, header=None):
    """[근거 n] 제목 · 출처 종류 · 소제목 · 원문 링크 (F2008, F2016 출처 종류 구분)"""
    with st.expander(header or T["evidence_header"].format(n=len(evidence))):
        for ev in evidence:
            parts = [f"**[{T['citation_label']} {ev['n']}]** {ev.get('title') or ''}",
                     T["source_type"].get(ev["source_type"], ev["source_type"])]
            if ev.get("section"):
                parts.append(ev["section"])
            line = " · ".join(parts)
            if ev.get("url"):
                line += f" · [{T['evidence_link']}]({ev['url']})"
            st.markdown(line)


def render_assistant_extras(message):
    for note in message.get("notes", []):
        st.caption(note)
    if message.get("no_citation"):
        st.caption("ⓘ " + T["no_citation"])
    elif message.get("evidence"):
        render_evidence_list(message["evidence"])


# highlights 표시 (design/retrieval-and-ui.md): 데이터는 원문 그대로 두고 화면에서만 말줄임. 마우스를 올리면 title 로 전체 문구.
CHIP_CSS = ("<style>.hl-chips{display:flex;flex-wrap:wrap;gap:4px;margin:2px 0 6px}"
            ".hl-chip{display:inline-block;max-width:min(15em,100%);overflow:hidden;white-space:nowrap;"
            "text-overflow:ellipsis;padding:1px 8px;border-radius:10px;font-size:0.78rem;"
            "background:rgba(128,128,128,0.15)}</style>")


def highlight_chips_html(highlights):
    """LLM 생성 문구이므로 본문·title 모두 HTML 이스케이프한다."""
    chips = "".join(f'<span class="hl-chip" title="{html.escape(h, quote=True)}">{html.escape(h)}</span>'
                    for h in highlights)
    return f'{CHIP_CSS}<div class="hl-chips">{chips}</div>'


def render_highlights(highlights, expandable):
    """expandable=True: 사이드바 요약 카드 (모바일 대응 '전체 보기' 접기 영역). 가로로 나란한 카드는 False(툴팁만)."""
    if not highlights:
        return
    st.markdown(highlight_chips_html(highlights), unsafe_allow_html=True)
    if expandable:
        with st.expander(T["highlights_all"]):
            st.markdown("\n".join(f"- {html.escape(h)}" for h in highlights))


def render_model_card(model_id, summary_text=None, highlights=None):
    it = items_by_id()[model_id]
    f = T["card_fields"]
    mods = ", ".join(L["modality"].get(m, m) for m in it.get("input_modalities") or [])
    ctx = it.get("max_position_embeddings")
    st.markdown(f"**{T['selected_card_title']}**  \n`{model_id}`")
    st.caption(" · ".join(x for x in [
        f"{f['vendor']}: {it.get('vendor')}", f"{f['params']}: {it.get('params_b')}B",
        f"{f['license']}: {it.get('license')}", f"{f['modalities']}: {mods}",
        f"{f['context']}: {ctx:,}" if ctx else None,
        f"{f['downloads']}: {it.get('downloads_30d_adj'):,}",
    ] if x))
    render_highlights(highlights, expandable=True)
    if summary_text:
        st.caption(f"{f['summary']}: {summary_text}")


def render_disclaimer():
    st.caption(T["disclaimer"])
