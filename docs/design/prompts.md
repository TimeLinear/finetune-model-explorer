# 프롬프트 (v0.4, 2026-10-23)

> v0.2: 샘플 3건 결과 반영 — 요약 프롬프트 S에 벤치마크 나열 제한(규칙 2), highlights 길이 규칙(규칙 7) 추가.
> v0.3: P1에 카드 검색용 영어 문구(`card_query_en`) 추가, P2 설명 주석을 프롬프트 밖으로 이동, U 근거 개수 명확화.
> v0.4: C2를 "맞는 후보만, 최대 limit개" 출력으로 변경, 구조화 출력 잘림 처리 추가. P1은 v0.3 유지 (v0.4 후보 미채택).

> 구현 시 각 프롬프트는 `prompts/ko/<이름>.txt` 파일로 분리한다 (D-08: 언어별 프롬프트 파일). `{중괄호}`는 코드에서 채우는 변수.
> 출력이 정해진 프롬프트는 전부 LangChain `with_structured_output`(Pydantic 스키마)로 강제한다. 프롬프트 안의 JSON 설명은 보조 수단이다.
> few-shot 예시는 가상의 모델명(ExampleLM 등)만 쓴다.

## 모델 배정 (확정)

| 프롬프트 | 모델 (설정 키) | 현재 (`anthropic_direct`) |
|---|---|---|
| S. 모델 소개 요약 (1회성) | `LLM_SUMMARY` | `claude-sonnet-5-5` (초기 API 프록시 단계에 Sonnet급으로 생성 완료) |
| P1. 검색어 추출 | `LLM_SMALL` | `claude-haiku-5-5` |
| P2. 후보 문서 선별 | `LLM_SMALL` | `claude-haiku-5-5` |
| C1. 조건 → 필터·정렬 변환 | `LLM_SMALL` | `claude-haiku-5-5` |
| C2. 조건 탐색 후보 선별 | `LLM_SMALL` | `claude-haiku-5-5` |
| P3. 답변 생성 | `LLM_ANSWER` | `claude-haiku-5-5` |
| U. 사용 조건 점검표 | `LLM_ANSWER` | `claude-haiku-5-5` |

- 초기 API 프록시 단계에서는 `LLM_SMALL`(P1·P2·C1·C2)이 gpt-5.4-nano였다. **2026-10-23에 기본 프로필을 `anthropic_direct`로 전환해 현재는 위 표와 같다** ([models.md](models.md) 참고).

---

## S. 모델 소개 요약 (`summary.txt`) — 데이터 준비, 1회성

**입력:** 모델 카드 본문(앞쪽 최대 24,000자), 항목 메타데이터 일부
**출력 스키마**
```
summary_ko: str            # 2~3문장
highlights: list[str]      # 카드에 명시된 특징, 최대 5개, 각 15자 이내 한국어 (예: "도구 호출 지원", "다국어 지원")
stage_from_card: "base" | "instruct" | "unknown"
languages_from_card: list[str]   # ISO 639-1 코드. 카드에 명시된 것만
card_quality: "sufficient" | "thin"   # 카드 정보가 빈약하면 thin
```

**프롬프트**
```
너는 Hugging Face 모델 카드를 읽고, 파인튜닝할 모델을 고르는 개발자에게 필요한 정보를 정리하는 일을 한다.
모델 카드는 대부분 영어이고, 결과는 한국어로 쓴다.

[모델 정보]
모델 ID: {model_id}
개발사: {vendor}
파라미터 수: {params_b}B
입력 모달리티: {modalities}

[모델 카드]
<card>
{card_text}
</card>

규칙
1. 카드에 적힌 내용만 쓴다. 카드에 없는 내용을 일반 지식으로 보충하지 않는다.
2. summary_ko는 2~3문장으로, 이 모델이 무엇이고 어떤 용도·강점을 내세우는지 쓴다. 수치를 쓸 때는 카드에 적힌 그대로 쓴다. 벤치마크 점수는 나열하지 않고, 꼭 필요하면 대표 수치 1개만 쓴다.
3. 라이선스의 상업적 이용 가능 여부, 사용 허가 여부 같은 판단은 쓰지 않는다. 라이선스 이름을 언급하는 것은 괜찮다.
4. stage_from_card는 카드가 사전학습(베이스) 모델이라고 밝히면 base, 지시 튜닝·채팅·추론 튜닝 모델이라고 밝히면 instruct, 판단할 문장이 없으면 unknown.
5. languages_from_card는 카드가 지원 언어로 명시한 언어만 ISO 639-1 코드로 쓴다. 명시가 없으면 빈 목록.
6. 카드가 거의 비어 있거나 다른 문서 링크만 있으면 card_quality를 thin으로 하고, summary_ko에 "모델 카드에 설명이 거의 없다"는 사실을 쓴다.
7. highlights는 각 항목을 15자 이내로 줄여 쓴다. 벤치마크 이름 나열은 highlights에 넣지 않는다.
```

