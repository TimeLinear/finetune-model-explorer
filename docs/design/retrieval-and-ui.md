# 검색 설정과 서비스 기능·화면 설계

- 상태: 확정
- 최종 수정일: 2026-10-25
- 관련 문서: [collections.md](collections.md), [prompts.md](prompts.md), [evaluation.md](../reports/evaluation.md), [performance.md](../reports/performance.md)

## 요약

- 검색·청킹 값은 모두 `config/settings.json`에 두고, 아래 "검색 설정" 표가 기본값의 기준이다 (`tests/test_settings_defaults.py`가 대조).
- 근거는 항목 청크 1개(항상 [근거 1]) + 카드 청크 6개 + 위키 청크 2개를 출처별로 따로 검색해 합친다. 위키가 모자라도 카드로 채우지 않는다.
- 화면은 Streamlit 멀티페이지(메인 질의응답·점검표 / 조건 탐색 / 리서치 준비 중)이고, 대화 기록은 모델별로 나눈다.
- 성능 목표는 웜 15초·콜드 40초 이내(답변 표시 완료까지), 중앙값으로 판정한다. `anthropic_direct` 측정에서 충족.
- 상세 오류·프롬프트·키는 화면에 내지 않고 로그에만 남긴다. 화면 문구는 `i18n/ko.json`에 둔다.

## 검색 설정

모든 값은 코드가 아니라 설정 파일(`config/settings.json`)에 둔다. 검증 단계에서 바꿔 비교한다.

| 설정 키 | 기본값 | 설명 |
|---|---|---|
| `chunk.splitter` | `markdown_then_recursive` | 모델 카드는 마크다운 소제목(`#`~`###`) 단위로 먼저 나누고, 긴 구간만 글자 수로 다시 나눈다. 소제목은 청크 메타데이터 `section`에 저장 |
| `chunk.size` | 1000 (글자) | |
| `chunk.overlap` | 200 (글자) | |
| `chunk.exclude_sections` | `["citation", "bibtex", "contributors", "acknowledg", "table of contents", "contact"]` | 색인에서 뺄 카드 소제목 (대소문자 무시 부분 일치, 잠정) |
| `card.front_matter_keys` | `["license", "license_name", "license_link", "extra_gated_heading", "extra_gated_prompt", "extra_gated_description", "language", "base_model", "pipeline_tag", "library_name"]` | 색인할 카드 머리말 키 |
| `index.version` | 2 | 색인 규칙 버전. 바꾸면 같은 카드 리비전도 다시 색인 |
| `index.chunk_header` | false | true면 카드 청크의 임베딩 본문 앞에 `[{model_id} \| {섹션 경로}]` 머리 정보를 붙인다. 바꾸면 전체 재색인이 필요하다 (`index.version`도 올린다). 평가에서 미채택, 실험용으로 남김 |
| `retrieve.item_always` | true | 선택한 모델의 항목 청크 1개는 검색 없이 항상 근거에 포함 (F2006) |
| `retrieve.card_k` | 6 | 모델 카드에서 가져올 청크 수 (해당 모델 범위 내, `doc_type=model_card`). 6개 — 평가 세트에서 정답 조각이 5~6위에 걸린 사례가 많아서 |
| `retrieve.wiki_k` | 2 | 위키백과에서 가져올 청크 수 (해당 모델 범위 내, `doc_type=wiki`) |
| `retrieve.search_type` | `similarity` | `mmr`로 바꾸면 F2014. MMR 결과 수도 출처별 `card_k`/`wiki_k`를 그대로 쓴다 (유사도 검색과 같은 개수로 비교하기 위해) |
| `retrieve.mmr_fetch_k` | 30 | MMR 사용 시 출처별 후보 수 |
| `retrieve.mmr_lambda` | 0.5 | |
| `retrieve.card_query_mode` | `single` | `single`: P1의 `card_query_en` 하나로 카드를 검색한다. `rrf`: `card_query_en`과 원래 질문으로 각각 검색해 순위를 결합한다(RRF). 평가에서 미채택, 실험용으로 남김 |
| `retrieve.rrf_candidates` | 10 | `rrf` 모드에서 질의별로 가져올 후보 수 |
| `retrieve.rrf_k` | 60 | RRF 점수 상수 (점수 = Σ 1/(`rrf_k` + 순위)) |
| `condition.candidate_k` | 30 | 조건 탐색에서 C2로 넘길 최대 후보 수 |
| `usage_check.card_k` | 8 | 사용 조건 점검표에 넣을 카드 청크 최대 수 (항목 메타데이터 1개는 별도) |
| `summary.card_max_chars` | 24000 | 요약 프롬프트에 넣을 카드 최대 길이 |
| `embedding.model` | `BAAI/bge-m3` | 로컬 임베딩 (후보: `intfloat/multilingual-e5-large`/`-small`) |
| `wiki.lang` | `ko` | 위키백과 언어 (`{lang}.wikipedia.org`) |
| `wiki.candidates_per_query` | 5 | 검색어당 후보 수 |
| `wiki.request_interval_sec` | 1.0 | 호출 간격 (NF2006) |
| `wiki.p2_concurrency` | 3 | 위키 후보 선별(P2)을 동시에 실행할 최대 수 (성능 개선용) |
| `hf.request_interval_sec` | 0.5 | Hugging Face 요청 간격 (NF2006) |
| `http.max_retries` | 3 | 외부 요청(Hugging Face·위키백과) 재시도 최대 횟수 (NF2006) |
| `answer.lang` | `ko` | 답변 언어 (D-08) |
| `answer.history_turns` | 4 | 답변 생성 시 넣을 같은 모델의 최근 대화 턴 수 |

