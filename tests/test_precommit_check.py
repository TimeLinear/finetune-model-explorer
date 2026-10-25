"""커밋 전 검사 스크립트 (scripts/precommit_check.py). 입력은 합성: 가짜 키·가짜 금지 문자열을 쓰고, 임시 git 저장소에서 실제 스테이징을 검사한다.
가짜 키는 문자열을 이어 붙여 만든다 (이 파일 자체가 검사에 걸리지 않도록)."""
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import precommit_check as pc  # noqa: E402

FAKE_HF = "hf" + "_" + "A1b2C3d4" * 3
FAKE_SK = "sk" + "-" + "x" * 24
FAKE_TERM = "가짜금지어"
FAKE_ENV_VALUE = "example-secret-" + "value-123"


class CheckFileTest(unittest.TestCase):
    def test_env_value_reported_by_line_without_value(self):
        env = [("EXAMPLE_KEY", FAKE_ENV_VALUE.encode())]
        found = pc.check_file("a.txt", f"첫 줄\n값={FAKE_ENV_VALUE}\n".encode(), env, [])
        self.assertEqual(found, [("a.txt", 2, ".env 값 (EXAMPLE_KEY)")])
        self.assertNotIn(FAKE_ENV_VALUE, repr(found))

    def test_key_patterns(self):
        found = pc.check_file("b.py", f"x = '{FAKE_HF}'\n\ny = '{FAKE_SK}'\n".encode(), [], [])
        self.assertEqual([(f[1], f[2]) for f in found], [(1, "키 형태 문자열"), (3, "키 형태 문자열")])

    def test_short_prefix_is_not_a_key(self):
        self.assertEqual(pc.check_file("c.md", "키 형태(hf_, sk-) 문자열".encode(), [], []), [])

    def test_forbidden_term_case_insensitive_and_file_name(self):
        terms = ["abcterm", FAKE_TERM]
        found = pc.check_file(f"docs/{FAKE_TERM}.md", f"ok\nAbcTerm 포함\n{FAKE_TERM}\n".encode(), [], terms)
        self.assertIn((f"docs/{FAKE_TERM}.md", None, "금지 문자열 (파일 이름)"), found)
        self.assertEqual(sorted(f[1] for f in found if f[2] == "금지 문자열"), [2, 3])

    def test_ascii_term_matches_whole_word_only(self):
        """영문 금지어는 다른 영어 단어 속에서는 통과, 단독·구분 문자 앞뒤에서는 걸린다 (가짜 금지어 zqx)."""
        text = "paradigzqxs\nZQX 키\nzqxs\nazqx\nzqx_1\nv.zqx-2\n(zqx)\nzqx3\n한글zqx한글\n"
        found = pc.check_file("notes.md", text.encode(), [], ["zqx"])
        self.assertEqual([f[1] for f in found], [2, 5, 6, 7, 9])

    def test_ascii_term_in_file_name(self):
        self.assertEqual(pc.check_file("docs/zqxs.md", b"", [], ["zqx"]), [])
        for name in ["docs/zqx.md", "docs/a_zqx-b.md", "ZQX/x.md"]:
            self.assertEqual(pc.check_file(name, b"", [], ["zqx"]), [(name, None, "금지 문자열 (파일 이름)")], name)

    def test_korean_term_is_substring(self):
        found = pc.check_file("k.md", f"앞{FAKE_TERM}뒤\nabc{FAKE_TERM}\n".encode(), [], [FAKE_TERM])
        self.assertEqual([f[1] for f in found], [1, 2])

    def test_binary_skips_term_check_but_not_keys(self):
        data = b"\x89PNG\0" + FAKE_TERM.encode() + b" " + FAKE_HF.encode()
        found = pc.check_file("img.png", data, [], [FAKE_TERM])
        self.assertEqual([f[2] for f in found], ["키 형태 문자열"])

    def test_excluded_paths(self):
        for path in [".env", ".venv/x.py", "data/chroma/a.bin", "data/cards/x__y.md", "logs/app.log"]:
            self.assertIn((path, None, "제외 대상 경로"), pc.check_file(path, b"", [], None), path)
        for path in ["data/cards/_manifest.json", ".env.example", "data/items.json"]:
            self.assertEqual(pc.check_file(path, b"", [], None), [], path)


class ReadInputsTest(unittest.TestCase):
    def test_env_values_skips_comments_empty_and_short(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text(f"# 주석\nA_KEY={FAKE_ENV_VALUE}\nEMPTY=\nSHORT=abc\nQ=\"{FAKE_ENV_VALUE}2\"\n", encoding="utf-8")
            self.assertEqual([k for k, _ in pc.env_values(p)], ["A_KEY", "Q"])
            self.assertEqual(pc.env_values(Path(d) / "없음"), [])

    def test_missing_terms_file_is_none(self):
        self.assertIsNone(pc.forbidden_terms(Path("없는/경로.txt")))


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class StagedRepoTest(unittest.TestCase):
    """임시 git 저장소에 파일을 스테이징하고 main() 의 종료 코드와 출력을 확인한다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, "init", "-q")
        (self.root / ".env").write_text(f"EXAMPLE_KEY={FAKE_ENV_VALUE}\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = pc.main(self.root)
        return code, buf.getvalue()

    def stage(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        git(self.root, "add", "-f", name)

    def test_clean_passes_and_notes_missing_terms_file(self):
        self.stage("README.md", "깨끗한 문서\n")
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("금지 문자열 검사를 건너뛴다", out)

    def test_problems_fail_without_printing_values(self):
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "forbidden_terms.txt").write_text(FAKE_TERM + "\n", encoding="utf-8")
        self.stage("notes.md", f"줄1\n{FAKE_TERM}\n토큰 {FAKE_ENV_VALUE}\n")
        self.stage("logs/app.log", "로그\n")
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("notes.md:2: 금지 문자열", out)
        self.assertIn("notes.md:3: .env 값 (EXAMPLE_KEY)", out)
        self.assertIn("logs/app.log: 제외 대상 경로", out)
        self.assertNotIn(FAKE_ENV_VALUE, out)
        self.assertNotIn(FAKE_TERM, out)


if __name__ == "__main__":
    unittest.main()
