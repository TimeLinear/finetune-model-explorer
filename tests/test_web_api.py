"""웹 화면 백엔드 (F2013, web/api.py) 와 화면 이스케이프.

입력은 합성이다: 카드 색인·위키 수집·답변 스트리밍을 가짜 함수로 바꿔 LLM·외부 API 를 부르지 않는다.
- status, models: 실제 색인·항목 파일을 읽는다 (읽기만)
- chat: SSE 이벤트 순서(stage … → token … → done)와 done 의 인용 근거, 오류 시 짧은 문구만 나가는지
- 이스케이프: 화면 코드(web/static/js/common.js)의 renderMarkdown 을 node 로 실행해 <script> 가 글자로 남는지
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from common import perf  # noqa: E402
from web import api  # noqa: E402

MODEL = "google/gemma-3-4b-it"
EVIDENCE = [
    {"n": 1, "chunk_id": "item:x", "source_type": "item", "title": MODEL, "url": None, "section": None, "text": "본문"},
    {"n": 2, "chunk_id": "c:2", "source_type": "model_card", "title": MODEL, "url": "https://example.org",
     "section": "Inputs", "text": "본문"},
]


def parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def fake_stream(model_id, question, history=None, card_query_en=None):
    yield "token", "입력은 "
    yield "token", "128K입니다 [근거 2]"
    yield "final", {"answer": "입력은 128K입니다 [근거 2]", "cited": [EVIDENCE[1]], "no_citation": False,
                    "history_seen": history}


class WebApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api.app)
        # 웹 요청은 요청 단위 성능 기록을 남긴다. 테스트 기록이 실제 logs/perf.jsonl 에 섞이지 않게 임시 폴더로 바꾼다
        self.tmp = tempfile.TemporaryDirectory()
        self.perf_patch = mock.patch.object(perf, "PERF_PATH", Path(self.tmp.name) / "perf.jsonl")
        self.perf_patch.start()

    def tearDown(self):
        self.perf_patch.stop()
        self.tmp.cleanup()

    def test_status(self):
        r = self.client.get("/api/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(set(body), {"items", "docs", "api_key", "profile", "history_turns"})
        self.assertIn(body["api_key"], ("ok", "missing"))  # 키 값·변수 이름은 내보내지 않는다

    def test_models(self):
        body = self.client.get("/api/models").json()
        self.assertEqual(len(body["models"]), 202)
        self.assertEqual(set(body["models"][0]), {"model_id", "vendor", "params_b", "input_modalities", "stage", "license"})
        detail = self.client.get(f"/api/models/{MODEL}").json()
        self.assertEqual(detail["model_id"], MODEL)
        self.assertIn("highlights", detail)
        self.assertEqual(self.client.get("/api/models/none/none").status_code, 404)

    def chat(self, **patches):
        defaults = {"missing_api_keys": [], "ensure_card_indexed": "done",
                    "collect_for_question": {"card_query_en": "context", "new_titles": ["예시 문서"], "queries": []}}
        defaults.update(patches)
        with mock.patch.object(api, "missing_api_keys", return_value=defaults["missing_api_keys"]), \
                mock.patch.object(api, "ensure_card_indexed", return_value=defaults["ensure_card_indexed"]), \
                mock.patch.object(api, "collect_for_question", return_value=defaults["collect_for_question"]), \
                mock.patch.object(api, "stream_answer", side_effect=patches.get("stream", fake_stream)):
            return self.client.post("/api/chat", json={
                "model_id": MODEL, "question": "컨텍스트 길이는?",
                "history": [{"role": "user", "content": "이전 질문"}, {"role": "assistant", "content": "이전 답 [근거 1]"},
                            {"role": "system", "content": "무시돼야 함"}]})

    def test_chat_event_order(self):
        r = self.chat()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/event-stream"))
        events = parse_sse(r.text)
        kinds = [k for k, _ in events]
        first_token = kinds.index("token")
        self.assertTrue(all(k == "stage" for k in kinds[:first_token]))
        self.assertEqual(kinds[-1], "done")
        self.assertIn("수집된 위키 문서: 예시 문서", [d["text"] for k, d in events if k == "stage"])
        done = events[-1][1]
        self.assertEqual(done["answer"], "입력은 128K입니다 [근거 2]")
        self.assertEqual(done["evidence"], [{"n": 2, "source_type": "model_card", "title": MODEL,
                                             "url": "https://example.org", "section": "Inputs"}])  # 본문 텍스트는 보내지 않는다
        self.assertFalse(done["no_citation"])

    def test_chat_history_cleaned(self):
        seen = {}

        def capture(model_id, question, history=None, card_query_en=None):
            seen["history"] = history
            yield from fake_stream(model_id, question, history, card_query_en)

        self.chat(stream=capture)
        self.assertEqual([h["role"] for h in seen["history"]], ["user", "assistant"])  # system 역할은 버린다

    def test_chat_error_is_short(self):
        def boom(*a, **k):
            raise RuntimeError("secret detail must not leak")
            yield  # noqa: unreachable — 제너레이터로 만들기 위함

        with self.assertLogs("web", level="ERROR"):  # 상세는 로그로만 (테스트에서는 실제 로그 파일에 쓰지 않는다)
            r = self.chat(stream=boom)
        events = parse_sse(r.text)
        self.assertEqual(events[-1][0], "error")
        self.assertNotIn("secret", r.text)
        self.assertEqual(events[-1][1]["text"], api.T["error_generic"])

    def test_chat_blocked_without_key(self):
        r = self.chat(missing_api_keys=["ANTHROPIC_API_KEY"])
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"], api.T["missing_key"])


@unittest.skipUnless(shutil.which("node"), "node 가 없으면 화면 이스케이프 테스트를 건너뛴다")
class RenderEscapeTest(unittest.TestCase):
    """LLM 답변에 <script> 가 들어 있어도 화면에는 글자로 나와야 한다 (innerHTML 로 넣는 유일한 경로)."""

    def render(self, text):
        js = ("const m = require(process.argv[1]); process.stdout.write(m.renderMarkdown(process.argv[2], 'ev-0', '근거'));")
        out = subprocess.run(["node", "-e", js, str(ROOT / "web/static/js/common.js"), text],
                             capture_output=True, text=True, encoding="utf-8", check=True)
        return out.stdout

    def test_script_is_text(self):
        html = self.render('<script>alert(1)</script> <img src=x onerror="alert(2)"> **굵게** [근거 2]')
        self.assertNotIn("<script", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("&quot;alert(2)&quot;", html)
        self.assertIn("<strong>굵게</strong>", html)
        self.assertIn('<a class="cite" href="#ev-0-2">[근거 2]</a>', html)

    def test_lists_and_paragraphs(self):
        html = self.render("첫 문단\n\n- 하나 <b>\n- 둘\n\n1. 셋")
        self.assertEqual(html, "<p>첫 문단</p><ul><li>하나 &lt;b&gt;</li><li>둘</li></ul><ol><li>셋</li></ol>")


if __name__ == "__main__":
    unittest.main()
