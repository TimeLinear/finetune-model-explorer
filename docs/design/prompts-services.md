# 프롬프트: 서비스 기능 (C1·C2·U)

- 상태: 확정
- 최종 수정일: 2026-10-25
- 관련 문서: [prompts.md](prompts.md), [retrieval-and-ui.md](retrieval-and-ui.md), [models.md](models.md), [decisions.md](decisions.md)

## 요약
- 조건 기반 탐색(F2011)의 C1(조건 → 필터·정렬 변환)·C2(후보 선별)와 사용 조건 점검표(F2010)의 U 프롬프트다. 본문은 `prompts/ko/<이름>.txt`와 같다.
- 현재 버전: C1 v0.1, C2 v0.4, U v0.3. 모델은 모두 `claude-haiku-5-5` (C1·C2 = `LLM_SMALL`, U = `LLM_ANSWER`).
- C2는 맞는 후보만 최대 `limit`개 출력한다 — 후보 전부를 판정하면 출력이 잘렸다.
- 공통 규칙(파일 분리, 구조화 출력 강제, 가상 모델명 few-shot)과 모델 배정 표는 [prompts.md](prompts.md)에 있다.

## C1. 조건 → 필터·정렬 변환 (`condition_parse.txt`) — F2011

**버전:** v0.1

**출력 스키마**
```
params_min_b: float | None
params_max_b: float | None
input_modalities_required: list["text"|"image"|"audio"|"video"]
languages_required: list[str]          # ISO 639-1
stage: "base" | "instruct" | None
categories: list["general"|"code"|"math"|"medical"|"document_ocr"|"translation"]
context_min_tokens: int | None
exclude_gated: bool
license_names: list[str]               # 사용자가 특정 라이선스를 지목한 경우만
sort_by: "downloads" | "params_asc" | "params_desc" | "newest" | None
semantic_query: str                    # 필터로 표현 못 한 나머지 조건 (의미 검색용, 한국어)
limit: int                             # 기본 5, 최대 10
```

**프롬프트**
```
너는 사용자가 원하는 언어 모델 조건을 검색 필터로 바꾸는 일을 한다.
숫자·참거짓으로 정확히 거를 수 있는 조건은 필드에 넣고, 나머지(용도, 강점, 분위기 등)는 semantic_query에 한국어 문장으로 남긴다.

규칙
1. 사용자가 말하지 않은 조건은 넣지 않는다 (기본값: None 또는 빈 목록).
2. "많이 쓰는", "인기 있는", "요즘 핫한"은 sort_by=downloads.
3. "가벼운", "작은"처럼 수치가 없는 크기 표현은 필터로 바꾸지 말고 sort_by=params_asc로 표현한다.
4. "상업적으로 쓸 수 있는" 같은 라이선스 판단 조건은 필터로 바꾸지 말고 semantic_query에 남긴다 (라이선스 판단은 근거 기반 답변에서 다룬다).
5. 컨텍스트 "128k"는 131072, "32k"는 32768처럼 2의 거듭제곱 값으로 바꾼다.

예시 1
입력: 이미지도 받을 수 있는 10B 이하 모델 중 요즘 제일 많이 쓰는 거
→ params_max_b=10, input_modalities_required=["text","image"], sort_by="downloads", semantic_query="", limit=5

예시 2
입력: 한국어 잘하고 긴 문서 넣을 수 있는 인스트럭트 모델, 승인 절차 없는 걸로
→ languages_required=["ko"], stage="instruct", context_min_tokens=None, exclude_gated=true, semantic_query="한국어에 강하고 긴 문서 처리에 적합한 모델", limit=5

예시 3
입력: 코드 짜는 데 쓸 가벼운 베이스 모델, 상업 이용 가능한 걸로
→ categories=["code"], stage="base", sort_by="params_asc", semantic_query="상업적으로 이용 가능한 코드 생성 모델", limit=5
```
※ 예시 2에서 "긴 문서"는 수치가 없어 필터로 바꾸지 않고 semantic_query로 남긴다.

**처리 흐름:** C1 결과로 Chroma `items` 컬렉션에 메타데이터 필터 + `semantic_query` 의미 검색(비어 있으면 필터만) → 후보 최대 30개 → `sort_by`가 있으면 파이썬에서 정렬 → C2로 최종 선별 → 카드 표시.

