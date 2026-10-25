"""데이터 갱신 2단계 수동 반영 (data_prep/refresh_apply.py, refresh_swap.py, refresh_worker.py). HTTP·LLM 은 가짜다.

입력이 합성인 이유: 2026-10-25 실제 갱신은 신규 3·카드 변경 1(예상 $0.07), 평가 세트 모델 카드 변경 0건이라
비용 상한·급변·정답 재연결·심각 판정·이동 실패가 실제로는 일어나지 않는다. 실제 입력은 10절 실행
(data/refresh/2026-10-25.json, 되돌리기 실측)에서 다룬다. 각 테스트에 실제로 생길 수 있는 입력인지 적었다.
"""
import json
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_prep import cards, summaries  # noqa: E402
from data_prep import refresh_apply as ra  # noqa: E402
from data_prep import refresh_swap as rs_  # noqa: E402
from data_prep.refresh import judge  # noqa: E402
from vectorstore import docs_index  # noqa: E402

REF = date(2026, 10, 25)
CFG = {  # 그룹 하나(general), 21개 → k = 4, 퇴출 순위 6 (tests/test_refresh.py 와 같은 구성)
    "orgs": {"o": {"vendor": "V", "country": "US"}},
    "duplicate_pattern": "(?!x)x", "duplicate_exempt_orgs": [], "featured_regions": {},
    "general_pct": 0.2, "special_pct": 0.3, "special_min": 2, "category_rules": [],
}
RS = {"exit_rank_factor": 1.5, "exit_streak_required": 2, "protect_days": 30, "grace_days": 30, "max_cost_usd": 1.0,
      "anomaly_ratio": 0.2, "batch_threshold": 30}


def row(n, downloads, created="2024-01-01", sha=None):
    return {"id": f"o/m{n:02d}", "org": "o", "vendor": "V", "params_b": 7.0, "pipeline": "text-generation",
            "license": "mit", "languages": None, "gated": False, "downloads": downloads, "tags": [], "created": created,
            "sha": sha or f"sha{n}"}


def item(n, **extra):
    return {"model_id": f"o/m{n:02d}", "vendor": "V", "org": "o", "selection_group": "general", "category": "general",
            "license": "mit", "gated": False, "downloads_30d": 1, "downloads_30d_adj": 1, "group_rank": "?",
            "created_at": "2024-01-01", "status": "active", "first_seen": "2026-10-21", "last_qualified": "2026-10-21",
            "snapshot_date": "2026-10-21", "card_revision": f"sha{n}", **extra}


def catalog(n=21):
    return {"rows": [row(i, 3000 - 100 * i) for i in range(1, n + 1)], "excluded": {}, "failed_orgs": {}}


class ItemFieldsTest(unittest.TestCase):
    """판정 → 새 목록의 필드 (1-3). 실제로 생기는 입력: 유지·신규·보관 예정·재활성·판정 보류 모두 실제 판정 결과 유형이다."""

    def test_fields(self):
        items = [item(1), item(5, exit_streak=1), item(7), item(8, exit_streak=1), item(2, status="archived"),
                 {**item(40), "org": "down"}]
        cat = {**catalog(), "failed_orgs": {"down": "HTTP 500"}}
        judged = judge(items, cat, REF, rs=RS, cfg=CFG)
        checks = [{"model_id": "o/m01", "decision": "keep", "result": "card_changed", "new_revision": "new1"},
                  {"model_id": "o/m03", "decision": "new", "result": "new_card", "new_revision": "sha3"}]
        out, fallback = ra.build_items(items, judged, cat, checks, REF, CFG)
        by = {it["model_id"]: it for it in out}
        day = REF.isoformat()
        m1 = by["o/m01"]  # 1위 (진입 순위 안) 유지 + 카드 변경
        self.assertEqual((m1["last_qualified"], m1["snapshot_date"], m1["exit_streak"], m1["card_revision"],
                          m1["group_rank"], m1["first_seen"]), (day, day, 0, "new1", "1/21", "2026-10-21"))
        self.assertEqual(fallback["o/m01"]["card_revision"], "sha1")  # 반영 실패 시 리비전 그대로
        m5 = by["o/m05"]  # 5위: 진입~퇴출 사이 → 연속 횟수 0, last_qualified 그대로
        self.assertEqual((m5["exit_streak"], m5["last_qualified"]), (0, "2026-10-21"))
        self.assertEqual((by["o/m07"]["exit_streak"], by["o/m07"]["status"]), (1, "active"))
        self.assertEqual((by["o/m08"]["exit_streak"], by["o/m08"]["status"]), (2, "archived"))
        self.assertEqual((by["o/m02"]["status"], by["o/m02"]["last_qualified"]), ("active", day))  # 재활성
        self.assertEqual(fallback["o/m02"]["status"], "archived")
        self.assertEqual(by["o/m40"], {**items[-1], "exit_streak": 0})  # 판정 보류: 바꾸지 않음 (필드만 추가)
        m3 = by["o/m03"]  # 신규
        self.assertEqual((m3["first_seen"], m3["status"], m3["card_revision"], m3["exit_streak"]),
                         (day, "active", "sha3", 0))
        self.assertIsNone(fallback["o/m03"])
        self.assertNotIn("o/m03", {it["model_id"] for it in ra.apply_fallback(out, fallback, ["o/m03"])})


