"""답변 본문의 [근거 n] 인용 추출과 '실제 인용된 근거만' 남기기 (F2008).

입력 답변은 합성 문자열이다. 실제 답변은 LLM 출력이라 고정할 수 없어, 형식만 같은 문자열로 규칙을 확인한다.
실제 답변에 대한 확인은 검증 4.3(화면 근거 번호와 목록 일치)에서 한다.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.evidence import cited_evidence, cited_numbers, strip_citations  # noqa: E402

EVIDENCE = [{"n": n, "source_type": "model_card", "title": f"doc{n}"} for n in (1, 2, 3)]


class CitationTest(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(cited_numbers("A [근거 1]. B [근거 3][근거 1]. C [근거3]"), [1, 3])

    def test_only_cited_and_existing(self):
        got = cited_evidence("라이선스는 apache-2.0입니다 [근거 2]. 다른 내용 [근거 9]", EVIDENCE)
        self.assertEqual([ev["n"] for ev in got], [2])

    def test_strip_for_history(self):
        self.assertEqual(strip_citations("128K입니다 [근거 2][근거 3]. 끝 [근거1]"), "128K입니다. 끝")

    def test_no_citation(self):
        self.assertEqual(cited_evidence("제공된 문서에서 확인되지 않습니다.", EVIDENCE), [])


if __name__ == "__main__":
    unittest.main()
