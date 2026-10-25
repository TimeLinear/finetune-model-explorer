"""데이터 갱신 (design/data-refresh.md). 1단계: 조회·판정 시험 실행.

사용: python scripts/refresh.py --dry-run [--date YYYY-MM-DD]
- 최신 목록을 조회하고 진입·퇴출과 카드 변경을 판정해 data/refresh/YYYY-MM-DD.dryrun.json 에 보고서만 쓴다.
- 항목 목록·카드·manifest·요약·색인은 바꾸지 않는다. LLM 은 부르지 않는다.
- --dry-run 없이 실행하면 안내만 하고 끝난다 (실제 반영은 2단계에서 구현).
"""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import last_asked  # noqa: E402
from common.config import DATA_DIR  # noqa: E402
from data_prep.cards import load_manifest  # noqa: E402
from data_prep.catalog_fetch import HFClient, fetch_catalog  # noqa: E402
from data_prep.items import load_items  # noqa: E402
from data_prep.refresh import CARD_RESULTS, DECISIONS, dry_run  # noqa: E402

REPORT_DIR = DATA_DIR / "refresh"

ap = argparse.ArgumentParser()
ap.add_argument("--dry-run", action="store_true", help="조회·판정만 하고 보고서를 쓴다")
ap.add_argument("--date", help="기준 날짜 YYYY-MM-DD (기본: 오늘)")
args = ap.parse_args()
if not args.dry_run:
    print("실제 반영(카드 수집·요약·색인 교체·평가 판정)은 2단계에서 구현합니다. 지금은 --dry-run 만 지원합니다.")
    sys.exit(0)

ref_date = date.fromisoformat(args.date) if args.date else date.today()
t0 = time.perf_counter()
client = HFClient()
catalog = fetch_catalog(client)
catalog_requests = client.requests
report = dry_run(ref_date, load_items(), catalog, load_manifest(), client, last_asked=last_asked.load())
elapsed = time.perf_counter() - t0

report["catalog"] = {"rows": len(catalog["rows"]), "missing_orgs": catalog["missing_orgs"],
                     "failed_orgs": catalog["failed_orgs"]}
report["hf_requests"] = {"total": client.requests, "catalog": catalog_requests,
                         "cards": client.requests - catalog_requests}
report["elapsed_sec"] = round(elapsed, 1)

REPORT_DIR.mkdir(parents=True, exist_ok=True)
out = REPORT_DIR / f"{ref_date.isoformat()}.dryrun.json"
out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

cost = report["cost_estimate"]
print(f"기준 날짜 {report['date']} | 조회 {len(catalog['rows'])}건 | 조회 실패 조직 {list(catalog['failed_orgs']) or '없음'}")
print("판정:", ", ".join(f"{DECISIONS[k]} {v}" for k, v in report["decision_counts"].items()))
print("카드:", ", ".join(f"{CARD_RESULTS[k]} {v}" for k, v in report["card_counts"].items()))
print(f"예상 요약 비용: 대상 {cost['targets']}개, 일반 ${cost['cost_usd']:.4f}, 배치 ${cost['batch_cost_usd']:.4f}"
      f" (상한 ${cost['max_cost_usd']})")
print(f"HF 요청 {client.requests}회, 소요 {elapsed:.1f}초 → {out.relative_to(DATA_DIR.parent)}")
