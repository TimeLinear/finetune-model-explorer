"""요약 "이미 생성됨" 판정 (data_prep/summaries.py done_keys·item_key): model_id + 카드 본문 해시 + prompt_version.

입력은 합성이지만 실제로 생기는 경우다: 커밋 해시만 바뀌고 README 본문이 같은 "메타데이터만 변경"(design/data-refresh.md 3절)과,
본문이 바뀐 "카드 변경". 실제 목록 전체 확인은 scripts/generate_summaries.py --all --dry-run 으로 한다.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_prep import summaries  # noqa: E402

V = summaries.PROMPT_VERSION


class SummaryKeyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "summaries.jsonl"
        records = [{"model_id": "o/a", "card_revision": "r1", "card_body_sha256": "H1", "prompt_version": V},
                   {"model_id": "o/b", "card_revision": "r1", "card_body_sha256": None, "prompt_version": V}]
        path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        patch = mock.patch.object(summaries, "SUMMARIES_PATH", path)
        patch.start()
        self.addCleanup(patch.stop)
        self.done = summaries.done_keys()

    def is_done(self, mid, rev, manifest):
        return summaries.item_key({"model_id": mid, "card_revision": rev}, manifest) in self.done

    def test_revision_changed_same_body_is_done(self):
        manifest = {"o/a": {"card_revision": "r2", "status": "ok", "body_sha256": "H1"}}
        self.assertTrue(self.is_done("o/a", "r2", manifest))

    def test_body_changed_needs_summary(self):
        manifest = {"o/a": {"card_revision": "r2", "status": "ok", "body_sha256": "H2"}}
        self.assertFalse(self.is_done("o/a", "r2", manifest))

    def test_unknown_hash_needs_summary(self):
        """카드를 아직 그 리비전으로 받지 않았거나, 기록에 해시가 없으면 생성 대상."""
        self.assertFalse(self.is_done("o/a", "r2", {"o/a": {"card_revision": "r1", "status": "ok", "body_sha256": "H1"}}))
        self.assertFalse(self.is_done("o/b", "r1", {"o/b": {"card_revision": "r1", "status": "ok", "body_sha256": None}}))


if __name__ == "__main__":
    unittest.main()
