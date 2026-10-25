"""데이터 갱신 판정 (data_prep/refresh.py, design/data-refresh.md 4절) — 입력은 모두 합성이다.

- 목록 판정: 신규 진입, 진입~퇴출 순위 사이 유지(연속 횟수 0), 퇴출 순위 밖 1회/2회, 보호 기간, 신규 유예,
  조회 안 됨(제외 사유 포함), 조직 조회 실패(판정 보류), 보관 후 재진입·보관 유지
- 카드 변경 판단: HTTP 는 가짜 클라이언트 (변경 없음은 요청 없이, 메타데이터만·카드 변경·새 카드·조회 실패)
- Hugging Face 요청: 재시도·재시도하지 않는 상태 코드·요청 수
- 예상 요약 비용: 카드 길이 상한과 일반·배치 단가
"""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_prep.cards import sha256  # noqa: E402
from data_prep.catalog_fetch import HFClient, HFRequestError  # noqa: E402
from data_prep.refresh import check_card, estimate_cost, judge  # noqa: E402

REF = date(2026, 10, 25)
CFG = {  # 그룹 하나(general), 21개 → k = round(21 × 0.2) = 4, 퇴출 순위 = ceil(4 × 1.5) = 6
    "orgs": {"o": {"vendor": "V", "country": "US"}},
    "duplicate_pattern": "(?!x)x", "duplicate_exempt_orgs": [], "featured_regions": {},
    "general_pct": 0.2, "special_pct": 0.3, "special_min": 2, "category_rules": [],
}
RS = {"exit_rank_factor": 1.5, "exit_streak_required": 2, "protect_days": 30, "grace_days": 30, "max_cost_usd": 1.0}


def row(n, downloads, created="2024-01-01"):
    return {"id": f"o/m{n:02d}", "org": "o", "vendor": "V", "params_b": 7.0, "pipeline": "text-generation",
            "license": None, "languages": None, "gated": False, "downloads": downloads, "tags": [], "created": created,
            "sha": f"sha{n}"}


def item(n, **extra):
    return {"model_id": f"o/m{n:02d}", "org": "o", "selection_group": "general", "status": "active",
            "created_at": "2024-01-01", **extra}


class JudgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows = [row(n, 3000 - 100 * n) for n in range(1, 21)]  # m01 이 1위 … m20 이 20위
        fresh = (REF - timedelta(days=10)).isoformat()
        rows.append(row(21, 10, created=fresh))  # 공개 10일째: 환산 30, 21위
        items = [
            item(2, status="archived"),              # 2위 → 재활성
            item(3),                                 # 3위 → 유지
            item(5),                                 # 5위 (k=4 < 5 ≤ 6) → 유지, 연속 횟수 0
            item(7),                                 # 7위, 처음 → 퇴출 후보 1회
            item(8, exit_streak=1),                  # 8위, 두 번째 → 보관 예정
            item(9),                                 # 9위지만 최근 질문 → 보호 기간
            item(21),                                # 21위지만 공개 10일째 → 신규 유예
            item(11, status="archived"),             # 11위 보관 → 보관 유지
            item(30),                                # 조회 결과에 없음
            item(31),                                # 크기 범위 밖으로 제외
            {**item(40), "org": "down"},             # 조직 조회 실패 → 판정 보류
        ]
        catalog = {"rows": rows, "excluded": {"o/m31": "크기 범위 밖"}, "failed_orgs": {"down": "HTTP 500"}}
        asked = {"o/m09": (REF - timedelta(days=5)).isoformat() + "T10:00:00+09:00"}
        cls.out = judge(items, catalog, REF, rs=RS, last_asked=asked, cfg=CFG)
        cls.by_id = {r["model_id"]: r for r in cls.out["results"]}

    def decision(self, n):
        return self.by_id[f"o/m{n:02d}"]["decision"]

    def test_thresholds(self):
        self.assertEqual(self.out["groups"], {"general": {"size": 21, "k": 4, "exit_rank": 6}})

    def test_new_entries(self):
        new = sorted(r["model_id"] for r in self.out["results"] if r["decision"] == "new")
        self.assertEqual(new, ["o/m01", "o/m04"])  # m02 는 보관 중이라 재활성, m03 은 이미 목록에 있음

    def test_keep_between_entry_and_exit(self):
        self.assertEqual(self.decision(3), "keep")
        r = self.by_id["o/m05"]
        self.assertEqual((r["decision"], r["streak_if_applied"]), ("keep", 0))
        self.assertIn("사이", r["reason"])

    def test_exit_streak(self):
        r7, r8 = self.by_id["o/m07"], self.by_id["o/m08"]
        self.assertEqual((r7["decision"], r7["streak_if_applied"]), ("exit_candidate", 1))
        self.assertEqual((r8["decision"], r8["streak_if_applied"]), ("archive", 2))
        self.assertIn("7위 > 6위", r7["reason"])

    def test_protect_and_grace(self):
        self.assertEqual(self.decision(9), "keep")
        self.assertTrue(self.by_id["o/m09"]["protected"])
        self.assertEqual(self.decision(21), "keep")
        self.assertTrue(self.by_id["o/m21"]["grace"])

    def test_not_found(self):
        self.assertEqual(self.decision(30), "exit_candidate")
        self.assertIn("조회 결과에 없음", self.by_id["o/m30"]["reason"])
        self.assertEqual(self.by_id["o/m31"]["reason"], "조회 결과에 없음: 크기 범위 밖")
        self.assertEqual(self.decision(40), "hold")

    def test_archived(self):
        self.assertEqual(self.decision(2), "reactivate")
        self.assertEqual(self.decision(11), "archived")


