"""config/settings.json 의 값이 설계 문서(docs/design/retrieval-and-ui.md) "검색 설정" 표의 기본값과 같은지 대조한다.

입력은 실제 파일 두 개(설계 문서, 설정 파일)다. 표에 키가 추가되면 이 테스트가 그대로 대상에 넣는다.
실행: python -m unittest discover tests
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "design" / "retrieval-and-ui.md"
SETTINGS = ROOT / "config" / "settings.json"
ROW = re.compile(r"^\|\s*`([\w.]+)`\s*\|\s*([^|]+?)\s*\|")


def parse_value(raw):
    """표의 기본값 칸: `similarity` → 문자열, `["a", "b"]` → 목록, 1000 (글자) → 1000, true → True, 0.5 → 0.5"""
    raw = raw.strip()
    if raw.startswith("`") and raw.endswith("`"):
        inner = raw.strip("`")
        return json.loads(inner) if inner.startswith("[") else inner
    raw = re.sub(r"\s*\(.*\)$", "", raw)  # "1000 (글자)" 같은 단위 설명
    return json.loads(raw)


def doc_defaults():
    section = DOC.read_text(encoding="utf-8").split("\n## 검색 설정")[1].split("\n## ")[0]
    return {m.group(1): parse_value(m.group(2)) for line in section.splitlines() if (m := ROW.match(line))}


def lookup(settings, key):
    node = settings
    for part in key.split("."):
        node = node[part]
    return node


class SettingsDefaultsTest(unittest.TestCase):
    def test_table_has_expected_keys(self):
        keys = doc_defaults()
        self.assertGreaterEqual(len(keys), 20)
        for k in ("chunk.size", "retrieve.card_k", "retrieve.wiki_k", "usage_check.card_k",
                  "hf.request_interval_sec", "http.max_retries",
                  "chunk.exclude_sections", "card.front_matter_keys", "index.version"):
            self.assertIn(k, keys)

    def test_no_keys_outside_doc(self):
        """표에서 지운 키(예: retrieve.docs_k)가 설정 파일에 남아 있지 않은지"""
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        leaves = [f"{a}.{b}" for a, sub in settings.items() for b in sub]
        self.assertEqual(sorted(set(leaves) - set(doc_defaults())), [])

    def test_settings_match_doc(self):
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        for key, expected in doc_defaults().items():
            with self.subTest(key=key):
                actual = lookup(settings, key)
                self.assertEqual(actual, expected)
                self.assertIs(type(actual), type(expected))


if __name__ == "__main__":
    unittest.main()
