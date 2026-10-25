# 컬렉션과 메타데이터 설계

- 상태: 확정
- 최종 수정일: 2026-10-25
- 관련 문서: [retrieval-and-ui.md](retrieval-and-ui.md), [index-text.md](index-text.md), [decisions.md](decisions.md), [evaluation.md](../reports/evaluation.md)

## 요약

- 항목 필드는 임베딩 본문 / Chroma 메타데이터 / 원본 파일 세 곳에 나눠 둔다. 메타데이터는 답변 LLM에게 보이지 않으므로 근거로 답할 사실은 본문에도 넣는다.
- 다운로드 수는 임베딩하지 않고 정렬과 근거 텍스트 덧붙이기에만 쓴다. 인기도 지표이지 성능 지표가 아니다.
- 컬렉션은 `items`(모델당 1청크)와 `docs`(모델 카드 + 위키, `doc_type`으로 구분) 두 개. 검색은 출처별로 따로 한다 (카드 `card_k`=6, 위키 `wiki_k`=2) — 함께 검색하면 영어 카드 청크가 한국어 위키 청크에 밀려나서.
- 카드는 머리말의 정해 둔 키도 색인하고 가치가 낮은 섹션은 뺀다 (잠정). 재색인 건너뛰기 기준은 `model_id` + `card_revision` + `index_version`.
- 청크 ID는 규칙으로 만든다 (`{model_id}:{doc_id}:{chunk_index}`). 재실행해도 청크 수가 변하지 않고, 재색인 시 기존 청크를 먼저 지운다.

## 1. 항목 필드의 세 가지 배치

| 위치 | 넣을 필드 | 기준 |
|---|---|---|
| **임베딩 본문** (Chroma `document`) | 모델명, 개발사, 계열·버전, 크기·구조, 입력 모달리티, 학습 단계, 분야, 지원 언어, 컨텍스트 길이, 라이선스, 도구 호출, 베이스 모델, 소개 요약 | 의미 검색에 걸려야 하거나 답변 LLM이 근거로 읽어야 하는 사실 |
| **Chroma 메타데이터** | `model_id`, `params_b`, `stage`, `category`, `vendor_country`, `license`, `gated`, `context_len`(정수), 모달리티 플래그(`mod_image` 등), 언어 플래그(`lang_ko` 등), `downloads_30d_adj`, `status`, `snapshot_date`, `source_type`, `card_url`, `card_revision` | 정확히 거르는 조건, 정렬 기준, 근거 표시용 출처 |
| **원본 파일에만** (`data/items_*.json`) | 원본 다운로드 수, `selection_group`, `group_rank`, `first_seen`, `last_qualified`, `*_needs_review`, `context_library_version`, `weight_precision`, 아키텍처 세부 | 선별 기록·운영용. 필요하면 `model_id`로 조인 |

### 규칙
- **메타데이터에만 있는 값은 답변 LLM에게 보이지 않는다.** 근거로 답해야 하는 사실(라이선스, 컨텍스트 길이 등)은 메타데이터에 있더라도 본문에도 넣는다.
- **Chroma 메타데이터 값은 문자열·숫자·참거짓만 쓰고, 빈 값(None)은 키를 빼서 표현한다.** 목록 필드는 플래그로 펼친다.
  - `input_modalities: [text, image]` → `mod_text: true`, `mod_image: true`
  - `languages: [ko, en]` → `lang_ko: true`, `lang_en: true`
- **본문이 서로 비슷해지는 문제:** 항목을 구별해 주는 것은 소개 요약이다. 요약 반영 후 조건 검색 품질 확인은 [backlog.md](backlog.md) 1절 "데이터 갱신"에서 관리한다.

## 2. 다운로드 수 (인기도)의 쓰임

**임베딩 본문에는 넣지 않는다. 메타데이터 정렬 기준과 근거 텍스트 덧붙이기로 쓴다.**

| 쓰임 | 방법 |
|---|---|
| "가장 많이 쓰이는 모델" 찾기 | 메타데이터 필터로 후보를 거른 뒤, 앱에서 `downloads_30d_adj` 기준으로 정렬 (Chroma는 정렬 기능이 없어 파이썬에서 정렬) |
| 답변에서 인기도를 근거로 언급 | 검색 단계(retrieve)에서 항목 근거 텍스트 끝에 "최근 30일 다운로드: N회 (YYYY-MM-DD 기준)" 한 줄을 메타데이터로부터 덧붙여 LLM에 넘김 |

