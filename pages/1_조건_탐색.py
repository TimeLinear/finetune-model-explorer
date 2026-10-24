"""조건 기반 탐색 (F2011, design/retrieval-and-ui.md). 결과 카드의 버튼으로 메인 페이지의 해당 모델 대화로 이동한다."""
import streamlit as st

from common.config import labels, texts
from data_prep.summaries import latest_summaries
from services.condition_search import search_by_conditions
from ui.components import init_state, keys_missing, render_disclaimer, render_highlights, show_error

T = texts()
C = T["condition"]
L = labels()
st.set_page_config(page_title=C["title"], layout="wide")
init_state()
ss = st.session_state
summaries = latest_summaries()

st.title(C["title"])
st.caption(C["caption"])
missing = keys_missing()
if missing:
    st.warning(T["missing_key"])

request = st.text_input(C["input_label"], placeholder=C["input_placeholder"])
if st.button(C["button"], disabled=bool(missing) or not request.strip()):
    try:
        with st.spinner(C["spinner"]):
            ss.condition_result = {"request": request, **search_by_conditions(request)}
    except Exception as e:
        show_error(e)

res = ss.get("condition_result")
if res:
    f = res["filter"]
    applied = {k: v for k, v in f.items() if v not in (None, [], "", False) and k not in ("semantic_query", "limit")}
    with st.expander(C["applied_filters"]):
        st.json(applied)
        if f.get("semantic_query"):
            st.caption(f"{C['semantic_query']}: {f['semantic_query']}")
    st.caption(C["candidates"].format(n=res["candidates_count"], m=len(res["results"])))
    if not res["results"]:
        st.info(T["no_results"])
    for r in res["results"]:
        m = r["metadata"]
        mods = ", ".join(L["modality"].get(k[4:], k[4:]) for k in m if k.startswith("mod_"))
        with st.container(border=True):
            st.markdown(f"**{r['model_id']}**")
            st.caption(" · ".join([f"{m.get('params_b')}B", mods, m.get("license") or "",
                                   f"{T['card_fields']['downloads']} {m.get('downloads_30d_adj', 0):,}"]))
            render_highlights((summaries.get(r["model_id"]) or {}).get("highlights"), expandable=False)
            st.markdown(f"{C['reason']}: {r['reason']}")
            if st.button(C["ask_button"], key=f"ask_{r['model_id']}"):
                ss.selected_model_id = r["model_id"]
                st.switch_page("app.py")
    st.caption(T["popularity_note"])
render_disclaimer()
