"""데이터 갱신 판정 (design/data-refresh.md 3·4·8절). 1단계는 시험 실행(dry-run)만 한다.

시험 실행은 아무 파일도 바꾸지 않는다: 항목 목록·카드·manifest·요약·색인은 읽기만 하고, 연속 횟수도 저장하지 않는다.
카드 본문은 변경 판단에 필요한 모델만 메모리로 받아 해시만 비교하고 버린다.

목록 판정 (4절)
- 진입 순위 k = 현재 선별 규칙의 그룹별 선발 수 (data_prep.selection.group_k), 퇴출 순위 = k × refresh.exit_rank_factor 올림
- 활성 모델: 퇴출 순위 안이면 유지(연속 횟수 0). 밖이거나 조회 결과에 없으면 퇴출 후보
  - 보호 기간(refresh.protect_days 안에 질문받음)이면 유지. 신규 유예(공개 후 refresh.grace_days 미만)는 순위 기준 퇴출에만 적용
  - 연속 횟수가 refresh.exit_streak_required 에 닿으면 보관 예정
  - 조직 조회 자체가 실패한 모델은 판정 보류 (조회 실패를 삭제로 오인하지 않게)
- 보관 모델: 진입 순위 안이면 재활성, 아니면 보관 유지
- 목록에 없는 모델: 진입 순위 안이면 신규 진입

카드 변경 판단 (3절): 유지·신규·재활성 모델의 새 커밋 해시를 card_revision 과 비교 → 같으면 변경 없음.
다르면 README 본문 해시를 manifest 의 body_sha256 과 비교 (data_prep.cards 와 같은 방식) → 카드 변경 / 메타데이터만 변경.
"""
import math
from datetime import date

from common.config import setting
from data_prep.cards import raw_url, sha256, split_front_matter
from data_prep.catalog_fetch import HFRequestError, catalog_config
from data_prep.selection import annotate, group_k, rank_groups

DECISIONS = {
    "new": "신규 진입", "keep": "유지", "exit_candidate": "퇴출 후보", "archive": "보관 예정",
    "reactivate": "보관에서 재활성", "archived": "보관 유지", "hold": "판정 보류",
}
CARD_RESULTS = {
    "unchanged": "변경 없음", "metadata_only": "메타데이터만 변경", "card_changed": "카드 변경",
    "new_card": "새 카드", "fetch_failed": "조회 실패",
}
CARD_CHECK_DECISIONS = ("keep", "new", "reactivate")

# 소개 요약 비용 추정 (8절). 단가: Sonnet 5.5 기준, 배치 API 는 50% 할인
SUMMARY_PRICE = {"model": "claude-sonnet-5-5", "input_usd_per_mtok": 2.0, "output_usd_per_mtok": 10.0,
                 "batch_discount": 0.5}
# 토큰 추정: 2026-10-22 요약 실행(200건, 입력 합계 1,365,842 · 출력 83,819 토큰, 카드 평균 약 12,500자)에서
# 프롬프트·항목 정보 약 800 토큰 + 카드 약 2글자당 1토큰, 출력 약 450 토큰으로 잡았다 (data-refresh.md 8절 요약 1개 추정과 같은 규모)
SUMMARY_TOKENS = {"prompt_overhead": 800, "chars_per_token": 2.0, "output": 450}

REFRESH_KEYS = ("auto", "interval_days", "exit_rank_factor", "exit_streak_required", "protect_days", "grace_days",
                "max_cost_usd")


def refresh_settings():
    return {k: setting(f"refresh.{k}") for k in REFRESH_KEYS}


def days_since(iso_value, ref_date):
    """ISO 날짜/일시 문자열 → ref_date 까지의 일수. 값이 없으면 None."""
    if not iso_value:
        return None
    return (ref_date - date.fromisoformat(str(iso_value)[:10])).days


def group_thresholds(ranked, factor, cfg):
    out = {}
    for g, members in sorted(ranked.items()):
        k = group_k(g, len(members), cfg)
        out[g] = {"size": len(members), "k": k, "exit_rank": math.ceil(k * factor)}
    return out


