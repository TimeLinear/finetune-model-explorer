"""카드 머리말 텍스트와 저가치 섹션 제외 (design/collections.md 3절 "카드 머리말과 섹션 처리").

입력은 합성이다: 카드 원문(data/cards)은 저장소에 없어 clone 한 환경에서도 돌도록 짧은 마크다운·머리말 dict 를 쓴다.
실제 카드에 대한 확인은 색인 결과(front_matter 조각 수, 제외 청크 수, 검증 문서)에서 한다.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_prep.cards import front_matter_text  # noqa: E402
from vectorstore.chunking import split_markdown  # noqa: E402

CARD = """# ExampleLM-7B

Intro text.

## License

Apache 2.0.

## Citation

@misc{example}

## Table of Contents

- a

## Contributors

### Team A

Alice
"""
EXCLUDE = ("citation", "bibtex", "contributors", "acknowledg", "table of contents", "contact")


class CardSectionTest(unittest.TestCase):
    def test_excluded_sections_and_children(self):
        chunks, excluded = split_markdown(CARD, EXCLUDE)
        sections = {s for _, s, _ in chunks}
        self.assertEqual(sections, {"ExampleLM-7B", "License"})
        # Citation, Table of Contents, Contributors(본문 없는 소제목이라 하위 Team A 와 한 청크) = 3
        self.assertEqual(excluded, 3)

    def test_no_exclusion_by_default(self):
        chunks, excluded = split_markdown(CARD)
        self.assertEqual(excluded, 0)
        self.assertIn("Citation", {s for _, s, _ in chunks})

    def test_front_matter_only_listed_keys(self):
        fm = {"license": "other", "language": ["en", "ko"], "tags": ["x"], "model-index": [{"a": 1}],
              "extra_gated_prompt": "Not granted in the EU.", "base_model": None}
        text = front_matter_text(fm, ["license", "extra_gated_prompt", "language", "base_model"])
        self.assertEqual(text, "license: other\nextra_gated_prompt: Not granted in the EU.\nlanguage: en, ko")


if __name__ == "__main__":
    unittest.main()