def summary_check(mid, decision, result, chars=10000):
    return {"model_id": mid, "decision": decision, "result": result, "new_revision": f"r-{mid}", "body_chars": chars}


class PlanTest(unittest.TestCase):
    """반영 대상·이월 (3절). 합성: 실제 갱신(대상 4개, $0.07)은 상한 $1 에 닿지 않는다."""

    def judged(self, ranks):
        return {"results": [{"model_id": m, "decision": d, "rank": r, "group": "general"} for m, d, r in ranks]}

    def test_priority_and_limit(self):
        judged = self.judged([("a", "new", 5), ("b", "new", 2), ("c", "reactivate", 1), ("d", "keep", 9),
                              ("e", "keep", 3)])
        checks = [summary_check("a", "new", "new_card"), summary_check("b", "new", "new_card"),
                  summary_check("c", "reactivate", "card_changed"), summary_check("d", "keep", "card_changed"),
                  {"model_id": "e", "decision": "keep", "result": "fetch_failed", "reason": "HTTP 403"}]
        one = ra.usage_cost(800 + 5000, 450)  # 카드 1만 자 → 입력 5,800 · 출력 450 토큰
        plan = ra.plan_targets(judged, checks, 24000, max_cost=one * 3 + 1e-9, batch_threshold=30)
        # 우선순위: 기존 모델 카드 변경(d) → 재활성(c) → 신규(그룹 순위 높은 b, 그다음 a)
        self.assertEqual([t["model_id"] for t in plan["targets"]], ["d", "c", "b"])
        carried = {c["model_id"]: c for c in plan["carried"]}
        self.assertIn("예상 비용 상한 초과", carried["a"]["reason"])
        self.assertTrue(carried["e"]["gated"])  # 게이트 승인 필요는 따로 표시
        self.assertEqual(plan["warnings"], [])
        many = ra.plan_targets(judged, checks, 24000, max_cost=10, batch_threshold=3)
        self.assertIn("배치 API 전환 검토", many["warnings"][0])

    def test_run_targets_actual_cost(self):
        targets = [{"model_id": m, "est_cost": 0.02} for m in "abcd"]
        usages = {"a": [{"input_tokens": 100_000, "output_tokens": 1000}],  # 실제 $0.21 (예상보다 큼)
                  "b": [{"input_tokens": 1000, "output_tokens": 100}]}

        def process(t):
            if t["model_id"] == "c":
                raise ra.ModelFailed("요약 실패", [{"input_tokens": 10, "output_tokens": 0}])
            return usages.get(t["model_id"], [])
        applied, carried, spent = ra.run_targets(targets, process, max_cost=0.22)
        self.assertEqual([t["model_id"] for t in applied], ["a"])
        self.assertEqual([c["model_id"] for c in carried], ["b", "c", "d"])  # a 이후 상한을 넘어 남은 모델 이월
        self.assertIn("실제 비용 상한 초과", carried[0]["reason"])
        applied, carried, spent = ra.run_targets(targets, process, max_cost=10)
        self.assertEqual([c["model_id"] for c in carried], ["c"])  # 실패한 모델만 이월, 나머지는 계속
        self.assertEqual(spent["calls"], 3)  # 실패한 호출도 센다

    def test_stop_carries_rest(self):
        targets = [{"model_id": m, "est_cost": 0.01} for m in "abc"]

        def process(t):
            if t["model_id"] == "a":
                raise ra.ModelFailed("LLM 호출 상한 8회", stop=True)
            return []
        applied, carried, _ = ra.run_targets(targets, process, max_cost=1)
        self.assertEqual((applied, [c["model_id"] for c in carried]), ([], ["a", "b", "c"]))