- 근거 병합·중복 제거(F2006): 항목 청크 → 카드 청크(`card_k`) → 위키 청크(`wiki_k`) 순으로 합치고, 청크 ID 기준으로 중복을 제거한다. 근거 번호는 이 순서대로 1부터 붙인다 (항목 메타데이터가 항상 [근거 1]). 위키 청크가 모자라도 카드로 채우지 않는다.
- 카드 검색 설정은 평가 세트(`tests/retrieval_eval/`, 33사례 × 표현 3개)로 바꿔 비교한다. 결과 기록은 [evaluation.md](../reports/evaluation.md).
- 출처별로 따로 검색하는 이유: 한 컬렉션에서 함께 검색하면 한국어 질문이 한국어 위키 청크에 끌려 영어 카드 청크가 근거에서 빠지는 현상이 확인됐다. 카드 검색에는 P1의 `card_query_en`을 쓴다.

## 서비스 기능과 화면

### 화면 구성 (Streamlit 멀티페이지)

| 페이지 | 내용 | 관련 기능 |
|---|---|---|
| **메인: 모델 질의응답** (`app.py`) | 사이드바: 모델 선택(검색 가능한 선택 상자, 간단 필터), 현재 색인 수(items / docs), 선택 모델 요약 카드. 본문 탭 ① 질의응답 채팅 ② 사용 조건 점검표 | F2002 표시, F2009, F2010, F2012 |
| **조건 탐색** (`pages/1_조건_탐색.py`) | 자연어 조건 입력 → 결과 카드 목록(모델명, 크기, 모달리티, 라이선스, 다운로드, 맞는 이유) → 카드의 "이 모델에 질문하기" 버튼으로 메인 페이지 해당 모델 대화로 이동 | F2011 |
| **리서치** (`pages/2_리서치.py`) | 2단계. MVP에서는 "준비 중" 안내만 | D-02, O-01: 전용 페이지 |

### 대화 기록 구조 (세션 상태)

```
st.session_state.selected_model_id: str | None
st.session_state.chats: dict[model_id, list[message]]   # 모델별로 분리 (F2009)
st.session_state.research: dict                          # 2단계 전용, 채팅과 분리
message = {
  role: "user" | "assistant",
  content: str,
  evidence: list[{n, source_type, title, url, section}],  # 실제 인용된 근거만 (F2008)
  no_citation: bool                                        # 인용 근거가 하나도 없을 때 true → 안내 표시
}
```

### 도메인 특화 기능 (F2010): 사용 조건 점검표

- 모델을 고르고 탭을 열면 "점검표 만들기" 버튼 → 프롬프트 U로 생성.
- 점검 항목: 라이선스, 이용 승인 절차, 지원 언어, 컨텍스트 길이, 입력 모달리티, 의도된 용도, 제한·주의 사항.
- 각 행에 근거 번호, 하단에 근거 목록(제목·원문 링크), 면책 문구.
- 같은 모델·같은 카드 리비전의 점검표는 캐시해 재사용한다.