def judge(items, catalog, ref_date, rs=None, last_asked=None, cfg=None):
    """목록 판정. 반환: {"groups": 그룹별 크기·k·퇴출 순위, "results": 모델별 판정 목록}"""
    cfg = cfg or catalog_config()
    rs = rs or refresh_settings()
    last_asked = last_asked or {}
    ranked = rank_groups(annotate(catalog["rows"], ref_date, cfg))
    groups = group_thresholds(ranked, rs["exit_rank_factor"], cfg)
    position = {r["id"]: (r, rank, g) for g, members in ranked.items() for rank, r in enumerate(members, 1)}
    raw_ids = {r["id"] for r in catalog["rows"]}
    failed_orgs = catalog.get("failed_orgs") or {}
    excluded = catalog.get("excluded") or {}
    current = {it["model_id"] for it in items}
    results = []

    for it in items:
        mid, status = it["model_id"], it.get("status", "active")
        res = {"model_id": mid, "status": status, "group_before": it.get("selection_group")}
        hit = position.get(mid)
        if hit:
            r, rank, g = hit
            res.update(group=g, rank=rank, **groups[g], downloads_30d_adj=r["dl30_adj"])
            if g != it.get("selection_group"):
                res["group_changed"] = True

        if status == "archived":
            if hit and res["rank"] <= res["k"]:
                res.update(decision="reactivate", reason=f"진입 순위 안 ({res['rank']}위 ≤ {res['k']}위)")
            else:
                res.update(decision="archived", reason="진입 순위 밖" if hit else "조회 결과에 없음")
            results.append(res)
            continue

        if it.get("org") in failed_orgs:
            res.update(decision="hold", reason=f"조직 조회 실패 ({failed_orgs[it['org']]})")
            results.append(res)
            continue

        rank_based = False
        if not hit:
            if mid in excluded:
                reason = f"조회 결과에 없음: {excluded[mid]}"
            elif mid in raw_ids:
                reason = "조회 결과에 없음: 중복본 제외"
            else:
                reason = "조회 결과에 없음 (삭제·비공개 전환·이름 변경 등)"
        elif res["rank"] <= res["exit_rank"]:
            note = "" if res["rank"] <= res["k"] else " (진입 순위와 퇴출 순위 사이)"
            res.update(decision="keep", reason=f"퇴출 순위 안 ({res['rank']}위 ≤ {res['exit_rank']}위){note}",
                       streak_if_applied=0)
            results.append(res)
            continue
        else:
            rank_based = True
            reason = f"퇴출 순위 밖 ({res['rank']}위 > {res['exit_rank']}위)"

        asked = days_since(last_asked.get(mid), ref_date)
        created = (hit[0]["created"] if hit else None) or it.get("created_at")
        age = days_since(created, ref_date)
        if asked is not None and asked <= rs["protect_days"]:
            res.update(decision="keep", reason=f"보호 기간: 퇴출 사유 '{reason}'가 있으나 {asked}일 전에 질문받음",
                       protected=True, last_asked=last_asked[mid], streak_if_applied=0)
        elif rank_based and age is not None and age < rs["grace_days"]:
            res.update(decision="keep", reason=f"신규 유예: 퇴출 사유 '{reason}'가 있으나 공개 {age}일째",
                       grace=True, streak_if_applied=0)
        else:
            streak = (it.get("exit_streak") or 0) + 1
            decision = "archive" if streak >= rs["exit_streak_required"] else "exit_candidate"
            res.update(decision=decision, reason=reason, streak_if_applied=streak,
                       streak_required=rs["exit_streak_required"])
        results.append(res)

    for g, members in sorted(ranked.items()):
        k = groups[g]["k"]
        for rank, r in enumerate(members[:k], 1):
            if r["id"] not in current:
                results.append({"model_id": r["id"], "status": None, "group": g, "rank": rank, **groups[g],
                                "downloads_30d_adj": r["dl30_adj"], "decision": "new",
                                "reason": f"진입 순위 안 ({rank}위 ≤ {k}위)", "vendor": r["vendor"],
                                "params_b": r["params_b"], "created": r["created"]})
    return {"groups": groups, "results": results}


