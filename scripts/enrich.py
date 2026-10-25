"""항목 보강 (D-07, 로직은 data_prep/enrich.py): 기계 판독 가능한 출처에서만 아키텍처·컨텍스트 길이·정밀도를 채운다.

- 모델 정보 API(expand=config,safetensors,sha): 아키텍처, model_type, MoE 전문가 수, 가중치 정밀도, 카드 리비전(sha), 도구 호출 템플릿 유무
- config.json: 컨텍스트 길이 (게이트 모델은 인증 필요 → 토큰 없으면 비워 두고 표시)
  키 이름이 모델 계열마다 다르다: max_position_embeddings / n_positions(GPT-2 계열) / seq_length 등.
  위치도 다르다: 최상위 / text_config / encoder·decoder(T5 계열).
- 설정 파일에 값이 없으면 transformers 설정 클래스의 기본값을 쓴다 (context_source=library_default).
  기본값은 라이브러리 버전에 따라 바뀔 수 있으므로 사용한 버전을 함께 저장한다.
- 위치 임베딩이 없는 구조(Mamba 등 상태 공간 모델)는 not_applicable 로 표시한다.
카드 본문 추정값은 쓰지 않는다.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from data_prep.enrich import enrich_fields  # noqa: E402
from data_prep.items import write_items  # noqa: E402

SRC, OUT_JSON, OUT_CSV = sys.argv[1:4]

items = json.loads(Path(SRC).read_text(encoding="utf-8"))
for it in items:
    it.update(enrich_fields(it["model_id"]))
    time.sleep(0.2)

write_items(items, Path(OUT_JSON), Path(OUT_CSV))

n = len(items)
print("항목", n)
print("아키텍처 확보", sum(bool(i["architecture"]) for i in items))
C = __import__("collections").Counter
print("컨텍스트 길이 출처", dict(C(i["context_source"] for i in items)))
print("MoE", sum(i["is_moe"] for i in items))
print("정밀도", C(i["weight_precision"] for i in items).most_common(6))
print("도구 호출 템플릿", sum(bool(i["chat_template_has_tools"]) for i in items))
print("접근 승인 필요:", [i["model_id"] for i in items if i["context_source"] == "access_pending"])
