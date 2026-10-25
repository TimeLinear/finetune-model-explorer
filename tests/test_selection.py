"""선별 규칙 (data_prep/selection.py, data_prep/catalog_fetch.py).

- 회귀: 2026-10-21 수집 원본(tests/fixtures/raw_models_2026-10-21.json.gz, collect.py 출력 961행)을 기준 날짜
  2026-10-21 로 선별하면 data/items.json 의 202개와 model_id·selection_group·group_rank 가 모두 같아야 한다.
- 조회 결과 1건의 필터 (합성 입력): 언어 모델 여부, 크기 범위, 제외 패턴, 커밋 해시·수정 시각 보존
"""
import gzip
import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_prep.catalog_fetch import catalog_config, to_row  # noqa: E402
from data_prep.selection import select  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "raw_models_2026-10-21.json.gz"
ITEMS = ROOT / "data" / "items.json"


class SelectionRegressionTest(unittest.TestCase):
    def test_fixture_reproduces_items(self):
        with gzip.open(FIXTURE, "rt", encoding="utf-8") as f:
            rows = json.load(f)["rows"]
        self.assertEqual(len(rows), 961)
        picked = select(rows, date(2026, 10, 21))
        items = json.loads(ITEMS.read_text(encoding="utf-8"))
        key = lambda it: (it["model_id"], it["selection_group"], it["group_rank"])  # noqa: E731
        self.assertEqual(len(picked), 202)
        self.assertEqual([key(it) for it in picked], [key(it) for it in items])


def api_model(mid, total=8e9, pipe="text-generation", **extra):
    return {"id": mid, "pipeline_tag": pipe, "safetensors": {"total": total}, "tags": ["conversational"],
            "createdAt": "2025-01-02T00:00:00.000Z", "downloads": 10, "sha": "abc", "lastModified": "2026-10-01T00:00:00Z",
            **extra}


class CatalogRowTest(unittest.TestCase):
    def setUp(self):
        self.cfg = catalog_config()

    def test_keeps_language_model_with_revision(self):
        row, reason = to_row(api_model("google/gemma-x-it"), "google", self.cfg)
        self.assertIsNone(reason)
        self.assertEqual((row["sha"], row["last_modified"], row["created"]), ("abc", "2026-10-01T00:00:00Z", "2025-01-02"))
        self.assertEqual((row["vendor"], row["stage"], row["params_b"]), ("Google", "instruct", 8.0))

    def test_filters(self):
        cases = {
            "언어 모델 아님": api_model("google/x", pipe="automatic-speech-recognition"),
            "크기 범위 밖": api_model("google/huge", total=70e9),
            "제외 패턴": api_model("google/gemma-x-it-GGUF"),
            "파라미터 수 정보 없음": api_model("google/y", total=None),
        }
        for reason, m in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(to_row(m, "google", self.cfg), (None, reason))


if __name__ == "__main__":
    unittest.main()
