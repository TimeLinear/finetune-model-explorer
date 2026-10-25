"""데이터 갱신 (design/data-refresh.md).

사용:
  python scripts/refresh.py --dry-run [--date YYYY-MM-DD]
      1단계 시험 실행: 조회·판정만 하고 data/refresh/YYYY-MM-DD.dryrun.json 에 보고서를 쓴다. 아무 파일도 바꾸지 않는다.
  python scripts/refresh.py --apply [--date YYYY-MM-DD] [--allow-large] [--max-llm-calls 8]
      2단계 수동 반영: 판정 → 급변 검사 → 반영 대상·이월 → 작업 공간(data/refresh/work/날짜/)에서 카드·요약·색인
      → 점검·평가 → 교체 판정·교체 → data/refresh/YYYY-MM-DD.json. 교체는 앱(웹·Streamlit)이 꺼져 있을 때만 한다.
      교체 단계에서 멈췄으면 같은 날짜로 다시 실행하면 남은 단계부터 이어서 한다.
  python scripts/refresh.py --rollback
      현재 묶음과 직전 묶음(data/refresh/prev/)을 맞바꾼다. 다시 실행하면 원래대로 돌아온다. 앱이 꺼져 있을 때만.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from common import last_asked  # noqa: E402
from common.config import DATA_DIR, ROOT  # noqa: E402
from data_prep.cards import load_manifest  # noqa: E402
from data_prep.catalog_fetch import HFClient, catalog_config, fetch_catalog  # noqa: E402
from data_prep.items import load_items  # noqa: E402
from data_prep.refresh import CARD_RESULTS, DECISIONS, dry_run  # noqa: E402
from data_prep.refresh_apply import load_eval_models, read_json, run_apply  # noqa: E402
from data_prep.refresh_swap import SwapError, open_ports, prev_dir, rollback  # noqa: E402

REPORT_DIR = DATA_DIR / "refresh"

ap = argparse.ArgumentParser()
mode = ap.add_mutually_exclusive_group()
mode.add_argument("--dry-run", action="store_true", help="조회·판정만 하고 보고서를 쓴다")
mode.add_argument("--apply", action="store_true", help="판정 결과를 작업 공간에서 반영하고 평가 후 교체한다")
mode.add_argument("--rollback", action="store_true", help="현재 묶음과 직전 묶음을 맞바꾼다")
ap.add_argument("--date", help="기준 날짜 YYYY-MM-DD (기본: 오늘)")
ap.add_argument("--allow-large", action="store_true", help="급변 검사(refresh.anomaly_ratio)를 넘어가 반영한다")
ap.add_argument("--max-llm-calls", type=int, default=8, help="요약 LLM 호출 상한 (재시도 포함)")
args = ap.parse_args()
if not (args.dry_run or args.apply or args.rollback):
    ap.error("--dry-run, --apply, --rollback 중 하나를 지정한다")


def run_worker(command, work, out, cases=None):
    """작업 공간을 데이터 폴더로 바꾼 별도 프로세스에서 refresh_worker 를 실행한다 (서비스 파일은 열지 않는다)."""
    env = {**os.environ, "APP_DATA_DIR": str(work), "CHROMA_DIR": str(work / "chroma"), "PYTHONIOENCODING": "utf-8"}
    cmd = [sys.executable, "-m", "data_prep.refresh_worker", command, "--out", str(out)]
    if cases:
        cmd += ["--cases", str(cases)]
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)
    return read_json(out)


def count_service():
    """현재 서비스 묶음의 항목 수·청크 수 (되돌리기 확인용). 결과는 표준 출력으로만 받는다."""
    env = {k: v for k, v in os.environ.items() if k not in ("APP_DATA_DIR", "CHROMA_DIR")}
    out = subprocess.run([sys.executable, "-m", "data_prep.refresh_worker", "count"], cwd=ROOT,
                         env={**env, "PYTHONIOENCODING": "utf-8"}, check=True, capture_output=True, encoding="utf-8")
    return json.loads(out.stdout.strip().splitlines()[-1])


class Ops:
    max_llm_calls = args.max_llm_calls

    @staticmethod
    def lookup():
        client = HFClient()
        catalog = fetch_catalog(client)
        return {"items": load_items(), "catalog": catalog, "manifest": load_manifest(), "client": client,
                "last_asked": last_asked.load()}

    @staticmethod
    def eval_models():
        return load_eval_models(ROOT)

    @staticmethod
    def worker(command, work, out, cases=None):
        return run_worker(command, work, out, cases)

    @staticmethod
    def open_ports():
        return open_ports()


if args.rollback:
    running = open_ports()
    if running:
        sys.exit(f"앱 실행 중 ({', '.join(running)}). 앱을 끄고 다시 실행한다")
    print("되돌리기 전:", json.dumps(count_service(), ensure_ascii=False))
    try:
        rollback(ROOT, prev_dir(ROOT))
    except SwapError as e:
        sys.exit(f"되돌리기 실패: {e}")
    print("되돌리기 후:", json.dumps(count_service(), ensure_ascii=False))
    sys.exit(0)

ref_date = date.fromisoformat(args.date) if args.date else date.today()

if args.apply:
    t0 = time.perf_counter()
    report = run_apply(ROOT, ref_date, args.allow_large, Ops)
    print(f"기준 날짜 {report['date']} | 규칙 {report['rules_version']} | 결과 {report.get('result')}")
    for alert in report["alerts"]:
        print("  ! " + alert)
    print("판정:", ", ".join(f"{DECISIONS[k]} {v}" for k, v in report["decision_counts"].items()))
    a = report["anomaly"]
    print(f"급변 검사: 변화 {a['changes']}개 / 기준 {a['limit']} (활성 {a['active']} × {a['ratio']})"
          f" → {'초과' if a['exceeded'] else '통과'}{' (--allow-large)' if a['allow_large'] else ''}")
    if "build" in report:
        b = report["build"]
        u = b["summary_usage"]
        print(f"반영(요약) {len(b['applied'])}개, 이월 {len(report['carried'])}개"
              f" | 실제 비용 ${u['cost_usd']:.4f} (입력 {u['input_tokens']}, 출력 {u['output_tokens']}, 호출 {u['calls']}회)")
        for c in report["carried"]:
            print(f"  이월 {c['model_id']}: {c['reason']}" + (" [게이트 승인 필요]" if c.get("gated") else ""))
    if "evaluation" in report:
        e = report["evaluation"]
        print(f"평가: 현재 색인 {e['current_index']['hits']}/{e['current_index']['queries']}, "
              f"새 색인 {e['new_index']['hits']}/{e['new_index']['queries']} | A {e['type_a']} C {e['type_c']}"
              f" | 판정 {e['verdict']['label']}")
    swap = report.get("swap") or {}
    print(f"교체: {'예' if swap.get('swapped') else '아니오'}{' — ' + swap['reason'] if swap.get('reason') else ''}"
          f" | {time.perf_counter() - t0:.0f}초 → data/refresh/{report['date']}.json")
    sys.exit(0)

t0 = time.perf_counter()
client = HFClient()
catalog = fetch_catalog(client, catalog_config())
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
print(f"기준 날짜 {report['date']} | 규칙 {report['rules_version']} | 조회 {len(catalog['rows'])}건 | 조회 실패 조직 {list(catalog['failed_orgs']) or '없음'}")
print("판정:", ", ".join(f"{DECISIONS[k]} {v}" for k, v in report["decision_counts"].items()))
print("카드:", ", ".join(f"{CARD_RESULTS[k]} {v}" for k, v in report["card_counts"].items()))
print(f"예상 요약 비용: 대상 {cost['targets']}개, 일반 ${cost['cost_usd']:.4f}, 배치 ${cost['batch_cost_usd']:.4f}"
      f" (상한 ${cost['max_cost_usd']})")
print(f"HF 요청 {client.requests}회, 소요 {elapsed:.1f}초 → {out.relative_to(DATA_DIR.parent)}")
