"""항목 보강 (D-07): 기계 판독 가능한 출처에서만 아키텍처·컨텍스트 길이·정밀도를 채운다.

- 모델 정보 API(expand=config,safetensors,sha): 아키텍처, model_type, MoE 전문가 수, 가중치 정밀도, 카드 리비전(sha), 도구 호출 템플릿 유무
- config.json: 컨텍스트 길이 (게이트 모델은 인증 필요 → 토큰 없으면 비워 두고 표시)
  키 이름이 모델 계열마다 다르다: max_position_embeddings / n_positions(GPT-2 계열) / seq_length 등.
  위치도 다르다: 최상위 / text_config / encoder·decoder(T5 계열).
- 설정 파일에 값이 없으면 transformers 설정 클래스의 기본값을 쓴다 (context_source=library_default).
  기본값은 라이브러리 버전에 따라 바뀔 수 있으므로 사용한 버전을 함께 저장한다.
- 위치 임베딩이 없는 구조(Mamba 등 상태 공간 모델)는 not_applicable 로 표시한다.
카드 본문 추정값은 쓰지 않는다.
"""
import csv, json, os, sys, time, urllib.parse, urllib.request

SRC, OUT_JSON, OUT_CSV = sys.argv[1:4]
TOKEN = os.environ.get("HF_TOKEN")
UA = {"User-Agent": "finetune-model-explorer/0.1"}


def fetch(url, auth=False):
    h = dict(UA)
    if auth and TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                return None
            time.sleep(2 * (i + 1))
        except Exception:
            time.sleep(2 * (i + 1))
    return None


SUBCONFIGS = ("text_config", "llm_config", "language_config", "decoder", "encoder")
CONTEXT_KEYS = ("max_position_embeddings", "n_positions", "max_sequence_length", "seq_length", "n_ctx")
NO_POSITION_TYPES = {"mamba", "mamba2"}  # 위치 임베딩이 없는 구조


def pick(cfg, *keys):
    """최상위 → 하위 설정(text_config, decoder 등) 순으로 찾는다."""
    for src in (cfg,) + tuple(cfg.get(s) or {} for s in SUBCONFIGS):
        for k in keys:
            if src.get(k) is not None:
                return src.get(k)
    return None


def library_default_context(mid):
    """설정 파일에 값이 없을 때 transformers 설정 클래스의 기본값. 없으면 (None, None)."""
    try:
        import transformers
        from transformers import AutoConfig
        cfg = AutoConfig.from_pretrained(mid, token=TOKEN)
    except Exception:
        return None, None
    for sub in (cfg,) + tuple(getattr(cfg, s, None) for s in SUBCONFIGS):
        if sub is None:
            continue
        for k in CONTEXT_KEYS:
            if getattr(sub, k, None) is not None:
                return getattr(sub, k), f"transformers {transformers.__version__}"
    return None, None


def resolve_context(mid, cfg, model_type):
    """(값, 출처, 라이브러리 버전)"""
    if cfg is None:
        return None, "access_pending", None
    v = pick(cfg, *CONTEXT_KEYS)
    if v is not None:
        return v, "config.json", None
    if (model_type or "").lower() in NO_POSITION_TYPES:
        return None, "not_applicable", None
    v, ver = library_default_context(mid)
    if v is not None:
        return v, "library_default", ver
    return None, "not_in_config", None


items = json.load(open(SRC))
for it in items:
    mid = it["model_id"]
    q = urllib.parse.urlencode([("expand[]", e) for e in ("config", "safetensors", "sha")])
    info = fetch(f"https://huggingface.co/api/models/{mid}?{q}") or {}
    api_cfg = info.get("config") or {}
    tmpl = ((api_cfg.get("tokenizer_config") or {}).get("chat_template")) or ""
    if isinstance(tmpl, list):
        tmpl = " ".join(t.get("template", "") for t in tmpl if isinstance(t, dict))
    params = ((info.get("safetensors") or {}).get("parameters")) or {}

    cfg = fetch(f"https://huggingface.co/{mid}/resolve/main/config.json", auth=True)
    experts = pick(cfg or {}, "num_experts", "num_local_experts", "n_routed_experts") or api_cfg.get("num_experts")
    per_tok = pick(cfg or {}, "num_experts_per_tok", "moe_topk") or api_cfg.get("num_experts_per_tok")

    # API에 아키텍처가 비어 있으면 config.json 값으로 채운다
    arch = api_cfg.get("architectures") or (cfg or {}).get("architectures") or []
    model_type = api_cfg.get("model_type") or (cfg or {}).get("model_type")
    ctx, ctx_src, ctx_ver = resolve_context(mid, cfg, model_type)

    it.update({
        "architecture": ",".join(arch),
        "model_type": model_type,
        "is_moe": bool(experts),
        "num_experts": experts,
        "experts_per_token": per_tok,
        "max_position_embeddings": ctx,
        "context_source": ctx_src,
        "context_library_version": ctx_ver,
        "weight_precision": ",".join(sorted(params.keys())),
        "chat_template_has_tools": ("tools" in tmpl) if tmpl else None,
        "card_revision": info.get("sha"),
        "card_url": f"https://huggingface.co/{mid}",
    })
    time.sleep(0.2)

json.dump(items, open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(items[0].keys()))
    w.writeheader()
    for it in items:
        w.writerow({k: (",".join(v) if isinstance(v, list) else v) for k, v in it.items()})

n = len(items)
print("항목", n)
print("아키텍처 확보", sum(bool(i["architecture"]) for i in items))
C = __import__("collections").Counter
print("컨텍스트 길이 출처", dict(C(i["context_source"] for i in items)))
print("MoE", sum(i["is_moe"] for i in items))
print("정밀도", C(i["weight_precision"] for i in items).most_common(6))
print("도구 호출 템플릿", sum(bool(i["chat_template_has_tools"]) for i in items))
print("접근 승인 필요:", [i["model_id"] for i in items if i["context_source"] == "access_pending"])
