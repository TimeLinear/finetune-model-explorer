"""데이터 갱신 2단계: 수동 반영 (design/data-refresh.md 5·6·8·9절).

순서 (run_apply): 판정 → 급변 검사 → 반영 대상·이월 결정 → 작업 공간 → 점검·평가 → 교체 판정·교체 → 보고서
- 판정은 1단계 코드(data_prep.refresh.judge·card_checks)를 그대로 쓴다.
- 서비스가 읽는 파일(목록·카드·manifest·요약·색인)은 교체 전까지 바꾸지 않는다. 작업 공간에서 만드는 일은
  APP_DATA_DIR 을 작업 공간으로 바꾼 별도 프로세스(data_prep/refresh_worker.py)가 기존 함수로 한다.
- 단계마다 작업 공간의 state.json 에 진행 상태를 남긴다. 교체 단계에서 멈추면(앱 실행 중 등) 같은 날짜로 다시 실행할 때
  남은 단계부터 이어서 한다 (요약을 다시 부르지 않는다).

항목 필드 (1-3)
- status: active / archived. 보관 예정이면 archived, 재활성이면 active
- first_seen: 목록에 처음 들어온 날짜. 기존 모델은 그대로, 신규는 반영 날짜
- last_qualified: 마지막으로 진입 순위(k) 안에 든 날짜. 진입 순위 안의 유지·재활성·신규만 반영 날짜로 바꾼다
- snapshot_date: 조회 필드(다운로드 수·순위 등)를 마지막으로 받은 날짜. 조회 결과에 있는 모델만 바꾼다
- exit_streak: 퇴출 후보 연속 횟수. 판정 결과(streak_if_applied)를 저장하고, 퇴출 순위 안이면 0
- 판정 보류 모델은 아무것도 바꾸지 않는다.
"""
import json
import math
import time
from collections import Counter

from common.config import setting
from data_prep.refresh import (CARD_RESULTS, DECISIONS, SUMMARY_PRICE, card_checks, count_by, judge, refresh_settings,
                                summary_tokens)
from data_prep.refresh_swap import (BUNDLE, SwapError, create_workspace, prev_dir, refresh_dir, service_hashes,
                                    swap, work_dir)
from data_prep.selection import annotate, item_record, rank_groups

CHANGE_DECISIONS = ("new", "exit_candidate", "archive", "reactivate")  # 급변 검사에 세는 판정 (9절)
SUMMARY_RESULTS = ("card_changed", "new_card")
SUMMARY_PRIORITY = {"keep": 0, "reactivate": 1, "new": 2}  # 9절 다음 갱신으로 넘기는 순서
LOOKUP_FIELDS = ("selection_group", "category", "license", "gated", "downloads_30d", "downloads_30d_adj", "group_rank")
GATED_ERRORS = ("HTTP 401", "HTTP 403")

# 교체 판정 (6절 표). 운용하면서 바꿀 값이라도 설정에 두지 않고 설계 문서 표와 같은 상수로 둔다
# (tests/test_refresh_apply.py 가 표의 숫자와 대조한다).
MINOR_MAX_C = 3            # 경미: C 유형 3건 이하
SEVERE_MIN_C = 4           # 심각: C 유형 4건 이상
MODEL_SEVERE_FRACTION = 0.5  # 심각: 한 모델의 사례가 절반 넘게 나빠짐
# 점검 (5절)
CHUNK_DROP_RATIO = 0.5     # 청크 수가 절반 이하로 줄면
CHUNK_GROW_RATIO = 2.0     # 두 배 이상 늘면
# 평가 세트 수명 (6절: 검토 필요·폐기 후보가 20% 초과, 9절: 평가 세트 모델 6개 중 절반 이상 보관·카드 변경)
EVAL_SET_STALE_FRACTION = 0.2
EVAL_SET_EROSION_FRACTION = 0.5

STAGES = ("workspace", "eval_before", "built", "evaluated", "swapped")
VERDICT_LABELS = {"normal": "정상", "minor": "경미", "severe": "심각"}


def apply_settings():
    return {**refresh_settings(), "anomaly_ratio": setting("refresh.anomaly_ratio"),
            "batch_threshold": setting("refresh.batch_threshold")}