## C2. 조건 탐색 후보 선별 (`condition_select.txt`) — F2011

**버전:** v0.4 (`services/condition_search.py` `C2_PROMPT_VERSION`) — 맞는 후보만, 최대 `limit`개 출력한다. 후보 30개 전부에 판정·이유를 쓰면 Haiku `max_tokens` 2048에서 잘리고, 화면에는 맞는 후보만 표시하기 때문이다 (Haiku 출력 468토큰, 다운로드 상위 5개와 일치).

**출력 스키마**
```
picks: list[{ model_id: str, reason: str }]   # 맞는 후보만, 최대 limit개
```

**프롬프트**
```
너는 사용자의 조건에 맞는 모델만 고르는 일을 한다. 후보는 이미 숫자 조건으로 걸러져 있고, 정렬된 순서대로 나열되어 있다.
남은 조건(semantic_query)과 원래 요청에 비추어, 조건에 맞는 후보만 골라 picks에 넣는다.

[원래 요청] {request}
[남은 조건] {semantic_query}
[최대 개수] {limit}
[후보]
{candidate_item_texts}

규칙
1. 항목 정보에 근거가 있는 후보만 고른다. 정보가 없어 판단할 수 없는 후보는 고르지 않는다.
2. 라이선스 조건은 라이선스 이름만 보고 판단할 수 있을 때(예: apache-2.0, mit)만 맞는 것으로 본다. 자체 라이선스(other 등)는 고르지 않는다.
3. 후보를 나열된 순서대로 살펴보고, 최대 개수까지만 고른다. 고른 후보의 순서를 바꾸지 않는다.
4. reason은 조건에 맞는 근거를 한 문장으로 쓴다.
5. 맞는 후보가 없으면 picks를 빈 목록으로 둔다.
```

**코드 검증:** 후보에 없는 `model_id` 제거, 중복 제거, 원래 후보 순서로 재정렬, `limit`에서 자름.
**잘림 처리 (모든 구조화 출력 공통):** Anthropic `stop_reason="max_tokens"` / OpenAI 호환 `finish_reason="length"`이면 파싱 결과를 쓰지 않고 실패로 처리한다.

---

## U. 사용 조건 점검표 (`usage_check.txt`) — F2010 도메인 특화 기능

**버전:** v0.3

**용도:** 모델 하나를 고르면 도입 전에 확인할 조건을 근거와 함께 표로 보여 준다.
**근거 수집:** 항목 메타데이터 1개 + 모델 카드에서 점검 항목별 고정 검색어로 청크를 가져온다 (예: "license terms commercial use", "supported languages", "context length", "intended use limitations", "image input"). 카드 청크는 중복 제거 후 최대 `usage_check.card_k`개(기본 8)이고, 여기에 항목 메타데이터 1개를 더한다. 점검표는 모델 고유 조건만 다루므로 위키 문서는 쓰지 않는다.

**출력 스키마**
```
rows: list[{
  aspect: "license" | "gated" | "languages" | "context" | "modality" | "intended_use" | "limitations",
  finding: str,          # 근거에 적힌 내용 요약 (한국어 1~2문장)
  evidence_ids: list[int],
  status: "confirmed" | "not_in_documents"
}]
```

**프롬프트**
```
너는 오픈 웨이트 언어 모델을 회사에 도입하기 전 확인해야 할 조건을, 제공된 근거만 사용해 점검표로 정리하는 일을 한다.

[근거]
{evidence_blocks}

점검 항목: 라이선스(license), 이용 승인 절차(gated), 지원 언어(languages), 컨텍스트 길이(context), 입력 모달리티(modality), 의도된 용도(intended_use), 제한·주의 사항(limitations)

규칙
1. 각 점검 항목마다 근거에 적힌 내용을 한국어 1~2문장으로 정리하고, 사용한 근거 번호를 evidence_ids에 넣는다.
2. 근거에 내용이 없으면 status=not_in_documents, finding="제공된 문서에서 확인되지 않습니다."로 쓴다.
3. 라이선스는 조건을 전달만 하고 "사용 가능/불가" 판단은 쓰지 않는다.
4. 수치·이름은 근거에 적힌 그대로 쓴다.
```
**화면:** 표 + 근거 목록 + 면책 문구("라이선스 관련 내용은 참고 정보이며 법률 자문을 대신하지 않습니다…").
