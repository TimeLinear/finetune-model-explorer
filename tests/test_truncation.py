"""구조화 출력 잘림 처리와 C2 출력 검증.

입력은 합성이다: 실제 LLM 대신 잘린 응답 모양(Anthropic stop_reason="max_tokens", OpenAI 호환 finish_reason="length")을
돌려주는 가짜 구조화 출력 LLM 을 쓴다. 잘림은 출력 상한에 걸려야 생겨 실제 호출로 고정해 재현하기 어렵기 때문이다.
파싱이 성공한 것처럼 보여도(parsed 있음) 결과를 쓰지 않고 실패로 처리하는지 확인한다.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage  # noqa: E402

from common import llm  # noqa: E402
from data_prep import summaries, wiki  # noqa: E402
from services import condition_search, usage_check  # noqa: E402

ANTHROPIC_CUT = {"stop_reason": "max_tokens"}
OPENAI_CUT = {"finish_reason": "length"}
USAGE = {"input_tokens": 100, "output_tokens": 2048, "total_tokens": 2148}


def fake_structured(parsed, response_metadata):
    """get_structured_llm(...) 대신 쓰는 가짜. invoke 는 include_raw=True 모양을 돌려준다."""
    raw = AIMessage(content="", response_metadata=response_metadata, usage_metadata=USAGE)
    return SimpleNamespace(invoke=lambda _input: {"raw": raw, "parsed": parsed, "parsing_error": None})


class TruncationTest(unittest.TestCase):
    def assert_truncated_fails(self, call, parsed, meta, prompt_name):
        with mock.patch.object(llm, "get_structured_llm", return_value=fake_structured(parsed, meta)), \
                self.assertLogs("app", level="WARNING") as logs:
            with self.assertRaises(llm.TruncatedOutput):
                call()
        self.assertIn(prompt_name, logs.output[0])
        self.assertIn("output_tokens=2048", logs.output[0])

    def test_is_truncated_both_providers(self):
        self.assertTrue(llm.is_truncated(AIMessage(content="", response_metadata=ANTHROPIC_CUT)))
        self.assertTrue(llm.is_truncated(AIMessage(content="", response_metadata=OPENAI_CUT)))
        self.assertFalse(llm.is_truncated(AIMessage(content="", response_metadata={"stop_reason": "tool_use"})))
        self.assertFalse(llm.is_truncated(AIMessage(content="", response_metadata={"finish_reason": "stop"})))

    def test_p1_truncated(self):
        parsed = wiki.QueryExtraction(queries=[wiki.SearchQuery(query="ExampleLM", reason="계열")], card_query_en="license")
        with mock.patch.object(wiki.store, "get_by_ids", return_value=[]):
            for meta in (ANTHROPIC_CUT, OPENAI_CUT):
                self.assert_truncated_fails(lambda: wiki.extract_queries("Example/ExampleLM-7B", "라이선스는?"),
                                            parsed, meta, "P1 query_extract")

    def test_p2_truncated(self):
        parsed = wiki.DocSelection(decisions=[])
        cands = [{"title": "예시 문서", "summary": "요약"}]
        for meta in (ANTHROPIC_CUT, OPENAI_CUT):
            self.assert_truncated_fails(lambda: wiki.select_candidates("Example/ExampleLM-7B", "질문", cands),
                                        parsed, meta, "P2 doc_select")

    def test_c1_c2_truncated(self):
        f = condition_search.ConditionFilter()
        cands = [{"metadata": {"model_id": "Example/A"}, "text": "모델: Example/A"}]
        picks = condition_search.Picks(picks=[condition_search.Pick(model_id="Example/A", reason="맞음")])
        for meta in (ANTHROPIC_CUT, OPENAI_CUT):
            self.assert_truncated_fails(lambda: condition_search.parse_conditions("이미지 입력 모델"), f, meta,
                                        "C1 condition_parse")
            self.assert_truncated_fails(lambda: condition_search.select("이미지 입력 모델", f, cands), picks, meta,
                                        "C2 condition_select")

    def test_u_truncated(self):
        parsed = usage_check.UsageCheck(rows=[])
        with mock.patch.object(usage_check, "gather_evidence", return_value=[]):
            for meta in (ANTHROPIC_CUT, OPENAI_CUT):
                self.assert_truncated_fails(lambda: usage_check.build_usage_check("Example/ExampleLM-7B"), parsed, meta,
                                            "U usage_check")

    def test_s_truncated_no_retry(self):
        """요약은 잘리면 재시도 없이 SummaryParseError(사용 토큰 포함)로 넘긴다."""
        item = {"model_id": "Example/ExampleLM-7B", "vendor": "Example", "params_b": 7, "input_modalities": ["text"],
                "card_revision": "r1", "card_url": "https://example.org"}
        parsed = summaries.CardSummary(summary_ko="요약", highlights=[], stage_from_card="instruct",
                                       languages_from_card=["en"], card_quality="sufficient")
        for meta in (ANTHROPIC_CUT, OPENAI_CUT):
            chain = mock.Mock()
            chain.invoke.return_value = fake_structured(parsed, meta).invoke(None)
            with mock.patch.object(summaries, "read_card_body", return_value="card"), \
                    self.assertLogs("app", level="WARNING") as logs:
                with self.assertRaises(summaries.SummaryParseError) as ctx:
                    summaries.summarize(item, chain)
            self.assertEqual(chain.invoke.call_count, 1)
            self.assertEqual(ctx.exception.usages, [USAGE])
            self.assertIn("S summary", logs.output[0])

    def test_not_truncated_passes(self):
        parsed = wiki.QueryExtraction(queries=[wiki.SearchQuery(query="ExampleLM", reason="계열")], card_query_en="license")
        with mock.patch.object(llm, "get_structured_llm", return_value=fake_structured(parsed, {"stop_reason": "tool_use"})), \
                mock.patch.object(wiki.store, "get_by_ids", return_value=[]):
            self.assertEqual(wiki.extract_queries("Example/ExampleLM-7B", "라이선스는?").card_query_en, "license")


class ValidatePicksTest(unittest.TestCase):
    """C2 출력 검증: 후보에 없는 ID 버림, 중복 제거, 원래 후보 순서, limit."""

    def test_validate(self):
        P = condition_search.Pick
        cands = [{"metadata": {"model_id": m}} for m in ("Example/A", "Example/B", "Example/C", "Example/D")]
        picks = [P(model_id="Example/C", reason="c"), P(model_id="Example/Z", reason="후보 아님"),
                 P(model_id="Example/A", reason="a"), P(model_id="Example/C", reason="중복"), P(model_id="Example/D", reason="d")]
        self.assertEqual(condition_search.validate_picks(picks, cands, 2), [("Example/A", "a"), ("Example/C", "c")])
        self.assertEqual(condition_search.validate_picks([], cands, 5), [])


if __name__ == "__main__":
    unittest.main()