def check_card(mid, new_sha, old_sha, manifest_rec, is_new, client):
    """카드 변경 판단 1건. 본문은 메모리로만 받아 길이·해시만 남긴다."""
    if not new_sha:
        return {"result": "fetch_failed", "reason": "조회 결과에 커밋 해시 없음"}
    if not is_new and new_sha == old_sha:
        return {"result": "unchanged"}
    try:
        text = client.get_text(raw_url(mid, new_sha))
    except HFRequestError as e:
        return {"result": "fetch_failed", "reason": str(e), "new_revision": new_sha}
    _, body = split_front_matter(text)
    out = {"new_revision": new_sha, "body_chars": len(body), "body_sha256": sha256(body)}
    if is_new:
        return {"result": "new_card", **out}
    old_hash = (manifest_rec or {}).get("body_sha256")
    if old_hash is None:
        return {"result": "card_changed", "reason": "manifest 에 기존 본문 해시 없음", "old_revision": old_sha, **out}
    result = "metadata_only" if out["body_sha256"] == old_hash else "card_changed"
    return {"result": result, "old_revision": old_sha, **out}


def card_checks(judged, items, catalog, manifest, client):
    by_item = {it["model_id"]: it for it in items}
    sha = {r["id"]: r.get("sha") for r in catalog["rows"]}
    checks = []
    for res in judged["results"]:
        if res["decision"] not in CARD_CHECK_DECISIONS:
            continue
        mid = res["model_id"]
        old = (by_item.get(mid) or {}).get("card_revision")
        c = check_card(mid, sha.get(mid), old, manifest.get(mid), res["decision"] == "new", client)
        checks.append({"model_id": mid, "decision": res["decision"], **c})
    return checks


def summary_tokens(body_chars, max_chars):
    t = SUMMARY_TOKENS
    return t["prompt_overhead"] + math.ceil(min(body_chars, max_chars) / t["chars_per_token"]), t["output"]


def estimate_cost(checks, max_chars, max_cost_usd):
    targets = [c for c in checks if c["result"] in ("card_changed", "new_card")]
    tokens = [summary_tokens(c["body_chars"], max_chars) for c in targets]
    tin, tout = sum(t[0] for t in tokens), sum(t[1] for t in tokens)
    p = SUMMARY_PRICE
    normal = tin * p["input_usd_per_mtok"] / 1e6 + tout * p["output_usd_per_mtok"] / 1e6
    batch = normal * (1 - p["batch_discount"])
    return {"model": p["model"], "price": p, "token_estimate": SUMMARY_TOKENS, "card_max_chars": max_chars,
            "targets": len(targets), "input_tokens": tin, "output_tokens": tout,
            "cost_usd": round(normal, 4), "batch_cost_usd": round(batch, 4),
            "max_cost_usd": max_cost_usd, "batch_within_limit": batch <= max_cost_usd}


def count_by(rows, key, labels):
    counts = {k: 0 for k in labels}
    for r in rows:
        counts[r[key]] += 1
    return counts


def dry_run(ref_date, items, catalog, manifest, client, last_asked=None, rs=None, cfg=None):
    """시험 실행 보고서 본문 (HF 요청 수·소요 시간·조회 요약은 호출한 쪽에서 더한다)."""
    rs = rs or refresh_settings()
    cfg = cfg or catalog_config()
    judged = judge(items, catalog, ref_date, rs=rs, last_asked=last_asked, cfg=cfg)
    checks = card_checks(judged, items, catalog, manifest, client)
    max_chars = setting("summary.card_max_chars")
    results = judged["results"]
    groups = {g: {**v, "exit_candidates": sum(1 for r in results if r.get("group") == g
                                              and r["decision"] in ("exit_candidate", "archive"))}
              for g, v in judged["groups"].items()}
    return {
        "date": ref_date.isoformat(),
        "dry_run": True,
        "rules_version": cfg.get("rules_version"),
        "settings": rs,
        "groups": groups,
        "decision_counts": count_by(results, "decision", DECISIONS),
        "card_counts": count_by(checks, "result", CARD_RESULTS),
        "cost_estimate": estimate_cost(checks, max_chars, rs["max_cost_usd"]),
        "decisions": {d: [r for r in results if r["decision"] == d] for d in DECISIONS},
        "card_checks": {c: [x for x in checks if x["result"] == c] for c in CARD_RESULTS},
        "labels": {"decision": DECISIONS, "card": CARD_RESULTS},
    }
