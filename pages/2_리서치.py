"""리서치 (2단계, D-02). 1단계에서는 준비 중 안내만 둔다."""
import streamlit as st

from common.config import texts

R = texts()["research"]
st.set_page_config(page_title=R["title"], layout="wide")
st.title(R["title"])
st.info(R["notice"])