# ---------- 급변 검사 (9절) ----------

def anomaly_check(results, items, ratio, allow_large=False):
    active = sum(1 for it in items if it.get("status", "active") == "active")
    by = {d: sum(1 for r in results if r["decision"] == d) for d in CHANGE_DECISIONS}
    changes = sum(by.values())
    limit = active * ratio
    exceeded = changes > limit
    return {"changes": changes, "by_decision": by, "active": active, "ratio": ratio, "limit": round(limit, 2),
            "exceeded": exceeded, "allow_large": allow_large, "stop": exceeded and not allow_large}


def eval_set_erosion(results, checks, eval_models):
    """평가 세트 모델 중 보관 예정이거나 카드가 바뀐 모델 (9절 "평가 세트 침식")."""
    archived = {r["model_id"] for r in results if r["decision"] == "archive"}
    changed = {c["model_id"] for c in checks if c["result"] == "card_changed"}
    hit = sorted((archived | changed) & set(eval_models))
    return {"eval_models": sorted(eval_models), "affected": hit,
            "review": bool(eval_models) and len(hit) >= len(eval_models) * EVAL_SET_EROSION_FRACTION}


# ---------- 반영 대상과 이월 (8·9절) ----------

def usage_cost(input_tokens, output_tokens, price=SUMMARY_PRICE):
    """일반 API 단가 기준 (갱신 요약은 일반 API, 8절)."""
    return input_tokens * price["input_usd_per_mtok"] / 1e6 + output_tokens * price["output_usd_per_mtok"] / 1e6


def is_gated(reason):
    return any(code in (reason or "") for code in GATED_ERRORS)


def plan_targets(judged, checks, max_chars, max_cost, batch_threshold):
    """카드 변경 판단 결과 → 요약 대상(우선순위 순, 예상 비용이 상한 안), 메타데이터만 바뀐 모델, 이월 모델."""
    res_by = {r["model_id"]: r for r in judged["results"]}
    summary, carried, metadata_only = [], [], []
    for c in checks:
        mid, d = c["model_id"], c["decision"]
        if c["result"] == "fetch_failed":
            carried.append({"model_id": mid, "decision": d, "reason": f"카드 조회 실패: {c.get('reason')}",
                            "gated": is_gated(c.get("reason"))})
        elif c["result"] == "metadata_only":
            metadata_only.append({"model_id": mid, "decision": d, "new_revision": c["new_revision"]})
        elif c["result"] in SUMMARY_RESULTS:
            tin, tout = summary_tokens(c["body_chars"], max_chars)
            summary.append({"model_id": mid, "decision": d, "card_result": c["result"],
                            "priority": SUMMARY_PRIORITY[d], "rank": res_by[mid].get("rank"),
                            "group": res_by[mid].get("group"), "new_revision": c["new_revision"],
                            "est_input": tin, "est_output": tout, "est_cost": round(usage_cost(tin, tout), 4)})
    summary.sort(key=lambda t: (t["priority"], t["rank"] if t["decision"] == "new" else 0, t["model_id"]))
    targets, total, over = [], 0.0, False
    for t in summary:
        if over or total + t["est_cost"] > max_cost:
            over = True
            carried.append({**t, "reason": f"예상 비용 상한 초과 (누적 ${total + t['est_cost']:.4f} > ${max_cost})"})
            continue
        total += t["est_cost"]
        targets.append(t)
    warnings = []
    if len(summary) > batch_threshold:
        warnings.append(f"배치 API 전환 검토: 요약 대상 {len(summary)}개 > refresh.batch_threshold {batch_threshold}")
    return {"targets": targets, "metadata_only": metadata_only, "carried": carried, "summary_candidates": len(summary),
            "est_cost": round(total, 4), "warnings": warnings}


class ModelFailed(RuntimeError):
    """모델 1개의 반영 실패 → 그 모델 전체를 이월한다. stop=True 면 남은 모델도 이월한다 (LLM 호출 상한 등)."""

    def __init__(self, reason, usages=(), gated=False, stop=False):
        super().__init__(reason)
        self.reason, self.usages, self.gated, self.stop = reason, list(usages), gated, stop