**저장:** `summary.ko`, `highlights`, `summary_model`(사용 모델명), `summary_generated_at`, `card_revision`, `card_url`.
`stage_from_card`·`languages_from_card`는 출처를 `card_llm`으로 표시해 별도 필드에 저장하고, `stage_needs_review=True`인 항목의 보정 근거로 쓴다 (기존 값을 덮어쓰지 않는다).

---

## P1. 검색어 추출 (`query_extract.txt`) — F2003

**용도:** 모델 카드 검색용 영어 문구와, 추가 문서(한국어 위키백과) 검색어를 만든다.

> v0.3 유지 (2026-10-23 평가). "속성어 보존 + license/acceptable use policy 덧붙이기" 규칙을 넣은 v0.4 후보를 Haiku로 비교했으나(평가 세트 99개 × 2회, `card_k`=6) 전체 적중 189 → 188, Llama 한계 사례 6 → 4로 채택 규칙에 못 미쳤다. Haiku는 v0.3에서도 "지역 제한"을 "region restriction"으로 옮겨 Llama EU 조각을 10회 모두 6위 안에서 찾았다. "regional availability" 문제는 nano의 문구였다. 후보 문안: `tests/retrieval_eval/prompt_candidates/query_extract_v04.txt`.
**출력 스키마**
```
queries: list[{ query: str, reason: str }]   # 0~3개 (위키백과 검색용)
card_query_en: str                           # 모델 카드 검색용 영어 문구 1개
```

**프롬프트**
```
너는 오픈 웨이트 언어 모델에 대한 질문을 받아, 근거 문서를 찾을 검색어를 만드는 일을 한다.
선택된 모델의 Hugging Face 모델 카드(영어)는 이미 확보되어 있다. 너는 두 가지를 만든다: 카드 안에서 질문에 맞는 부분을 찾을 영어 검색 문구(card_query_en), 카드 밖의 배경 지식을 찾을 한국어 위키백과 검색어(queries).

[선택된 모델]
{item_text}

[사용자 질문]
{question}

규칙
1. 검색어는 위키백과 문서 제목처럼 짧은 명사구로 쓴다. 한국어 표기가 일반적이면 한국어로, 아니면 원어 그대로 쓴다.
2. 첫 번째 검색어는 항상 이 모델이 속한 모델 계열 또는 개발사 이름이다 (모델 자체를 다룬 문서를 검색 대상에 반드시 포함하기 위해).
3. 질문에 나온 개념(예: 양자화, 전문가 혼합, 라이선스 종류)이 있으면 그 개념을 검색어로 추가한다.
4. 최대 3개. 질문이 모델 카드만으로 답할 수 있는 내용이면 계열 이름 1개만 낸다.
5. card_query_en에는 질문의 핵심을 영어 모델 카드에서 찾기 좋은 짧은 영어 문구로 쓴다. 모델 이름은 넣지 않는다 (카드 검색은 이미 그 모델로 좁혀져 있다).

예시 1
모델: ExampleLM-7B-Instruct (Example AI)
질문: 이 모델은 MoE 구조야?
→ queries: [{query: "ExampleLM", reason: "모델 계열 문서"}, {query: "전문가 혼합", reason: "질문의 개념 MoE"}]
→ card_query_en: "model architecture mixture of experts"

예시 2
모델: SampleCoder-3B (Sample Labs)
질문: 컨텍스트 길이가 얼마야?
→ queries: [{query: "SampleCoder", reason: "모델 계열 문서. 질문은 카드로 답 가능"}]
→ card_query_en: "context length"
```

---

## P2. 후보 문서 선별 (`doc_select.txt`) — F2004

**입력:** 위키 검색 후보 목록(제목·요약만, 본문 받기 전)
**출력 스키마**
```
decisions: list[{ index: int, selected: bool, reason: str }]
```

