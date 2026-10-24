"""'인용 근거 없음' 판정과 화면 안내 경로 (F2008, reports/evaluation.md 답변과 근거 마지막 항목).

입력은 합성이다: 인용 표기가 없는 답변 문자열을 LLM 대신 돌려주는 가짜 모델을 쓴다.
실제 LLM 은 대부분 근거를 인용해 이 상황을 재현하기 어렵고(감사 인사에도 인용함), 결과가 매번 달라 테스트로 고정할 수 없기 때문이다.

커버하는 범위
- rag.graph.generate 노드: 메시지 구성(build_messages) → LLM 응답 텍스트 → 인용 추출 → no_citation 판정 (LLM 호출만 가짜)
- app.py 가 만드는 메시지 dict 와 같은 모양으로 ui.components.render_assistant_extras 를 Streamlit AppTest 로 실제 렌더링해
  i18n 안내 문구가 화면에 나오는지, 근거 목록(expander)이 나오지 않는지 확인
커버하지 않는 범위
- 실제 LLM 호출, retrieve 노드의 검색, app.py 의 채팅 입력 흐름 (reports/evaluation.md 의 브라우저 확인에서 다룸)
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage, AIMessageChunk  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from common.config import texts  # noqa: E402
from rag import graph  # noqa: E402
from rag.evidence import display_fields  # noqa: E402
from ui.components import highlight_chips_html  # noqa: E402

NO_CITATION_ANSWER = "도움이 되었다니 다행입니다. 더 궁금한 점이 있으면 물어보세요."
EVIDENCE = [
    {"n": 1, "chunk_id": "item:Example/ExampleLM-7B", "source_type": "item", "model_id": "Example/ExampleLM-7B",
     "title": "Example/ExampleLM-7B", "url": None, "section": None, "text": "모델: Example/ExampleLM-7B",
     "downloads": 10, "snapshot_date": "2026-10-21"},
    {"n": 2, "chunk_id": "Example/ExampleLM-7B:hf_card:Example/ExampleLM-7B:0", "source_type": "model_card",
     "model_id": "Example/ExampleLM-7B", "title": "Example/ExampleLM-7B", "url": "https://example.org",
     "section": "License", "text": "License: apache-2.0"},
]


class FakeLLM:
    def invoke(self, messages):
        self.messages = messages
        return AIMessage(content=NO_CITATION_ANSWER, usage_metadata={"input_tokens": 1, "output_tokens": 1,
                                                                     "total_tokens": 2})

    def stream(self, messages):  # generate 노드는 스트리밍으로 받아 합친다 (3-1)
        self.messages = messages
        yield AIMessageChunk(content=NO_CITATION_ANSWER, usage_metadata={"input_tokens": 1, "output_tokens": 1,
                                                                         "total_tokens": 2})


def render_message_app():
    import streamlit as st

    from ui.components import render_assistant_extras
    msg = st.session_state["msg"]
    st.markdown(msg["content"])
    render_assistant_extras(msg)


class NoCitationTest(unittest.TestCase):
    def test_generate_marks_no_citation(self):
        with mock.patch.object(graph, "get_llm", return_value=FakeLLM()):
            out = graph.generate({"model_id": "Example/ExampleLM-7B", "question": "고마워", "history": [],
                                  "evidence": EVIDENCE})
        self.assertEqual(out["cited"], [])
        self.assertTrue(out["no_citation"])

    def test_ui_shows_notice_without_evidence_list(self):
        msg = {"role": "assistant", "content": NO_CITATION_ANSWER, "notes": [], "evidence": [], "no_citation": True}
        at = AppTest.from_function(render_message_app)
        at.session_state["msg"] = msg
        at.run()
        self.assertFalse(at.exception)
        captions = [c.value for c in at.caption]
        self.assertTrue(any(texts()["no_citation"] in c for c in captions), captions)
        self.assertEqual(len(at.expander), 0)

    def test_ui_shows_evidence_list_when_cited(self):
        msg = {"role": "assistant", "content": "apache-2.0입니다 [근거 2]", "notes": [],
               "evidence": [display_fields(EVIDENCE[1])], "no_citation": False}
        at = AppTest.from_function(render_message_app)
        at.session_state["msg"] = msg
        at.run()
        self.assertEqual(len(at.expander), 1)
        self.assertFalse(any(texts()["no_citation"] in c.value for c in at.caption))


class MessageTextTest(unittest.TestCase):
    """스트리밍 답변의 글자 추출. 입력은 합성이지만 모양은 2026-10-23 실제 claude-haiku-5-5 스트리밍에서 관찰한 것과 같다
    (thinking 블록 뒤에 text 조각이 문자열로 이어짐). 이 모양을 dict 블록만 읽으면 답변이 빈 문자열이 되던 버그를 막는다."""

    def test_thinking_then_string_pieces(self):
        content = [{"thinking": "", "type": "thinking", "index": 0}, {"signature": "x", "type": "thinking", "index": 0},
                   "이 모델은 ", "Dense 구조입니다 [근거 1]."]
        self.assertEqual(graph.message_text(content), "이 모델은 Dense 구조입니다 [근거 1].")

    def test_plain_string(self):
        self.assertEqual(graph.message_text("답변"), "답변")


class HighlightEscapeTest(unittest.TestCase):
    """highlights 는 LLM 생성 문구라 HTML 이스케이프 (design/retrieval-and-ui.md). 입력은 합성: 실제 요약에는 태그가 없지만 방어 규칙을 고정한다."""

    def test_escaped(self):
        out = highlight_chips_html(['<script>alert(1)</script>', 'a "quoted" 특징'])
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn('title="a &quot;quoted&quot; 특징"', out)


if __name__ == "__main__":
    unittest.main()