def add_usages(spent, usages):
    for u in usages:
        spent["calls"] += 1
        spent["input_tokens"] += u.get("input_tokens", 0)
        spent["output_tokens"] += u.get("output_tokens", 0)
    spent["cost_usd"] = round(usage_cost(spent["input_tokens"], spent["output_tokens"]), 6)


def run_targets(targets, process, max_cost):
    """요약 대상을 우선순위대로 반영한다. 실제 토큰으로 비용을 누적해, 다음 모델의 예상 비용까지 더해 상한을 넘으면
    그 모델부터 남은 모델을 모두 이월한다. process(target) → 호출별 usage 목록 (실패하면 ModelFailed).
    반환: (반영 목록, 이월 목록, 실제 사용량 합계)"""
    spent = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    applied, carried, stop = [], [], None
    for t in targets:
        if stop is None and spent["cost_usd"] + t["est_cost"] > max_cost:
            stop = f"실제 비용 상한 초과 (사용 ${spent['cost_usd']:.4f} + 예상 ${t['est_cost']:.4f} > ${max_cost})"
        if stop:
            carried.append({**t, "reason": stop})
            continue
        try:
            usages = process(t)
        except ModelFailed as e:
            add_usages(spent, e.usages)
            carried.append({**t, "reason": e.reason, "gated": e.gated})
            if e.stop:
                stop = f"앞 모델에서 중단: {e.reason}"
            continue
        add_usages(spent, usages)
        applied.append({**t, "usage": {"calls": len(usages),
                                       "input_tokens": sum(u.get("input_tokens", 0) for u in usages),
                                       "output_tokens": sum(u.get("output_tokens", 0) for u in usages)}})
    return applied, carried, spent


# ---------- 새 목록 ----------

def sort_items(items):
    return sorted(items, key=lambda it: (it["selection_group"], it["vendor"], it["model_id"]))


def build_items(items, judged, catalog, checks, ref_date, cfg):
    """판정 결과를 반영한 새 목록(요약 대상이 모두 성공한다고 가정)과 모델별 대체 행(반영 실패·이월 시 쓸 행, 신규는 None)."""
    day = ref_date.isoformat()
    ranked = rank_groups(annotate(catalog["rows"], ref_date, cfg))
    rec = {r["id"]: item_record(r, rank, len(members), ref_date)
           for members in ranked.values() for rank, r in enumerate(members, 1)}
    res_by = {r["model_id"]: r for r in judged["results"]}
    chk_by = {c["model_id"]: c for c in checks}
    out, fallback = [], {}
    for it in items:
        mid = it["model_id"]
        res = res_by[mid]
        d = res["decision"]
        row = {**it, "exit_streak": it.get("exit_streak", 0)}
        if d == "hold":
            out.append(row)
            continue
        if mid in rec:
            row.update({k: rec[mid][k] for k in LOOKUP_FIELDS}, snapshot_date=day)
        if "streak_if_applied" in res:
            row["exit_streak"] = res["streak_if_applied"]
        if d == "keep" and res.get("rank") is not None and res["rank"] <= res["k"]:
            row["last_qualified"] = day
        if d == "archive":
            row["status"] = "archived"
        fallback[mid] = dict(row)  # 카드·요약·색인을 반영하지 못하면: 재활성 안 함, card_revision 그대로
        if d == "reactivate":
            row.update(status="active", exit_streak=0, last_qualified=day)
        c = chk_by.get(mid)
        if c and c["result"] in ("metadata_only", "card_changed"):
            row["card_revision"] = c["new_revision"]
        out.append(row)
    for res in judged["results"]:
        if res["decision"] != "new":
            continue
        mid = res["model_id"]
        c = chk_by.get(mid) or {}
        out.append({**rec[mid], "card_revision": c.get("new_revision"), "card_url": f"https://huggingface.co/{mid}",
                    "exit_streak": 0})
        fallback[mid] = None
    return sort_items(out), fallback