class AnomalyTest(unittest.TestCase):
    """급변 검사 (2절). 합성: 실제 갱신(2026-10-25)은 변화 3개 / 기준 40.4 로 통과한다."""

    def test_threshold(self):
        items = [{"model_id": str(i), "status": "active"} for i in range(10)] + [{"model_id": "x", "status": "archived"}]
        results = [{"decision": d} for d in ["new", "new", "archive", "keep", "hold"]]
        a = ra.anomaly_check(results, items, 0.2)
        self.assertEqual((a["changes"], a["active"], a["limit"], a["exceeded"], a["stop"]), (3, 10, 2.0, True, True))
        self.assertFalse(ra.anomaly_check(results, items, 0.2, allow_large=True)["stop"])
        self.assertFalse(ra.anomaly_check(results, items, 0.3)["exceeded"])

    def test_eval_set_erosion(self):
        """평가 세트 6개 중 3개가 보관 예정·카드 변경이면 재작성 검토 (합성: 실제 갱신(2026-10-25)은 0개)."""
        results = [{"model_id": "a", "decision": "archive"}, {"model_id": "b", "decision": "keep"}]
        checks = [{"model_id": "b", "result": "card_changed"}, {"model_id": "c", "result": "card_changed"}]
        self.assertTrue(ra.eval_set_erosion(results, checks, list("abcdef"))["review"])
        self.assertFalse(ra.eval_set_erosion(results, checks[:1], list("abcdef"))["review"])


def case(gold, evidence):
    return {"case_id": "c01", "model_id": "o/x", "topic": "license", "phrasings": ["q"], "gold_chunk_ids": gold,
            "evidence": evidence}


def chunk(i, text):
    return {"id": f"o/x:hf_card:o/x:{i}", "text": text, "metadata": {"chunk_index": i}}


class RelinkTest(unittest.TestCase):
    """정답 다시 연결 (5-2). 합성: 실제 갱신(2026-10-25)은 평가 세트 모델 카드가 바뀌지 않았다. 사례 형식은 cases.jsonl 과 같다."""

    def test_found(self):
        c = case(["o/x:hf_card:o/x:0", "o/x:hf_card:o/x:9"],
                 [{"chunk_id": "o/x:hf_card:o/x:0", "sentence": "license: llama3.2"},
                  {"chunk_id": "o/x:hf_card:o/x:9", "sentence": "governed by the  Llama 3.2\nCommunity License"}])
        chunks = [chunk(0, "license: llama3.2"), chunk(3, "intro"),
                  chunk(12, "Use of it is governed by the Llama 3.2 Community License (a custom license).")]
        new, info = ra.relink_case(c, chunks)
        self.assertEqual(info["status"], "relinked")
        self.assertEqual(new["gold_chunk_ids"], ["o/x:hf_card:o/x:0", "o/x:hf_card:o/x:12"])  # 공백 차이는 무시
        self.assertEqual(new["phrasings"], c["phrasings"])

    def test_not_found_is_a(self):
        c = case(["o/x:hf_card:o/x:0"], [{"chunk_id": "o/x:hf_card:o/x:0", "sentence": "license: llama3.2"}])
        new, info = ra.relink_case(c, [chunk(0, "license: llama3.3")], b_possible=True)
        self.assertEqual((info["status"], info["b_possible"], new), ("A", True, c))  # 사례는 그대로, A·B 가능성 표시

    def test_important_change_marks_b(self):
        old = {"license": "llama3.2", "gated": True, "max_position_embeddings": 8192}
        new = {"license": "llama3.3", "gated": True, "max_position_embeddings": 131072}
        self.assertEqual(ra.important_changes(old, new),
                         {"license": {"before": "llama3.2", "after": "llama3.3"},
                          "max_position_embeddings": {"before": 8192, "after": 131072}})
        self.assertEqual(ra.important_changes(old, {**old}), {})

    def test_chunk_check(self):
        """청크 수 급변·머리말 누락 (5-1). 실제 입력 형식: index_status.json 의 모델 기록."""
        self.assertEqual(ra.chunk_check({"chunks": 10, "front_matter_chunks": 1}, {"chunks": 5, "front_matter_chunks": 0})
                         ["flags"], ["청크 수 절반 이하", "머리말 청크 누락"])
        self.assertEqual(ra.chunk_check({"chunks": 10}, {"chunks": 20})["flags"], ["청크 수 두 배 이상"])
        self.assertEqual(ra.chunk_check({"chunks": 10}, {"chunks": 11})["flags"], [])


