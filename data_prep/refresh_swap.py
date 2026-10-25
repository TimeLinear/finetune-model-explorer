"""교체와 되돌리기 (design/data-refresh.md 6절 "교체와 되돌리기").

- 묶음: 목록(JSON·CSV), 카드 폴더(manifest 포함), 요약, 색인 폴더, 평가 세트 정답(cases.jsonl). 한 묶음으로 바꾼다.
- 교체: 현재 묶음 → data/refresh/prev/, 작업 공간 묶음 → 현재 위치. 전에 있던 prev 는 교체가 성공한 뒤에만 지운다 (한 세대 보관).
- 되돌리기: 현재와 prev 를 맞바꾼다. 다시 실행하면 원래대로 돌아온다.
- 옮기기는 같은 드라이브 안의 이름 바꾸기(os.replace)다. 하나라도 실패하면(앱이 파일을 열고 있는 경우 등) 옮긴 것을 원래대로 돌리고 멈춘다.
- 앱(웹·Streamlit)이 켜져 있으면 교체·되돌리기를 하지 않는다. 포트가 닫혀 있어도 옮기기가 실패하면 앱이 켜져 있는 것으로 본다.
"""
import hashlib
import json
import os
import shutil
import socket
from datetime import datetime, timezone

BUNDLE = {
    "items.json": "data/items.json",
    "items.csv": "data/items.csv",
    "cards": "data/cards",
    "summaries.jsonl": "data/summaries.jsonl",
    "chroma": "data/chroma",
    "cases.jsonl": "tests/retrieval_eval/cases.jsonl",
}
APP_PORTS = {"web": 8000, "streamlit": 8501}  # README "실행 방법"의 기본 포트


class SwapError(RuntimeError):
    pass


def refresh_dir(root):
    return root / "data" / "refresh"


def work_dir(root, day):
    return refresh_dir(root) / "work" / day


def prev_dir(root):
    return refresh_dir(root) / "prev"


def service_paths(root):
    return {name: root / rel for name, rel in BUNDLE.items()}


def bundle_in(folder):
    return {name: folder / name for name in BUNDLE}


def open_ports(ports=None, hosts=("127.0.0.1", "::1")):
    """열려 있는 앱 포트의 이름 목록."""
    found = []
    for name, port in (ports or APP_PORTS).items():
        for host in hosts:
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                try:
                    if s.connect_ex((host, port)) == 0:
                        found.append(f"{name}:{port}")
                        break
                except OSError:
                    continue
    return found


def tree_hash(path):
    """파일이면 내용 해시, 폴더면 (상대 경로 + 파일 해시) 전체의 해시. 없으면 None."""
    if not path.exists():
        return None
    if path.is_file():
        return {"files": 1, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    h, n = hashlib.sha256(), 0
    for p in sorted(q for q in path.rglob("*") if q.is_file()):
        h.update(p.relative_to(path).as_posix().encode("utf-8") + b"\0")
        h.update(hashlib.sha256(p.read_bytes()).digest())
        n += 1
    return {"files": n, "sha256": h.hexdigest()}


def service_hashes(root):
    return {name: tree_hash(p) for name, p in service_paths(root).items()}


def create_workspace(root, work):
    """현재 묶음을 작업 공간으로 복사한다 (서비스 파일은 읽기만 한다)."""
    if work.exists():
        raise SwapError(f"작업 공간이 이미 있음: {work}")
    work.mkdir(parents=True)
    for name, src in service_paths(root).items():
        if src.is_dir():
            shutil.copytree(src, work / name)
        elif src.exists():
            shutil.copy2(src, work / name)


def move_all(pairs, mover=os.replace):
    """[(원래 위치, 새 위치)]를 차례로 옮긴다. 하나라도 실패하면 옮긴 것을 원래대로 돌리고 예외를 다시 낸다."""
    done = []
    try:
        for src, dst in pairs:
            dst.parent.mkdir(parents=True, exist_ok=True)
            mover(src, dst)
            done.append((src, dst))
    except OSError:
        for src, dst in reversed(done):
            mover(dst, src)
        raise


def write_info(prev, action):
    info = {"updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), "last_action": action}
    (prev / "bundle.json").write_text(json.dumps(info, ensure_ascii=False) + "\n", encoding="utf-8")


def swap(root, work, prev, note, mover=os.replace):
    """작업 공간 묶음으로 교체한다. 실패하면 원래대로 돌리고 SwapError."""
    cur, new, old = service_paths(root), bundle_in(work), bundle_in(prev)
    missing = [n for n in BUNDLE if not new[n].exists()]
    if missing:
        raise SwapError(f"작업 공간에 없는 묶음 구성: {missing}")
    stash = prev.with_name(prev.name + "_old")
    if stash.exists():
        raise SwapError(f"지난 교체의 보관본 정리가 끝나지 않음: {stash} (확인 후 수동 처리)")
    had_prev = prev.exists()
    if had_prev:
        mover(prev, stash)
    prev.mkdir(parents=True)
    try:
        move_all([(cur[n], old[n]) for n in BUNDLE if cur[n].exists()], mover)
    except OSError as e:
        prev.rmdir()  # 방금 만든 빈 폴더
        if had_prev:
            mover(stash, prev)
        raise SwapError(f"현재 묶음을 옮기지 못함 ({type(e).__name__}: {e}). 앱이 켜져 있을 수 있음. 원래대로 돌림") from e
    try:
        move_all([(new[n], cur[n]) for n in BUNDLE], mover)
    except OSError as e:
        move_all([(old[n], cur[n]) for n in BUNDLE if old[n].exists()], mover)
        prev.rmdir()
        if had_prev:
            mover(stash, prev)
        raise SwapError(f"새 묶음을 옮기지 못함 ({type(e).__name__}: {e}). 원래대로 돌림") from e
    write_info(prev, note)
    if had_prev:
        shutil.rmtree(stash)  # 교체 성공 후에만 이전 prev 를 지운다


def rollback(root, prev, mover=os.replace):
    """현재 묶음과 prev 를 맞바꾼다. 실패하면 원래대로 돌리고 SwapError."""
    cur, old = service_paths(root), bundle_in(prev)
    missing = [n for n in BUNDLE if not old[n].exists()]
    if missing:
        raise SwapError(f"되돌릴 이전 묶음이 없거나 불완전함: {missing}")
    tmp = {n: cur[n].with_name(cur[n].name + ".rollback") for n in BUNDLE}
    if any(p.exists() for p in tmp.values()):
        raise SwapError("지난 되돌리기의 임시 파일이 남아 있음 (*.rollback). 확인 후 수동 처리")
    try:
        move_all([(cur[n], tmp[n]) for n in BUNDLE], mover)
    except OSError as e:
        raise SwapError(f"현재 묶음을 옮기지 못함 ({type(e).__name__}: {e}). 앱이 켜져 있을 수 있음. 원래대로 돌림") from e
    try:
        move_all([(old[n], cur[n]) for n in BUNDLE], mover)
    except OSError as e:
        move_all([(tmp[n], cur[n]) for n in BUNDLE], mover)
        raise SwapError(f"이전 묶음을 옮기지 못함 ({type(e).__name__}: {e}). 원래대로 돌림") from e
    try:
        move_all([(tmp[n], old[n]) for n in BUNDLE], mover)
    except OSError as e:
        move_all([(cur[n], old[n]) for n in BUNDLE], mover)
        move_all([(tmp[n], cur[n]) for n in BUNDLE], mover)
        raise SwapError(f"현재 묶음을 prev 로 옮기지 못함 ({type(e).__name__}: {e}). 원래대로 돌림") from e
    write_info(prev, "rollback")
