"""위키 선별 0건 재시도 규칙. LLM·위키 API 를 부르지 않는다 (합성 기록).

- 선별 0건 + 같은 모델·같은 P2 버전 → 다시 부르지 않음
- 선별 0건 + 다른 모델(또는 다른 P2 버전) → 다시 검색·선별
- 1건 이상 선별 → 모델이 달라도 다시 부르지 않음 (NF2002)
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_prep import wiki  # noqa: E402

MODEL = "Example/ExampleLM-7B"


def qlog(selected, select_model, version=wiki.P2_PROMPT_VERSION):
    return {"query": "q", "candidates": [{"title": "문서", "selected": selected}],
            "select_model": select_model, "prompt_version": version}


class ReselectTest(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"LLM_SMALL": "anthropic:example-small"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def log(self, **queries):
        return {"queries": dict(queries), "indexed": {f"{MODEL}|{k}": {"titles": []} for k in queries}}

    def keys(self, log, *words):
        return wiki.keys_to_select(MODEL, [wiki.SearchQuery(query=w, reason="r") for w in words], log)

    def test_zero_same_model_skipped(self):
        log = self.log(a=qlog(False, "example-small"))
        self.assertFalse(wiki.needs_reselect(log["queries"]["a"]))
        self.assertEqual(self.keys(log, "a"), {})

    def test_zero_other_model_retried(self):
        log = self.log(a=qlog(False, "gpt-5.4-nano"), b=qlog(False, "example-small", version="v0.2"))
        self.assertEqual(self.keys(log, "a", "b"), {"a": "a", "b": "b"})  # 모델이 다르거나 P2 버전이 다르면 재시도

    def test_selected_never_retried(self):
        log = self.log(a=qlog(True, "gpt-5.4-nano"))
        self.assertFalse(wiki.needs_reselect(log["queries"]["a"]))
        self.assertEqual(self.keys(log, "a"), {})

    def test_new_query_still_collected(self):
        self.assertEqual(self.keys(self.log(), "새 검색어"), {"새 검색어": "새 검색어"})


if __name__ == "__main__":
    unittest.main()
