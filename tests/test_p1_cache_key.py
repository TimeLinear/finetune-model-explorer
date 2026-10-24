"""P1 저장 키에 프롬프트 버전과 P1 모델(LLM_SMALL)이 들어가는지. LLM 을 호출하지 않는다."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_prep import wiki  # noqa: E402


class P1CacheKeyTest(unittest.TestCase):
    def test_key_has_version_and_model(self):
        key = wiki.question_key("Example/ExampleLM-7B", "  이 모델의  라이선스는? ")
        self.assertEqual(key, f"Example/ExampleLM-7B|{wiki.P1_PROMPT_VERSION}|{wiki.model_name('LLM_SMALL')}|이 모델의 라이선스는?")

    def test_model_change_changes_key(self):
        before = wiki.question_key("Example/ExampleLM-7B", "질문")
        with mock.patch.dict(os.environ, {"LLM_SMALL": "anthropic:example-small-model"}):
            after = wiki.question_key("Example/ExampleLM-7B", "질문")
        self.assertNotEqual(before, after)
        self.assertIn("|example-small-model|", after)


if __name__ == "__main__":
    unittest.main()