def eval_rows(model, n, hits):
    return [{"case_id": f"{model}-c{i // 3}", "model_id": model, "question": f"q{i}", "rep": 0, "hit": i < hits}
            for i in range(n)]


class VerdictTest(unittest.TestCase):
    """교체 판정 (6-1). 합성: 실제 갱신(2026-10-25)은 C 0건(정상)이다."""

    def verdict(self, c_count, model_queries=12):
        before = eval_rows("a", model_queries, model_queries) + eval_rows("b", 12, 12)
        after = eval_rows("a", model_queries, model_queries - c_count) + eval_rows("b", 12, 12)
        cls = ra.classify_eval(before, after, set())
        return ra.verdict(cls["c"], after, set())

    def test_levels(self):
        self.assertEqual(self.verdict(0)["level"], "normal")
        v3 = self.verdict(3)
        self.assertEqual((v3["level"], v3["c_count"], v3["swap"]), ("minor", 3, True))
        self.assertEqual(self.verdict(4)["level"], "severe")
        half = self.verdict(3, model_queries=5)  # 한 모델 질의 5개 중 3개가 C (절반 초과) → 심각
        self.assertEqual((half["level"], half["swap"]), ("severe", False))
        self.assertEqual(self.verdict(2, model_queries=4)["level"], "minor")  # 정확히 절반은 심각 아님

    def test_a_excluded(self):
        before = eval_rows("a", 6, 6)
        after = eval_rows("a", 6, 0)
        cls = ra.classify_eval(before, after, {"a-c0", "a-c1"})
        self.assertEqual((len(cls["a"]), len(cls["c"])), (6, 0))

    def test_constants_match_design_table(self):
        """상수가 design/data-refresh.md 6절 표의 숫자와 같은가."""
        text = (ROOT / "docs" / "design" / "data-refresh.md").read_text(encoding="utf-8")
        section = text.split("## 6. 교체 판정")[1].split("### ")[0]
        rows = {cells[0]: cells[1] for cells in
                ([c.strip() for c in line.strip("|").split("|")] for line in section.splitlines() if line.startswith("|"))}
        self.assertIn("C 유형 0건", rows["정상"])
        self.assertEqual(int(re.search(r"(\d+)건 이하", rows["경미"]).group(1)), ra.MINOR_MAX_C)
        self.assertEqual(int(re.search(r"(\d+)건 이상", rows["심각"]).group(1)), ra.SEVERE_MIN_C)
        self.assertIn("절반 넘게", rows["심각"])
        self.assertEqual(ra.MODEL_SEVERE_FRACTION, 0.5)


def make_bundle(root, tag):
    for name, rel in rs_.BUNDLE.items():
        p = root / rel
        if name in ("cards", "chroma"):
            p.mkdir(parents=True, exist_ok=True)
            (p / "f.txt").write_text(f"{name}-{tag}", encoding="utf-8")
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"{name}-{tag}", encoding="utf-8")