- 이유: 임베딩 유사도는 순위를 계산하지 못한다 / 숫자는 의미 검색 노이즈 / 갱신마다 재임베딩이 필요해진다.
- **"임베딩 본문"(검색용, 고정)과 "LLM에 넘기는 근거 텍스트"(검색 시점에 본문 + 메타데이터로 조립)를 분리한다.**
- 다운로드 수는 인기도 지표이지 성능 지표가 아니다. 화면·답변에서 "많이 쓰이는 모델"로 표현하고 "성능이 좋은 모델"로 표현하지 않는다.

## 3. 외부 문서 수집·색인 방식

### 최종 목표 (MVP 이후)
미리 수집(B) + 즉석 수집(A) 복합, 우선순위 큐 기반. 백그라운드에서 카드를 수집·색인하고, 질문이 들어온 모델은 우선순위를 최상위로 올린다.

### MVP 방식
배경 작업자와 우선순위 큐는 만들지 않는다. 최종 구조의 핵심 부품만 만든다.

| 부품 | 내용 |
|---|---|
| **색인 단위 함수** `ensure_card_indexed(model_id)` | 한 모델의 카드를 받아 청킹·색인한다. 이미 같은 리비전으로 색인돼 있으면 아무것도 하지 않는다 (멱등). 재색인 시 해당 `model_id`+`doc_id`의 기존 청크를 먼저 지운다. |
| **색인 상태 기록** | 모델별 상태(`pending` / `indexing` / `done` / `failed`), 색인한 카드 리비전, 처리 일시 (JSON 또는 SQLite) |
| **호출 경로 ①: 일괄 색인 스크립트** (B) | 앱 실행 전에 202개 전체를 한 번 돈다. 실패는 `failed`로 남긴다. |
| **호출 경로 ②: 즉석 수집** (A) | 질문 시 선택한 모델이 `done`이 아니면 그 자리에서 `ensure_card_indexed` 호출, 진행 상태 표시 (F2012) |

### 기본 기능 흐름(F2003~F2004)과의 관계

| 문서 종류 | 예 | 수집 방식 | 프롬프트 |
|---|---|---|---|
| **항목 자체 문서** | 그 모델의 Hugging Face 모델 카드 | 미리 일괄 + 즉석 보충. 선별 없이 항상 색인 | 사용 안 함 |
| **추가 문서** | 한국어 위키백과의 계열·개념 문서 | 질문 시 수집: 검색어 추출(P1) → 검색 → 후보 선별(P2) → 청킹·색인. 같은 검색어는 다시 수집하지 않음 (NF2002). 단, 선별 결과가 0건이었던 검색어는 선별 모델이나 P2 프롬프트 버전이 바뀌면 다시 수집한다 (이전 선별 모델의 0건 결과가 캐시로 굳지 않도록) | 사용 |

### 카드 머리말과 섹션 처리

**머리말(YAML front matter)도 색인한다.** Llama 3.2 Vision의 EU 이용 제한처럼 중요한 이용 조건이 카드 본문이 아니라 머리말(`extra_gated_prompt`)에만 있는 경우가 있기 때문이다 (F2015 질문 4).
- 머리말에서 정해 둔 키만 골라 읽기 쉬운 텍스트로 바꿔 `section="front_matter"` 문서 조각으로 색인한다 (`doc_type=model_card`).
- 대상 키 (설정 `card.front_matter_keys`): `license`, `license_name`, `license_link`, `extra_gated_heading`, `extra_gated_prompt`, `extra_gated_description`, `language`, `base_model`, `pipeline_tag`, `library_name`
- 제외: `model-index`(벤치마크 결과, 양이 많고 노이즈), `widget`, `tags`
- `extra_gated_prompt`처럼 긴 값은 일반 청킹 규칙으로 나눈다.

**가치가 낮은 섹션은 검색 대상에서 뺀다 (잠정).** 질문과 무관한 섹션(Citation, Contributors 등)이 카드 근거 자리를 차지하지 않도록.
- 제외할 소제목 (설정 `chunk.exclude_sections`, 대소문자 무시 부분 일치): Citation, BibTeX, Contributors, Acknowledgement(s), Table of Contents, Contact
- 데이터(카드 파일)는 그대로 두고 색인에서만 뺀다.