def apply_fallback(items, fallback, model_ids):
    """이월한 모델의 행을 대체 행으로 바꾼다 (신규는 목록에서 뺀다)."""
    model_ids = set(model_ids)
    out = []
    for it in items:
        mid = it["model_id"]
        if mid in model_ids:
            if fallback.get(mid) is not None:
                out.append(fallback[mid])
            continue
        out.append(it)
    return sort_items(out)


def order_keys(row, keys):
    """기존 목록과 같은 필드 순서 (없는 필드는 None, 기존에 없던 필드는 뒤에)."""
    return {**{k: row.get(k) for k in keys}, **{k: v for k, v in row.items() if k not in keys}}


# ---------- 점검 (5절) ----------

IMPORTANT_FIELDS = ("license", "gated", "max_position_embeddings")


def important_changes(old_item, new_item):
    """라이선스·승인 필요 여부·컨텍스트 길이 변경 (컨텍스트 길이는 보강을 다시 조회한 모델에서만 바뀐다)."""
    return {f: {"before": old_item.get(f), "after": new_item.get(f)}
            for f in IMPORTANT_FIELDS if old_item.get(f) != new_item.get(f)}


def chunk_check(old_status, new_status):
    """색인 상태(index_status.json 의 모델 기록) 전후 → 청크 수 급변·머리말 누락."""
    old_n, new_n = (old_status or {}).get("chunks"), (new_status or {}).get("chunks")
    old_f, new_f = (old_status or {}).get("front_matter_chunks", 0), (new_status or {}).get("front_matter_chunks", 0)
    out = {"chunks_before": old_n, "chunks_after": new_n,
           "front_matter_before": old_f, "front_matter_after": new_f, "flags": []}
    if old_n and new_n is not None:
        if new_n <= old_n * CHUNK_DROP_RATIO:
            out["flags"].append("청크 수 절반 이하")
        if new_n >= old_n * CHUNK_GROW_RATIO:
            out["flags"].append("청크 수 두 배 이상")
    if old_f and not new_f:
        out["flags"].append("머리말 청크 누락")
    return out


# ---------- 평가 세트 정답 다시 연결 (5절) ----------

def norm_space(text):
    return " ".join(text.split())


def relink_case(case, chunks, b_possible=False):
    """카드가 바뀐 모델의 사례: 저장된 근거 문장이 들어 있는 새 청크로 정답을 다시 만든다.
    chunks: [{id, text, metadata}] (그 모델 카드의 새 청크). 근거 문장을 하나도 못 찾으면 유형 A (사례는 그대로 둔다).
    반환: (사례, {case_id, status: relinked|unchanged|A, missing, b_possible})"""
    ordered = sorted(chunks, key=lambda c: c["metadata"].get("chunk_index", 0))
    found, missing = [], []
    for ev in case["evidence"]:
        sentence = norm_space(ev["sentence"])
        cid = next((c["id"] for c in ordered if sentence in norm_space(c["text"])), None)
        if cid:
            found.append({**ev, "chunk_id": cid})
        else:
            missing.append(ev["sentence"])
    info = {"case_id": case["case_id"], "model_id": case["model_id"], "missing": missing, "b_possible": b_possible}
    if not found:
        return case, {**info, "status": "A"}
    gold = list(dict.fromkeys(e["chunk_id"] for e in found))
    new_case = {**case, "gold_chunk_ids": gold, "evidence": found}
    status = "unchanged" if new_case == case else "relinked"
    return new_case, {**info, "status": status, "gold_before": case["gold_chunk_ids"], "gold_after": gold}


# ---------- 평가와 교체 판정 (6절) ----------

def row_key(r):
    return r["case_id"], r["question"], r.get("rep", 0)


def classify_eval(before_rows, after_rows, a_cases):
    """이전에는 맞췄는데 지금은 놓친 질의 → A 로 빠진 사례가 아니면 C."""
    before = {row_key(r): r["hit"] for r in before_rows}
    lost = [r for r in after_rows if before.get(row_key(r)) and not r["hit"]]
    return {"lost": lost, "a": [r for r in lost if r["case_id"] in a_cases],
            "c": [r for r in lost if r["case_id"] not in a_cases]}


