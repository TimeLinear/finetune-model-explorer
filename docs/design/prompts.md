# 프롬프트

- 상태: 확정
- 최종 수정일: 2026-10-25
- 관련 문서: [prompts-services.md](prompts-services.md), [models.md](models.md), [retrieval-and-ui.md](retrieval-and-ui.md), [decisions.md](decisions.md), [evaluation.md](../reports/evaluation.md)

## 요약
- 프롬프트 7개(S, P1, P2, P3, C1, C2, U)의 본문은 `prompts/ko/<이름>.txt`와 같고, 문서 버전은 v0.4다. 이 문서는 공통 규칙·모델 배정과 S·P1~P3, 서비스 기능 프롬프트 C1·C2·U는 [prompts-services.md](prompts-services.md)에 있다.
- 현재 버전: S v0.2, P1 v0.3, P2 v0.3, P3 v0.1, C1 v0.1, C2 v0.4, U v0.3 (S·P1·P2·C2는 코드의 `PROMPT_VERSION` 상수와 같다).
- 출력이 정해진 프롬프트는 `with_structured_output`(Pydantic 스키마)로 강제하고, 출력이 잘리면(`max_tokens`/`length`) 실패로 처리한다.
- 모델 배정: S는 `LLM_SUMMARY`(claude-sonnet-5-5), 나머지는 `LLM_SMALL`·`LLM_ANSWER`(claude-haiku-5-5, 기본 프로필 `anthropic_direct`).
- P1은 v0.3을 쓴다 — v0.4 후보가 평가에서 채택 규칙에 못 미쳤다. C2는 맞는 후보만 최대 `limit`개 출력한다 — 후보 전부를 판정하면 출력이 잘렸다.

## 공통 규칙

- 각 프롬프트는 `prompts/ko/<이름>.txt` 파일로 분리한다 (D-08: 언어별 프롬프트 파일). `{중괄호}`는 코드에서 채우는 변수.
- 출력이 정해진 프롬프트는 전부 LangChain `with_structured_output`(Pydantic 스키마)로 강제한다. 프롬프트 안의 JSON 설명은 보조 수단이다.
- few-shot 예시는 가상의 모델명(ExampleLM 등)만 쓴다.

## 모델 배정

| 프롬프트 | 모델 (설정 키) | 현재 (`anthropic_direct`) |
|---|---|---|
| S. 모델 소개 요약 (카드 본문이 바뀌면 다시 생성, [data-refresh.md](data-refresh.md)) | `LLM_SUMMARY` | `claude-sonnet-5-5` (초기 API 프록시 단계에 Sonnet급으로 생성 완료) |
| P1. 검색어 추출 | `LLM_SMALL` | `claude-haiku-5-5` |
| P2. 후보 문서 선별 | `LLM_SMALL` | `claude-haiku-5-5` |
| C1. 조건 → 필터·정렬 변환 | `LLM_SMALL` | `claude-haiku-5-5` |
| C2. 조건 탐색 후보 선별 | `LLM_SMALL` | `claude-haiku-5-5` |
| P3. 답변 생성 | `LLM_ANSWER` | `claude-haiku-5-5` |
| U. 사용 조건 점검표 | `LLM_ANSWER` | `claude-haiku-5-5` |

- 위 표는 기본 프로필 `anthropic_direct` 기준이다 ([models.md](models.md) 참고).
- C1·C2·U 본문: [prompts-services.md](prompts-services.md)

---

## S. 모델 소개 요약 (`summary.txt`) — 데이터 준비, 카드 본문이 바뀌면 다시 생성 ([data-refresh.md](data-refresh.md))

**버전:** v0.2 (`data_prep/summaries.py` `PROMPT_VERSION`)

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

**버전:** v0.3 (`data_prep/wiki.py` `P1_PROMPT_VERSION`) — v0.4 후보는 평가에서 채택 규칙에 못 미쳐 쓰지 않는다 (전체 적중 189 → 188, [evaluation.md](../reports/evaluation.md)). 후보 문안: `tests/retrieval_eval/prompt_candidates/query_extract_v04.txt`.

**용도:** 모델 카드 검색용 영어 문구와, 추가 문서(한국어 위키백과) 검색어를 만든다.
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

**버전:** v0.3 (`data_prep/wiki.py` `P2_PROMPT_VERSION`)

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

**버전:** v0.1

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