**색인 규칙 버전.** 청킹·머리말 규칙이 바뀌면 같은 카드 리비전이어도 다시 색인해야 한다. 색인 상태 기록에 `index_version`을 두고, 건너뛰기 기준을 `model_id` + `card_revision` + `index_version`으로 한다 (설정 `index.version`).

## 4. 컬렉션 구성

| 컬렉션 | 내용 | 청크 단위 |
|---|---|---|
| `items` | 항목(모델) 색인 텍스트 202개 | 모델당 1청크 |
| `docs` | 모델 카드 + 추가 문서(위키) | 문서를 청크 크기로 분할 |

- 모델 카드와 위키 문서를 같은 `docs`에 두고 `doc_type`으로 구분한다 (F2016 출처 종류 표시).
- **검색은 출처별로 따로 한다.** 한 컬렉션에서 함께 검색하면 한국어 질문이 한국어 위키 청크와 유사도가 높게 나와, 영어 카드 청크가 근거에서 모두 밀려나기 때문이다. `doc_type=model_card`에서 `retrieve.card_k`개, `doc_type=wiki`에서 `retrieve.wiki_k`개를 따로 검색해 합친다. 카드 검색에는 P1이 만든 영어 검색 문구(`card_query_en`)를 쓴다.
- **카드 검색 방식.** `card_query_en` 하나로 검색하는 기준선을 쓴다. 다중 질의 결합(RRF), 청크 머리 정보, 두 가지 결합은 평가 세트(`tests/retrieval_eval/`, 33사례 × 표현 3개)에서 기준선이 맞히던 질의를 놓치게 만들어 쓰지 않는다 (설정 뒤에 실험용으로 남김).
  - `retrieve.card_k`는 6 — 정답 조각이 5~6위에 걸린 경우가 많아서. 답변 단위 비교에서도 손해가 없었다.
  - 남은 실패는 P1 문구가 질문의 핵심어를 빠뜨리는 경우다 (예: "지역 제한" → "regional availability", 정답 조각 24위). 이것은 검색이 아니라 프롬프트(P1) 쪽에서 다룬다.

## 5. 청크 메타데이터 (`docs` 컬렉션)

| 필드 | 예 | 용도 |
|---|---|---|
| `model_id` | `Qwen/Qwen3-8B` | **범위 좁히기**. 빠지면 다른 모델 문서가 근거에 섞인다 |
| `doc_type` | `model_card` / `wiki` | 출처 종류 구분 (F2007, F2016) |
| `doc_id` | `hf_card:Qwen/Qwen3-8B`, `wiki:12345` | 문서 식별 |
| `title`, `url` | 문서 제목, 원문 링크 | 근거 표시 (F2008) |
| `section` | 카드 소제목 (예: `License`) | 근거 표시, 검색 품질 |
| `doc_lang` | `en` / `ko` | 다국어 원칙 (D-08) |
| `revision` | 카드 커밋 해시 / 위키 리비전 ID | 버전 추적, 재색인 판단 |
| `chunk_index` | 0, 1, 2… | 순서 |
| `collected_at` | ISO 일시 | 관리 |
| `search_query` | 수집에 쓴 검색어 (추가 문서만) | 재수집 방지 (NF2002) |

- **개발사(조직) 필드는 따로 두지 않는다.** 개발사 단위로 거를 때는 항목 원본에서 그 개발사(`vendor`)의 `model_id` 목록을 구해 `model_id $in [...]`로 거른다. 여러 모델 비교(O-02)도 같은 방식.
- **여러 모델에 걸친 문서**는 모델마다 청크를 복제해 넣는다.
- **저장소 이름 변경** 시 ID가 바뀐다. MVP는 스냅샷 고정이라 문제없음.

## 6. 청크 식별자

| 컬렉션 | 규칙 | 예 |
|---|---|---|
| `items` | `item:{model_id}` | `item:Qwen/Qwen3-8B` |
| `docs` | `{model_id}:{doc_id}:{chunk_index}` | `Qwen/Qwen3-8B:hf_card:Qwen/Qwen3-8B:3` |

- 무작위 ID 금지. 같은 ID로 다시 넣으면 덮어쓰기가 되므로 재실행해도 청크 수가 변하지 않는다 ([검증 결과](../reports/evaluation.md) 참고).
- 재색인 시 해당 `model_id`+`doc_id`의 기존 청크를 먼저 지우고 넣는다 (청크 수가 줄어든 경우 대비).

## 7. 미정
- MoE 크기 기준 (O-05) — 현재 잠정: 전체 파라미터
