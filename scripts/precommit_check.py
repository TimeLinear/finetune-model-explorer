"""커밋 전 검사. 스테이징된 파일에서 비밀 값·금지 문자열·제외 대상 경로를 찾는다.

사용: python scripts/precommit_check.py   (저장소 루트에서. .githooks/pre-commit 이 자동으로 부른다)
설정: git config core.hooksPath .githooks

검사 항목
- .env 가 있으면 그 값 문자열 (8글자 이상만. 짧은 값은 일반 단어와 겹친다)
- 키 형태 문자열 (hf_…, sk-…)
- .claude/forbidden_terms.txt 가 있으면 그 문자열 (대소문자 무시, 파일 이름 포함, 이미지 등 바이너리 제외). 없으면 이 검사만 건너뛴다
- 제외 대상 경로 (.env, .venv, data/chroma, data/cards 원문, logs)
걸리면 파일과 줄 번호만 출력하고(값·문자열은 출력하지 않는다) 종료 코드 1.
"""
import re
import subprocess
import sys
from pathlib import Path

ENV_MIN_LEN = 8
KEY_PATTERN = re.compile(rb"(hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_\-]{20,})")
EXCLUDED_PATH = re.compile(r"^(\.env$|\.venv/|data/chroma/|data/cards/(?!_manifest\.json$)|logs/)")
TERMS_FILE = Path(".claude") / "forbidden_terms.txt"


def env_values(path):
    """[(키 이름, 값 바이트)]. 파일이 없으면 빈 목록."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if len(value) >= ENV_MIN_LEN:
            out.append((key.strip(), value.encode("utf-8")))
    return out


def forbidden_terms(path):
    """금지 문자열 목록 (소문자). 파일이 없으면 None."""
    if not path.exists():
        return None
    return [t.strip().lower() for t in path.read_text(encoding="utf-8").splitlines() if t.strip()]


def line_numbers(data, needle):
    """data 안에서 needle 이 나오는 줄 번호 (1부터)."""
    lines, start = [], 0
    while (i := data.find(needle, start)) != -1:
        lines.append(data.count(b"\n", 0, i) + 1)
        start = i + 1
    return sorted(set(lines))


def check_file(path, data, env_vals, terms):
    """파일 하나의 검사 결과 [(경로, 줄 번호 또는 None, 항목)]. 값·문자열 자체는 담지 않는다."""
    found = []
    if EXCLUDED_PATH.match(path):
        found.append((path, None, "제외 대상 경로"))
    for key, value in env_vals:
        found += [(path, n, f".env 값 ({key})") for n in line_numbers(data, value)]
    found += [(path, data.count(b"\n", 0, m.start()) + 1, "키 형태 문자열") for m in KEY_PATTERN.finditer(data)]
    if terms:
        if any(t in path.lower() for t in terms):
            found.append((path, None, "금지 문자열 (파일 이름)"))
        if b"\0" not in data:  # 바이너리(이미지 등)는 문자열 검사를 하지 않는다
            lower = data.decode("utf-8", "ignore").lower().encode("utf-8")
            for t in terms:
                found += [(path, n, "금지 문자열") for n in line_numbers(lower, t.encode("utf-8"))]
    return found


def staged_files(root):
    """추가·수정된 스테이징 파일 경로 (삭제는 제외)."""
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"],
                         cwd=root, capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def staged_content(root, path):
    return subprocess.run(["git", "show", f":{path}"], cwd=root, capture_output=True, check=True).stdout


def main(root="."):
    root = Path(root)
    env_vals = env_values(root / ".env")
    terms = forbidden_terms(root / TERMS_FILE)
    if terms is None:
        print(f"알림: {TERMS_FILE.as_posix()} 이 없어 금지 문자열 검사를 건너뛴다.")
    files = staged_files(root)
    found = []
    for path in files:
        found += check_file(path, staged_content(root, path), env_vals, terms)
    for path, line, what in found:
        print(f"{path}:{line}: {what}" if line else f"{path}: {what}")
    print(f"커밋 전 검사: 파일 {len(files)}개, 문제 {len(found)}건")
    return 1 if found else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