def bundle_tags(folder_map):
    out = {}
    for name, p in folder_map.items():
        f = p / "f.txt" if name in ("cards", "chroma") else p
        out[name] = f.read_text(encoding="utf-8").rsplit("-", 1)[1] if f.exists() else None
    return set(out.values()) if len(set(out.values())) == 1 else out


class SwapTest(unittest.TestCase):
    """교체·되돌리기 (6-2·6-4). 임시 폴더에서 실제 이름 바꾸기로 확인한다. 이동 실패는 합성(앱이 파일을 연 상태를 흉내)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        make_bundle(self.root, "A")
        self.work = rs_.work_dir(self.root, "2026-10-25")
        make_bundle(self.work, "B")
        for name, rel in rs_.BUNDLE.items():  # 작업 공간은 묶음 이름으로 바로 둔다
            (self.work / rel).rename(self.work / name)
        self.prev = rs_.prev_dir(self.root)

    def cur(self):
        return bundle_tags(rs_.service_paths(self.root))

    def test_swap_rollback_rollback(self):
        rs_.swap(self.root, self.work, self.prev, note="apply")
        self.assertEqual((self.cur(), bundle_tags(rs_.bundle_in(self.prev))), ({"B"}, {"A"}))
        rs_.rollback(self.root, self.prev)
        self.assertEqual((self.cur(), bundle_tags(rs_.bundle_in(self.prev))), ({"A"}, {"B"}))
        rs_.rollback(self.root, self.prev)
        self.assertEqual((self.cur(), bundle_tags(rs_.bundle_in(self.prev))), ({"B"}, {"A"}))

    def test_second_swap_keeps_one_generation(self):
        rs_.swap(self.root, self.work, self.prev, note="apply 1")
        work2 = rs_.work_dir(self.root, "2026-11-01")
        make_bundle(work2, "C")
        for name, rel in rs_.BUNDLE.items():
            (work2 / rel).rename(work2 / name)
        rs_.swap(self.root, work2, self.prev, note="apply 2")
        self.assertEqual((self.cur(), bundle_tags(rs_.bundle_in(self.prev))), ({"C"}, {"B"}))
        self.assertFalse(self.prev.with_name("prev_old").exists())  # 이전 prev 는 성공 후에만 지운다

    def test_move_failure_restores(self):
        def mover(src, dst):
            if Path(src).name == "chroma":
                raise PermissionError("in use")
            Path(src).replace(dst)
        with self.assertRaises(rs_.SwapError):
            rs_.swap(self.root, self.work, self.prev, note="apply", mover=mover)
        self.assertEqual((self.cur(), bundle_tags(rs_.bundle_in(self.work))), ({"A"}, {"B"}))
        self.assertFalse(self.prev.exists())
        rs_.swap(self.root, self.work, self.prev, note="apply")  # 정상 이동이면 교체된다
        with self.assertRaises(rs_.SwapError):
            rs_.rollback(self.root, self.prev, mover=mover)
        self.assertEqual((self.cur(), bundle_tags(rs_.bundle_in(self.prev))), ({"B"}, {"A"}))


class FakeClient:
    """카드 변경 판단용 가짜 HTTP (신규 모델 카드)."""
    requests = 0

    def get_text(self, url):
        self.requests += 1
        return "# card\n\nbody\n"


class FakeOps:
    """run_apply 의 바깥 작업 (조회·작업 공간 프로세스·포트 확인)을 흉내 낸다."""
    max_llm_calls = 8

    def __init__(self, items, cat, after_hit=True, ports=()):
        self.items, self.cat, self.after_hit, self.ports = items, cat, after_hit, list(ports)
        self.calls = []

    def lookup(self):
        self.calls.append("lookup")
        return {"items": self.items, "catalog": self.cat, "manifest": {}, "client": FakeClient()}

    def eval_models(self):
        return ["o/m01"]

    def open_ports(self):
        return self.ports

    def worker(self, command, work, out, cases=None):
        self.calls.append(command)
        if command == "eval":
            hit = self.after_hit if (work / "build.json").exists() else True
            data = {"rows": [{"case_id": f"c{i}", "model_id": "o/m01", "question": "q", "rep": 0, "hit": hit}
                             for i in range(5)]}
        else:  # build: 작업 공간 파일만 바꾼다
            (work / "items.json").write_text("new items", encoding="utf-8")
            (work / "chroma" / "f.txt").write_text("chroma-new", encoding="utf-8")
            data = {"applied": [], "carried": [], "checks": [], "a_cases": [], "b_possible_cases": [],
                    "summary_usage": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                    "timings_sec": {"cards": 0.1}}
        ra.write_json(out, data)
        return data


class ApplyFlowTest(unittest.TestCase):
    """run_apply 흐름: 급변 중지, 불변 조건(교체 전 서비스 파일 해시), 앱 실행 중 교체 거부와 이어서 실행, 심각 판정.
    조회·작업 공간 프로세스는 가짜 (실제 흐름은 10절 실행에서 확인)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        make_bundle(self.root, "A")
        self.items = [item(i) for i in range(1, 5)]

    def run_apply(self, ops, allow_large=False):
        return ra.run_apply(self.root, REF, allow_large, ops, rs=RS, cfg=CFG, log=lambda *a: None)

    def test_anomaly_stops_without_workspace(self):
        """활성 4개에 신규 0·퇴출 후보 등 변화가 기준(4 × 0.2)을 넘는 합성 입력."""
        before = rs_.service_hashes(self.root)
        items = self.items + [item(i) for i in range(10, 13)]  # 10~12위: 퇴출 순위(6) 밖 → 퇴출 후보 3개
        report = self.run_apply(FakeOps(items, catalog()))
        self.assertEqual(report["result"], "stopped_anomaly")
        self.assertFalse(rs_.work_dir(self.root, REF.isoformat()).exists())
        self.assertEqual(rs_.service_hashes(self.root), before)
        self.assertTrue((rs_.refresh_dir(self.root) / f"{REF.isoformat()}.json").exists())
        report = self.run_apply(FakeOps(items, catalog(), ports=["web:8000"]), allow_large=True)
        self.assertTrue(report["anomaly"]["allow_large"])
        self.assertEqual(report["result"], "not_swapped")

    def test_refused_then_resumed(self):
        before = rs_.service_hashes(self.root)
        ops = FakeOps(self.items, catalog(), ports=["web:8000"])
        report = self.run_apply(ops)
        self.assertEqual((report["result"], report["evaluation"]["verdict"]["level"]), ("not_swapped", "normal"))
        self.assertIn("앱 실행 중", report["swap"]["reason"])
        self.assertEqual(rs_.service_hashes(self.root), before)  # 불변 조건: 교체 전까지 서비스 파일 그대로
        work = rs_.work_dir(self.root, REF.isoformat())
        self.assertTrue(work.exists())
        resumed = FakeOps(self.items, catalog())  # 앱을 끄고 같은 날짜로 다시 실행
        report = self.run_apply(resumed)
        self.assertEqual(resumed.calls, [])  # 조회·요약·평가를 다시 하지 않고 교체 단계부터
        self.assertEqual(report["result"], "swapped")
        self.assertTrue(report["invariant"]["service_files_unchanged_before_swap"])
        self.assertEqual((self.root / "data" / "items.json").read_text(encoding="utf-8"), "new items")
        self.assertFalse(work.exists())  # 교체 성공 후 작업 공간 정리
        self.assertTrue((rs_.prev_dir(self.root) / "items.json").exists())

    def test_service_change_blocks_swap(self):
        ops = FakeOps(self.items, catalog(), ports=["web:8000"])
        self.run_apply(ops)
        (self.root / "data" / "summaries.jsonl").write_text("changed", encoding="utf-8")
        report = self.run_apply(FakeOps(self.items, catalog()))
        self.assertIn("서비스 파일이 바뀜", report["swap"]["reason"])
        self.assertFalse(report["invariant"]["service_files_unchanged_before_swap"])

    def test_severe_keeps_workspace(self):
        report = self.run_apply(FakeOps(self.items, catalog(), after_hit=False))  # 5개 모두 C
        self.assertEqual(report["evaluation"]["verdict"]["level"], "severe")
        self.assertFalse(report["swap"]["swapped"])
        self.assertTrue(rs_.work_dir(self.root, REF.isoformat()).exists())
        self.assertEqual(bundle_tags(rs_.service_paths(self.root)), {"A"})