class FakeClient:
    def __init__(self, texts):
        self.texts, self.urls = texts, []

    def get_text(self, url):
        self.urls.append(url)
        value = self.texts[url.split("/resolve/")[0].rsplit("/", 1)[-1]]
        if isinstance(value, Exception):
            raise value
        return value


class CardCheckTest(unittest.TestCase):
    BODY = "# Model\n\nbody text\n"

    def test_cases(self):
        old = {"body_sha256": sha256(self.BODY)}
        client = FakeClient({"same": "---\nlicense: mit\n---\n" + self.BODY, "diff": "# Model\n\nnew text\n",
                             "fresh": self.BODY, "gone": HFRequestError(404)})
        self.assertEqual(check_card("o/x", "r1", "r1", old, False, client)["result"], "unchanged")
        self.assertEqual(client.urls, [])  # 커밋 해시가 같으면 받지 않는다
        self.assertEqual(check_card("o/same", "r2", "r1", old, False, client)["result"], "metadata_only")
        changed = check_card("o/diff", "r2", "r1", old, False, client)
        self.assertEqual((changed["result"], changed["body_chars"]), ("card_changed", len("# Model\n\nnew text\n")))
        self.assertEqual(check_card("o/fresh", "r1", None, None, True, client)["result"], "new_card")
        failed = check_card("o/gone", "r2", "r1", old, False, client)
        self.assertEqual((failed["result"], failed["reason"]), ("fetch_failed", "HTTP 404"))
        self.assertEqual(check_card("o/x", None, "r1", old, False, client)["result"], "fetch_failed")
        self.assertIn("https://huggingface.co/o/same/resolve/r2/README.md", client.urls)


class FakeResponse:
    def __init__(self, status):
        self.status_code, self.headers, self.content = status, {}, b"ok"


class FakeSession:
    def __init__(self, statuses):
        self.statuses = list(statuses)

    def get(self, url, headers=None, timeout=None):
        return FakeResponse(self.statuses.pop(0))


class HFClientTest(unittest.TestCase):
    def test_retry_then_ok(self):
        client = HFClient(session=FakeSession([500, 200]), sleep=lambda s: None, interval=0, max_retries=3)
        self.assertEqual(client.get_text("u"), "ok")
        self.assertEqual(client.requests, 2)

    def test_no_retry_on_404(self):
        client = HFClient(session=FakeSession([404, 200]), sleep=lambda s: None, interval=0, max_retries=3)
        with self.assertRaises(HFRequestError):
            client.get("u")
        self.assertEqual(client.requests, 1)


class CostTest(unittest.TestCase):
    def test_estimate(self):
        checks = [{"result": "card_changed", "body_chars": 30000}, {"result": "new_card", "body_chars": 2000},
                  {"result": "metadata_only", "body_chars": 5000}, {"result": "unchanged"}]
        cost = estimate_cost(checks, max_chars=24000, max_cost_usd=1.0)
        # (800 + 24000/2) + (800 + 2000/2) = 14600 입력, 450 × 2 = 900 출력
        self.assertEqual((cost["targets"], cost["input_tokens"], cost["output_tokens"]), (2, 14600, 900))
        self.assertAlmostEqual(cost["cost_usd"], 14600 * 2 / 1e6 + 900 * 10 / 1e6, places=4)
        self.assertAlmostEqual(cost["batch_cost_usd"], cost["cost_usd"] / 2, places=4)
        self.assertTrue(cost["batch_within_limit"])


if __name__ == "__main__":
    unittest.main()