### 성능 목표 (NF2001)

| 상황 | 목표 (질문 입력 → 답변 표시 완료) |
|---|---|
| 웜: 같은 모델에 두 번째 이후 질문 (추가 문서 수집 없음) | 15초 이내 |
| 콜드: 그 모델의 첫 질문 (위키 수집·색인 포함) | 40초 이내 |

- 단계별 소요 시간(검색어 추출, 위키 검색·선별·수집, 임베딩, 검색, 답변 생성, 화면 표시)을 기록해 병목을 찾는다.
- **판정은 측정값의 중앙값으로 한다. 최댓값은 참고로 함께 기록한다.** 외부 API 응답 속도가 날마다 달라 개별 측정값이 튀기 때문이다.
- 스트리밍으로 첫 글자가 먼저 보이더라도, 목표는 "답변 표시 완료" 시점으로 잰다. 첫 글자 표시 시간은 따로 기록한다.
- **판정 결과 (`anthropic_direct`, 2026-10-23 측정): 충족.** Streamlit 콜드 중앙값 12.9초(최댓값 16.7초) / 웜 2.2초(최댓값 5.7초), 웹 화면 콜드 5.3초 / 웜 3.0초. 상세는 [performance.md](../reports/performance.md) 10절. 이번 콜드는 "그 서버에서 그 모델의 첫 질문" 정의다.

### highlights 표시

- 데이터는 원문 그대로 저장하고 자르지 않는다. 길이 처리는 화면에서만 한다.
- 칩은 CSS 말줄임(`text-overflow: ellipsis`)으로 표시하고, 마우스를 올리면 전체 문구가 보이게 `title` 속성을 단다.
- 메인 페이지 사이드바의 모델 요약 카드에는 "전체 보기" 접기 영역(`st.expander`)을 두어 highlights 원문 목록을 보여 준다 (모바일 대응).
- 조건 탐색 결과 카드처럼 가로로 나란한 카드에는 접기 영역을 두지 않는다 (카드 높이가 어긋남). 툴팁만 쓴다.
- highlights는 LLM이 생성한 문구이므로 HTML로 그릴 때 반드시 이스케이프한다.

### 안내와 오류 처리 (F2012, NF2004)

| 상황 | 화면 안내 |
|---|---|
| 처리 중 | `st.status`로 단계 표시: "카드 색인 확인 중" → "추가 문서 검색 중"(수집된 문서 제목 표시) → "답변 생성 중" |
| API 키 누락 (`ANTHROPIC_API_KEY` 등) | "API 키가 설정되지 않았습니다. `.env`에 현재 LLM 프로필의 키(기본 `ANTHROPIC_API_KEY`)를 설정하세요." 채팅 입력 비활성화 |
| 색인 0건 | "색인이 비어 있습니다. `python scripts/build_index.py`를 실행하세요." |
| 검색 결과 없음 / 조건 탐색 결과 없음 | "조건에 맞는 모델을 찾지 못했습니다. 조건을 줄여 보세요." |
| 인용 근거 없음 | 답변 아래 "이 답변에는 인용된 근거가 없습니다." |
| 카드 즉석 수집 실패 | "모델 카드를 가져오지 못했습니다. 항목 메타데이터만으로 답합니다." |
| 예외 | 사용자에게는 짧은 안내만, 상세 오류·프롬프트 전문·키는 화면에 노출하지 않고 로그 파일에만 기록 |
| 면책 (상시) | 사이드바 하단 + 점검표 하단: "라이선스 관련 내용은 모델 카드와 라이선스 원문을 요약한 참고 정보이며 법률 자문을 대신하지 않습니다. 상업적 이용 전에는 원문과 법무 검토를 확인하세요." |

모든 화면 문구는 `i18n/ko.json`에 둔다 (D-08).

### 문서에 없는 질문 처리

- 답변 생성 규칙 3: "제공된 문서에서 확인되지 않습니다."로 답하고, 확인되는 관련 정보만 덧붙인다. 추측하지 않는다.
- 이때 `no_citation=true`면 화면에 인용 근거 없음 안내.
