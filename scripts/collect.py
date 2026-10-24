"""D-04 기준 커버리지 확인: 공식 조직 계정의 1~24B 언어 모델 집계."""
import json, re, sys, time, urllib.parse, urllib.request

OUT = sys.argv[1]

ORGS = {
    # 해외
    "meta-llama": "Meta", "google": "Google", "Qwen": "Alibaba(Qwen)", "mistralai": "Mistral AI",
    "microsoft": "Microsoft", "deepseek-ai": "DeepSeek", "allenai": "AI2", "ibm-granite": "IBM",
    "nvidia": "NVIDIA", "HuggingFaceTB": "Hugging Face", "tiiuae": "TII", "internlm": "Shanghai AI Lab",
    "zai-org": "Zhipu(Z.ai)", "THUDM": "Zhipu(THUDM)", "CohereLabs": "Cohere", "CohereForAI": "Cohere",
    "openai": "OpenAI", "LiquidAI": "Liquid AI", "tencent": "Tencent", "baidu": "Baidu",
    "moonshotai": "Moonshot", "01-ai": "01.AI", "swiss-ai": "Swiss AI",
    # 한국
    "LGAI-EXAONE": "LG AI연구원", "naver-hyperclovax": "NAVER", "kakaocorp": "Kakao", "skt": "SKT",
    "upstage": "Upstage", "K-intelligence": "KT", "trillionlabs": "Trillion Labs", "NCSOFT": "NCSOFT",
}
KOREAN = {"LGAI-EXAONE", "naver-hyperclovax", "kakaocorp", "skt", "upstage", "K-intelligence", "trillionlabs", "NCSOFT"}

EXPAND = ["safetensors", "cardData", "pipeline_tag", "downloads", "downloadsAllTime", "likes", "trendingScore", "createdAt", "gated", "tags"]
PIPES = {"text-generation", "image-text-to-text"}
EXCLUDE = re.compile(r"(gguf|awq|gptq|fp8|fp4|int4|int8|w4a16|w8a8|nvfp4|mxfp4|bnb|4bit|8bit|quant|onnx|mlx|exl2|reward|-rm\b|prm|guard|embed|eagle|draft|-mtp)", re.I)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "finetune-model-explorer/0.1"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r), r.headers.get("Link")
        except Exception as e:  # noqa
            time.sleep(2 * (i + 1))
    return None, None


rows, missing = [], []
for org, vendor in ORGS.items():
    q = urllib.parse.urlencode([("author", org), ("limit", 1000)] + [("expand[]", e) for e in EXPAND])
    url = f"https://huggingface.co/api/models?{q}"
    models = []
    while url:
        data, link = get(url)
        if data is None:
            break
        models += data
        m = re.search(r'<([^>]+)>;\s*rel="next"', link or "")
        url = m.group(1) if m else None
        time.sleep(0.3)
    if not models:
        missing.append(org)
        continue
    for m in models:
        mid = m["id"]
        pipe = m.get("pipeline_tag")
        total = (m.get("safetensors") or {}).get("total")
        tagset = set(m.get("tags") or [])
        lm_like = pipe in PIPES or (pipe is None and ("conversational" in tagset or "text-generation" in tagset or "mistral-common" in tagset or "vllm" in tagset))
        if not lm_like or not total or EXCLUDE.search(mid) or re.search(r"(voxtral|whisper|speech|tts|asr)", mid, re.I):
            continue
        if not (1e9 <= total <= 24.99e9):
            continue
        card = m.get("cardData") or {}
        name = mid.split("/")[1].lower()
        tags = m.get("tags") or []
        base_tags = [t for t in tags if t.startswith("base_model:")]
        is_instruct = bool(re.search(r"(instruct|chat|-it\b|-it-|thinking|reasoning)", name)) or (
            "conversational" in tags and not re.search(r"(base|-pt\b|-pt-)", name))
        rows.append({
            "id": mid, "org": org, "vendor": vendor, "korean": org in KOREAN,
            "params_b": round(total / 1e9, 2), "pipeline": pipe,
            "stage": "instruct" if is_instruct else "base",
            "license": card.get("license") or next((t[8:] for t in tags if t.startswith("license:")), None),
            "languages": card.get("language"), "gated": m.get("gated"),
            "downloads": m.get("downloads"), "downloads_all": m.get("downloadsAllTime"), "likes": m.get("likes"), "trending": m.get("trendingScore"), "tags": tags, "created": (m.get("createdAt") or "")[:10],
            "derived": any(t.startswith("base_model:finetune:") or t.startswith("base_model:quantized:") for t in base_tags),
        })

json.dump({"rows": rows, "missing_orgs": missing}, open(OUT, "w"), ensure_ascii=False, indent=1)
print(len(rows), "models; missing orgs:", missing)