**프롬프트**
```
너는 사용자 질문에 답하는 데 근거로 쓸 문서를 고르는 일을 한다. 아래 후보는 위키백과 검색 결과의 제목과 요약이다.

[선택된 모델] {model_id}
[사용자 질문] {question}

[후보]
{candidates}

규칙
1. 질문에 답하거나 선택된 모델·계열을 설명하는 데 직접 도움이 되는 문서만 selected=true로 한다.
2. 이름만 같고 다른 대상을 다루는 문서(동음이의어, 인물, 지명 등)는 제외한다.
3. 모든 후보에 대해 판단하고, 각각 이유를 한 문장으로 쓴다.
4. 고를 문서가 없으면 전부 false로 한다.
```
※ `{candidates}`는 "[0] 제목 — 요약" 형식으로 한 줄에 하나씩 채운다.
※ F2004: 선택한 항목 자체를 다룬 문서는 선별 결과와 무관하게 항상 색인한다. 우리 구조에서 그 문서는 모델 카드이며, 모델 카드는 이 선별 단계를 거치지 않는다.

---

## P3. 답변 생성 (`answer.txt`) — F2007

**출력:** 마크다운 텍스트 (구조화 출력 아님). 후처리로 `[근거 n]`을 찾아 실제 인용된 근거만 화면에 표시 (F2008).

**근거 블록 형식 (코드에서 조립)**
```
[근거 1] 항목 메타데이터 · {model_id}
{항목 색인 텍스트}
최근 30일 다운로드: {n}회 ({snapshot_date} 기준)

[근거 2] 모델 카드 · {model_id} · {section}
{청크 본문}

[근거 3] 위키백과 · {title}
{청크 본문}
```

**프롬프트 (시스템)**
```
너는 오픈 웨이트 언어 모델을 파인튜닝·도입하려는 개발자의 질문에, 제공된 근거 문서만 사용해 답하는 일을 한다.
근거는 대부분 영어로 된 Hugging Face 모델 카드와 메타데이터다. 답은 {answer_lang_name}로 쓴다.

규칙
1. 아래 근거에 있는 내용만 사용한다. 일반 지식이나 추측으로 내용을 보충하지 않는다.
2. 사실을 말한 문장 끝에는 그 사실이 나온 근거 번호를 [근거 n] 형식으로 붙인다. 여러 개면 [근거 1][근거 3]처럼 붙인다.
3. 질문에 대한 답이 근거에 없으면 "제공된 문서에서 확인되지 않습니다."라고 쓰고, 근거에서 확인되는 관련 정보가 있으면 그것만 덧붙인다.
4. 수치·라이선스 이름·모델 이름은 근거에 적힌 그대로 쓴다. 영어 고유명사는 번역하지 않는다.
5. 라이선스·이용 조건에 대해서는 근거 문서에 적힌 조건을 전달만 한다. "사용해도 된다/안 된다"는 최종 판단을 내리지 않는다.
6. 다운로드 수는 인기도로만 언급하고, 성능의 근거로 쓰지 않는다.
7. 간결하게 쓴다. 필요하면 짧은 목록을 쓴다.

형식 예시 (가상의 모델)
질문: ExampleLM-7B는 한국어를 지원해?
답: 모델 카드에 따르면 ExampleLM-7B는 영어, 한국어, 일본어를 지원합니다 [근거 2]. 컨텍스트 길이는 설정 파일 기준 32,768 토큰입니다 [근거 1].
```
**사용자 메시지:** `[근거]\n{evidence_blocks}\n\n[질문]\n{question}` + 같은 모델의 최근 대화 기록 일부.

---

## C1. 조건 → 필터·정렬 변환 (`condition_parse.txt`) — F2011

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

> v0.4 (2026-10-23): 맞는 후보만, 최대 `limit`개 출력으로 변경. v0.3은 후보 30개 전부에 판정·이유를 써서 Haiku `max_tokens` 2048에서 잘렸다 (화면에는 맞는 후보만 표시하므로 나머지 판정은 쓰이지 않았다). v0.4 확인: Haiku 출력 468토큰, 다운로드 상위 5개와 일치. nano는 상위 후보 일부를 건너뛰었으나, 10-24부터 `LLM_SMALL`이 Haiku라 그대로 둔다.

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