def verdict(c_rows, after_rows, a_cases):
    """정상(C 0건) / 경미(1~3건) / 심각(4건 이상, 또는 한 모델의 질의 절반 초과가 C). 단위는 평가 질의(표현) 1개."""
    total = Counter(r["model_id"] for r in after_rows if r["case_id"] not in a_cases)
    per_model = Counter(r["model_id"] for r in c_rows)
    worst = {m: {"c": n, "queries": total[m]} for m, n in per_model.items() if n > total[m] * MODEL_SEVERE_FRACTION}
    n = len(c_rows)
    if n >= SEVERE_MIN_C or worst:
        level = "severe"
    elif n:
        level = "minor"
    else:
        level = "normal"
    return {"level": level, "label": VERDICT_LABELS[level], "c_count": n, "models_over_half": worst,
            "swap": level != "severe"}


def hits(rows):
    return {"queries": len(rows), "hits": sum(r["hit"] for r in rows),
            "hit_rate": round(sum(r["hit"] for r in rows) / len(rows), 4) if rows else None}


# ---------- 실행 ----------

def read_json(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


class Timer:
    def __init__(self, store):
        self.store = store

    def __call__(self, name):
        timer = self

        class _Step:
            def __enter__(self):
                self.t0 = time.perf_counter()

            def __exit__(self, *exc):
                timer.store[name] = round(timer.store.get(name, 0) + time.perf_counter() - self.t0, 1)
        return _Step()


def load_eval_models(root):
    path = root / BUNDLE["cases.jsonl"]
    return sorted({json.loads(line)["model_id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()})


def prepare(root, ref_date, allow_large, ops, rs, cfg, log):
    """판정 → 급변 검사 → 대상 결정 → 작업 공간. 급변으로 멈추면 None 과 보고서."""
    day = ref_date.isoformat()
    timings = {}
    step = Timer(timings)
    with step("lookup"):
        looked = ops.lookup()
        items, catalog, client = looked["items"], looked["catalog"], looked["client"]
        catalog_requests = client.requests
        judged = judge(items, catalog, ref_date, rs=rs, last_asked=looked.get("last_asked"), cfg=cfg)
        checks = card_checks(judged, items, catalog, looked["manifest"], client)
    results = judged["results"]
    report = {
        "date": day, "dry_run": False, "rules_version": cfg.get("rules_version"), "settings": rs,
        "alerts": [], "groups": judged["groups"],
        "decision_counts": count_by(results, "decision", DECISIONS),
        "card_counts": count_by(checks, "result", CARD_RESULTS),
        "catalog": {"rows": len(catalog["rows"]), "missing_orgs": catalog.get("missing_orgs"),
                    "failed_orgs": catalog.get("failed_orgs")},
        "hf_requests": {"catalog": catalog_requests, "card_checks": client.requests - catalog_requests,
                        "enrich": 0, "card_fetch": 0, "total": client.requests},  # 보강·카드 수집은 작업 공간 단계에서 더한다
        "decisions": {d: [r for r in results if r["decision"] == d] for d in DECISIONS},
        "card_checks": {c: [x for x in checks if x["result"] == c] for c in CARD_RESULTS},
        "labels": {"decision": DECISIONS, "card": CARD_RESULTS, "verdict": VERDICT_LABELS},
        "timings_sec": timings,
    }

    anomaly = anomaly_check(results, items, rs["anomaly_ratio"], allow_large)
    report["anomaly"] = anomaly
    if anomaly["exceeded"]:
        if anomaly["stop"]:
            report["alerts"].append(f"급변: 변화 {anomaly['changes']}개 > 활성 {anomaly['active']} × {anomaly['ratio']}."
                                    " 반영하지 않음 (사람이 확인한 뒤 --allow-large 로 반영)")
            report["result"] = "stopped_anomaly"
            return None, report
        report["alerts"].append(f"급변 기준 초과({anomaly['changes']}개 > {anomaly['limit']})지만 --allow-large 로 반영")

    erosion = eval_set_erosion(results, checks, ops.eval_models())
    report["eval_set_erosion"] = erosion
    if erosion["review"]:
        report["alerts"].insert(0, f"평가 세트 재작성 검토: 평가 세트 모델 {len(erosion['eval_models'])}개 중 "
                                   f"{len(erosion['affected'])}개가 보관 예정이거나 카드 변경 ({', '.join(erosion['affected'])})")

    plan = plan_targets(judged, checks, setting("summary.card_max_chars"), rs["max_cost_usd"], rs["batch_threshold"])
    report["alerts"] += plan["warnings"]
    new_items, fallback = build_items(items, judged, catalog, checks, ref_date, cfg)
    new_items = apply_fallback(new_items, fallback, [c["model_id"] for c in plan["carried"]])
    keys = list(items[0].keys())
    new_items = [order_keys(it, keys) for it in new_items]
    report["plan"] = {k: plan[k] for k in ("targets", "metadata_only", "summary_candidates", "est_cost")}
    report["carried"] = plan["carried"]

    work = work_dir(root, day)
    log(f"작업 공간 만들기: {work.relative_to(root)}")
    with step("workspace"):
        hashes = service_hashes(root)
        create_workspace(root, work)
    enrich = sorted({r["model_id"] for r in results if r["decision"] in ("new", "reactivate")}
                    - {c["model_id"] for c in plan["carried"]})
    # 커밋 해시가 바뀐 유지 모델(카드 변경·메타데이터만 변경)은 config.json 도 바뀌었을 수 있어 보강을 다시 조회한다
    reenrich = sorted({t["model_id"] for t in plan["targets"] if t["decision"] == "keep"}
                      | {m["model_id"] for m in plan["metadata_only"] if m["decision"] == "keep"})
    write_json(work / "plan.json", {
        "date": day, "items": new_items, "item_keys": keys, "fallback": fallback,
        "targets": plan["targets"], "metadata_only": plan["metadata_only"], "enrich": enrich,
        "reenrich": reenrich, "old_items": {it["model_id"]: it for it in items},
        "eval_models": erosion["eval_models"], "max_cost_usd": rs["max_cost_usd"],
        "max_llm_calls": ops.max_llm_calls,
    })
    return {"stage": "workspace", "service_hashes": hashes, "report": report}, report


def finish_eval(work, report):
    before = read_json(work / "eval_before.json")["rows"]
    after = read_json(work / "eval_after.json")["rows"]
    a_cases = set(report["build"]["a_cases"])
    cls = classify_eval(before, after, a_cases)
    v = verdict(cls["c"], after, a_cases)
    n_cases = len({r["case_id"] for r in after})
    stale = len(a_cases | set(report["build"]["b_possible_cases"]))
    report["evaluation"] = {
        "current_index": hits(before), "new_index": hits(after),
        "lost": len(cls["lost"]), "type_a": len(cls["a"]), "type_c": len(cls["c"]),
        "type_a_cases": sorted(a_cases), "b_possible_cases": report["build"]["b_possible_cases"],
        "c_rows": [{k: r[k] for k in ("case_id", "model_id", "question", "rep")} for r in cls["c"]],
        "verdict": v,
    }
    if v["level"] == "minor":
        report["evaluation"]["needs_review"] = report["evaluation"]["c_rows"]
    if n_cases and stale > n_cases * EVAL_SET_STALE_FRACTION:
        report["alerts"].append(f"평가 세트 재작성 시점: 검토 필요·폐기 후보 {stale}개 > 사례 {n_cases}개의 20%")
    return v


def do_swap(root, work, state, ops, log):
    report = state["report"]
    timings = report.setdefault("timings_sec", {})
    t0 = time.perf_counter()
    running = ops.open_ports()
    if running:
        report["swap"] = {"swapped": False, "reason": f"앱 실행 중 ({', '.join(running)}). 앱을 끄고 같은 날짜로 다시 실행"}
        return False
    now = service_hashes(root)
    same = now == state["service_hashes"]
    report["invariant"] = {"service_files_unchanged_before_swap": same,
                           "hashes": {n: (h or {}).get("sha256") for n, h in now.items()}}
    if not same:
        changed = [n for n in now if now[n] != state["service_hashes"].get(n)]
        report["swap"] = {"swapped": False, "reason": f"작업 공간을 만든 뒤 서비스 파일이 바뀜: {changed}. 교체하지 않음"}
        return False
    try:
        swap(root, work, prev_dir(root), note=f"apply {report['date']}")
    except SwapError as e:
        report["swap"] = {"swapped": False, "reason": str(e)}
        return False
    timings["swap"] = round(time.perf_counter() - t0, 1)
    report["swap"] = {"swapped": True, "prev": str(prev_dir(root).relative_to(root).as_posix())}
    log("교체 완료")
    return True


def run_apply(root, ref_date, allow_large, ops, rs=None, cfg=None, log=print):
    """수동 반영. ops: lookup() / eval_models() / worker(command, work, **kwargs) / open_ports() / max_llm_calls.
    반환: 보고서 (data/refresh/YYYY-MM-DD.json 에도 쓴다)."""
    import shutil

    from data_prep.catalog_fetch import catalog_config
    day = ref_date.isoformat()
    work = work_dir(root, day)
    report_path = refresh_dir(root) / f"{day}.json"
    state_path = work / "state.json"
    state = read_json(state_path)
    if state is None:
        state, report = prepare(root, ref_date, allow_large, ops, rs or apply_settings(), cfg or catalog_config(), log)
        if state is None:
            write_json(report_path, report)
            return report
        write_json(state_path, state)
    else:
        log(f"작업 공간이 있어 '{state['stage']}' 다음 단계부터 이어서 한다: {work.relative_to(root)}")
        state["report"].setdefault("resumed", []).append(state["stage"])
    report = state["report"]
    timings = report.setdefault("timings_sec", {})

    def advance(stage):
        state["stage"] = stage
        write_json(state_path, state)

    if state["stage"] == "workspace":
        t0 = time.perf_counter()
        ops.worker("eval", work, cases=work / "cases.jsonl", out=work / "eval_before.json")
        timings["eval"] = round(timings.get("eval", 0) + time.perf_counter() - t0, 1)
        advance("eval_before")
    if state["stage"] == "eval_before":
        build = ops.worker("build", work, out=work / "build.json")
        report["build"] = build
        for k, v in build.get("timings_sec", {}).items():
            timings[k] = v
        report["carried"] = report.get("carried", []) + build["carried"]
        hf = report["hf_requests"]
        hf.update(build.get("hf_requests", {}))
        hf["total"] = sum(hf.get(k, 0) for k in ("catalog", "card_checks", "enrich", "card_fetch"))
        failed_enrich = [r["model_id"] for r in build.get("reenrich", []) if not r["updated"]]
        if failed_enrich:
            report["alerts"].append(f"보강 다시 조회 실패 (기존 값 유지): {failed_enrich}")
        gated = [c["model_id"] for c in report["carried"] if c.get("gated")]
        if gated:
            report["alerts"].append(f"게이트 승인 필요 (사람이 Hugging Face 에서 승인해야 함): {gated}")
        flagged = {c["model_id"]: c for c in build["checks"] if c["important_changes"] or c["chunks"]["flags"]}
        if flagged:
            report["alerts"].insert(0, f"점검 표시: {sorted(flagged)} (중요 필드 변경·청크 수 급변·머리말 누락)")
        advance("built")
    if state["stage"] == "built":
        t0 = time.perf_counter()
        ops.worker("eval", work, cases=work / "cases.jsonl", out=work / "eval_after.json")
        timings["eval"] = round(timings.get("eval", 0) + time.perf_counter() - t0, 1)
        finish_eval(work, report)
        advance("evaluated")
    if state["stage"] == "evaluated":
        v = report["evaluation"]["verdict"]
        if not v["swap"]:
            report["swap"] = {"swapped": False, "reason": "교체 판정 '심각': 교체하지 않음. 작업 공간을 남김"}
            write_json(state_path, state)
        elif do_swap(root, work, state, ops, log):
            report["result"] = "swapped"
            write_json(report_path, report)
            shutil.rmtree(work)  # 교체 성공 후 작업 공간 정리
            return report
        else:
            write_json(state_path, state)
    report["result"] = "swapped" if report.get("swap", {}).get("swapped") else "not_swapped"
    write_json(report_path, report)
    return report