class FakeChain:
    def __init__(self):
        self.calls = 0

    def invoke(self, prompt):
        self.calls += 1
        parsed = summaries.CardSummary(summary_ko="요약", highlights=[], stage_from_card="base",
                                       languages_from_card=[], card_quality="sufficient")
        raw = SimpleNamespace(usage_metadata={"input_tokens": 100, "output_tokens": 10}, response_metadata={})
        return {"raw": raw, "parsed": parsed, "parsing_error": None}


class ModelAtomicTest(unittest.TestCase):
    """모델 단위로 전부 반영 아니면 전부 이월 (3-6). 카드·manifest·요약·색인 상태 경로를 임시 폴더로 바꾸고,
    HTTP·LLM·색인은 가짜다. 색인 실패는 합성 (실제 갱신에서는 일어나지 않았다)."""

    def setUp(self):
        from data_prep import refresh_worker
        self.w = refresh_worker
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        cards_dir = self.tmp / "cards"
        cards_dir.mkdir()
        patches = [mock.patch.object(cards, "CARDS_DIR", cards_dir),
                   mock.patch.object(cards, "MANIFEST_PATH", cards_dir / "_manifest.json"),
                   mock.patch.object(summaries, "SUMMARIES_PATH", self.tmp / "summaries.jsonl"),
                   mock.patch.object(docs_index, "STATUS_PATH", self.tmp / "index_status.json"),
                   mock.patch.object(cards, "download", lambda mid, rev: "---\nlicense: mit\n---\nnew body\n")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.old = {"model_id": "o/x", "vendor": "V", "params_b": 1.0, "input_modalities": ["text"],
                    "card_revision": "r1", "card_url": "https://huggingface.co/o/x"}
        self.new = {**self.old, "card_revision": "r2"}
        cards.body_path("o/x").write_text("old body\n", encoding="utf-8")
        cards.save_manifest({"o/x": {"model_id": "o/x", "card_revision": "r1", "status": "ok",
                                     "body_sha256": cards.sha256("old body\n")}})
        summaries.SUMMARIES_PATH.write_text('{"model_id": "o/x", "card_revision": "r1"}\n', encoding="utf-8")
        docs_index.set_status("o/x", status="done", card_revision="r1", chunks=3)

    def run_model(self, index_result):
        from data_prep import indexing
        chain = self.w.CappedChain(FakeChain(), 8)
        reindexed = []

        def fake_index(mid, item=None):
            reindexed.append(item["card_revision"])
            if item["card_revision"] == "r2":
                docs_index.set_status(mid, status="failed" if index_result == "failed" else "done",
                                      card_revision="r2", chunks=4)
                return index_result
            docs_index.set_status(mid, status="done", card_revision="r1", chunks=3)
            return "indexed"
        with mock.patch.object(indexing, "ensure_card_indexed", fake_index):
            step = ra.Timer({})
            return self.w.apply_model(self.new, self.old, chain, True, step), chain, reindexed

    def test_success(self):
        usages, chain, _ = self.run_model("indexed")
        self.assertEqual((len(usages), chain.calls), (1, 1))
        self.assertEqual(cards.body_path("o/x").read_text(encoding="utf-8"), "new body\n")
        self.assertEqual(len(summaries.SUMMARIES_PATH.read_text(encoding="utf-8").splitlines()), 2)
        self.assertEqual(cards.load_manifest()["o/x"]["card_revision"], "r2")

    def test_index_failure_reverts_all(self):
        with self.assertRaises(ra.ModelFailed) as ctx:
            self.run_model("failed")
        self.assertEqual(len(ctx.exception.usages), 1)  # 요약 비용은 이미 들었으므로 합계에 넣는다
        self.assertEqual(cards.body_path("o/x").read_text(encoding="utf-8"), "old body\n")
        self.assertEqual(cards.load_manifest()["o/x"]["card_revision"], "r1")
        self.assertEqual(len(summaries.SUMMARIES_PATH.read_text(encoding="utf-8").splitlines()), 1)
        self.assertEqual(docs_index.load_status()["o/x"]["card_revision"], "r1")  # 이전 리비전으로 다시 색인

    def test_call_limit_stops(self):
        from data_prep import indexing
        chain = self.w.CappedChain(FakeChain(), 0)
        with mock.patch.object(indexing, "ensure_card_indexed", lambda mid, item=None: "indexed"), \
                self.assertRaises(ra.ModelFailed) as ctx:
            self.w.apply_model(self.new, self.old, chain, True, ra.Timer({}))
        self.assertTrue(ctx.exception.stop)
        self.assertEqual(chain.chain.calls, 0)

    def test_failed_new_model_card_files_removed(self):
        """반영에 실패한 신규 모델: 이번 갱신이 만든 카드 파일은 지우고, 서비스에서 복사해 온 기존 카드는 남긴다 (5-1·5-2)."""
        from data_prep import indexing
        from vectorstore import store
        new_item = {**self.old, "model_id": "o/n", "card_url": "https://huggingface.co/o/n"}

        def fake_index(mid, item=None):
            docs_index.set_status(mid, status="failed", card_revision="r1")
            return "failed"
        with mock.patch.object(indexing, "ensure_card_indexed", fake_index), \
                mock.patch.object(store, "delete_where") as deleted, self.assertRaises(ra.ModelFailed):
            self.w.apply_model(new_item, None, self.w.CappedChain(FakeChain(), 8), True, ra.Timer({}))
        self.assertFalse(cards.body_path("o/n").exists())
        self.assertFalse(cards.front_matter_path("o/n").exists())
        self.assertNotIn("o/n", cards.load_manifest())
        self.assertNotIn("o/n", docs_index.load_status())
        deleted.assert_called_once()  # 작업 공간 색인에서 그 모델의 청크도 뺀다
        self.assertEqual(cards.body_path("o/x").read_text(encoding="utf-8"), "old body\n")  # 기존 카드는 남는다


class ReenrichTest(unittest.TestCase):
    """커밋 해시가 바뀐 유지 모델의 보강 다시 조회 (4). HTTP 는 가짜 응답 (data_prep.enrich.fetch).
    값이 바뀌는 경우는 합성: 2026-10-25 갱신의 LFM2.5-2.6B 는 컨텍스트 길이 등이 그대로였다."""

    ROW = {"model_id": "o/x", "architecture": "LlamaForCausalLM", "model_type": "llama", "is_moe": False,
           "num_experts": None, "experts_per_token": None, "max_position_embeddings": 8192,
           "context_source": "config.json", "context_library_version": None, "weight_precision": "BF16",
           "chat_template_has_tools": None, "license": "mit"}

    def run_reenrich(self, ctx=8192, config_ok=True, info_ok=True):
        from data_prep import enrich, refresh_worker

        def fake_fetch(url, auth=False):
            if "/api/models/" in url:
                return {"config": {"architectures": ["LlamaForCausalLM"], "model_type": "llama"},
                        "safetensors": {"parameters": {"BF16": 1}}} if info_ok else None
            return {"max_position_embeddings": ctx} if config_ok else None
        row = dict(self.ROW)
        with mock.patch.object(enrich, "fetch", fake_fetch):
            return refresh_worker.reenrich(row), row

    def test_changed(self):
        info, row = self.run_reenrich(ctx=32768)
        self.assertEqual(info["changed"], {"max_position_embeddings": {"before": 8192, "after": 32768}})
        self.assertEqual(row["max_position_embeddings"], 32768)
        self.assertEqual(ra.important_changes(self.ROW, row), {"max_position_embeddings": {"before": 8192, "after": 32768}})

    def test_same(self):
        info, row = self.run_reenrich()
        self.assertEqual((info["updated"], info["changed"], row), (True, {}, self.ROW))

    def test_failed_keeps_values(self):
        for kwargs in ({"config_ok": False}, {"info_ok": False}):
            info, row = self.run_reenrich(**kwargs)
            self.assertFalse(info["updated"])
            self.assertTrue(info["reason"])
            self.assertEqual(row, self.ROW)


if __name__ == "__main__":
    unittest.main()
