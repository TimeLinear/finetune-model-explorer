# 기능 정의

- 상태: 확정
- 최종 수정일: 2026-10-25
- 관련 문서: [architecture.md](architecture.md), [evaluation.md](evaluation.md), [domain.md](../design/domain.md)

> 파인튜닝 모델 탐색기 (RAG 기반 도메인 지식 서비스)가 하는 일을 기능 번호별로 정리한다.
> 기능 번호(F2001~F2016, NF2001~NF2007, A-01~A-05)는 다른 문서에서 그대로 가리키는 이 프로젝트의 번호다.
> 기준일: 2026-10-23 (개발 기간 2026-10-21~23)

## 1. 도메인

파인튜닝에 쓸 오픈 웨이트 언어 모델을 고르는 사람을 위한 서비스다. 공식 조직이 Hugging Face에 공개한 약 1~24B 모델(멀티모달 포함) 202개를 다룬다 (2026-10-21 스냅샷).

| 항목 | 내용 |
|---|---|
| 항목 메타데이터 | Hugging Face Hub API + 저장소 config.json, 202건 |
| 외부 문서 | ① Hugging Face 모델 카드 (항목과 1:1, 주 출처) ② 한국어 위키백과 (보조) |
| 이용 조건 | 모델 카드: Hugging Face 이용약관 + 저장소별 라이선스 / 위키백과: CC BY-SA 4.0 |
| 근거가 필요한 질문의 예 | 같은 회사 모델 간 라이선스 차이, 자체 라이선스 조건, 설정 파일에 없는 컨텍스트 길이, 모델별 이용 정책 제한, LLM 학습 이후 공개된 모델의 수치 |
| 면책 | 건강·금융 도메인은 아니지만 라이선스 판단이 법률 문제에 걸쳐 있어 면책 안내를 둔다 |

도메인을 고른 이유와 데이터 범위: [domain.md](../design/domain.md)

## 2. 기능 목록

상태 표기: **구현** = 동작을 확인함 (확인 내용은 [evaluation.md](evaluation.md)).
화면: Streamlit = `app.py`(사이드바·질의응답 탭·사용 조건 점검표 탭), `pages/1_조건_탐색.py` / 웹 = `web/static/index.html`·`explore.html`.

### 2.1 핵심 기능 (RAG 질의응답과 서비스 기능)

| 번호 | 분류 | 이름 | 설명 | 구현 위치 | 상태 |
|---|---|---|---|---|---|
| F2001 | 데이터 | 항목 메타데이터 적재 | 모델 202개의 메타데이터를 읽어 템플릿(`config/index_text_template.ko.txt`)으로 모델당 색인 텍스트 1개를 만든다. 모델 카드를 LLM으로 요약한 소개 요약(v0.2)을 함께 넣는다 | `data_prep/items.py`, `data_prep/index_text.py`, `data_prep/summaries.py` / 사이드바 선택 모델 카드 | 구현 (202개 로드, 색인 텍스트에 소개 요약 포함) |
| F2002 | 색인 | 메타데이터 색인 (RAG 1) | `items` 컬렉션에 모델당 1청크를 색인한다. ID `item:{model_id}`가 고정이라 다시 색인하면 덮어쓴다. 색인 수를 사이드바에 보여 준다 | `data_prep/indexing.py`, `vectorstore/store.py` / 사이드바 색인 수 | 구현 (items 202청크, 두 번 실행해도 그대로) |
| F2003 | 프롬프트 | 검색어 추출 (프롬프트 1) | 질문에서 모델 카드 검색용 영어 문구(`card_query_en`)와 카드 밖 배경 문서(위키백과) 검색어 0~3개를 뽑는다. 첫 위키 검색어는 항상 모델 계열명이다. 구조화 출력이며, 같은 모델·질문이면 저장해 둔 검색어를 다시 쓴다 | `data_prep/wiki.py`, `prompts/ko/query_extract.txt` / 질의응답 진행 상태 | 구현 |
| F2004 | 수집 | 외부 문서 수집 (프롬프트 2) | 모델 카드(항목 자체 문서)는 선별 없이 항상 색인한다. 위키 후보는 제목·요약만 보고 선별한 뒤 본문을 수집하고, 선택·제외 이유를 기록한다. 이미 수집한 검색어는 다시 수집하지 않는다 | `data_prep/cards.py`, `data_prep/wiki.py`, `prompts/ko/doc_select.txt` / 진행 상태의 "수집된 위키 문서" | 구현 |
| F2005 | 색인 | 외부 문서 색인 (RAG 2) | `docs` 컬렉션에 색인한다. 마크다운 소제목으로 먼저 나눈 뒤 1,000자/중복 200자(설정값)로 분할한다. 청크 ID `{model_id}:{doc_id}:{chunk_index}` | `vectorstore/chunking.py`, `vectorstore/docs_index.py` / 사이드바 문서 청크 수 | 구현 (카드 4,667청크, 청크 설정을 바꾸면 청크 수가 바뀜) |
| F2006 | 검색 | 근거 검색 및 병합 | 선택 모델의 항목 청크를 항상 [근거 1]로 두고, `docs`에서 `model_id` 필터를 걸어 출처별로 따로 검색한다 (항목 1 + 카드 6 + 위키 2, 2026-10-23에 카드 4 → 6). 청크 ID로 중복을 없애고 번호를 붙인다 | `rag/graph.py` (retrieve), `rag/evidence.py` / 질의응답 | 구현 (Top-k를 바꾸면 근거 목록이 바뀜) |
| F2007 | 생성 | 근거 기반 답변 생성 (프롬프트 3) | LangGraph retrieve → generate 2노드. 근거만으로 답하고, 근거가 없으면 "제공된 문서에서 확인되지 않습니다."라고 답한다. 출처 종류(항목 메타데이터/모델 카드/위키백과)를 구분한다 | `rag/graph.py` (generate), `prompts/ko/answer.txt` / 질의응답 (스트리밍) | 구현 |
| F2008 | 생성 | 근거 표시 | 답변의 `[근거 n]`을 찾아 실제로 인용한 근거만 제목·원문 URL과 함께 보여 준다. 인용이 없으면 안내한다 | `rag/evidence.py`, `ui/components.py` / "답변에 사용한 근거", 웹 근거 목록 | 구현 (인용 없음 안내는 합성 입력 테스트로 확인) |
| F2009 | UI | 항목 선택 및 질의응답 | 사이드바에서 모델을 검색·선택하고, 모델별로 대화 기록을 나눠 유지한다 | `app.py`, `web/static/index.html` | 구현 |
| F2010 | 서비스 | 사용 조건 점검표 (도메인 특화 기능) | 라이선스·승인 절차·지원 언어·컨텍스트·모달리티·용도·제한 7항목을 근거 번호와 함께 표로 보여 준다. 근거는 항목 1 + 카드 최대 8, 면책 문구를 함께 표시한다 | `services/usage_check.py`, `prompts/ko/usage_check.txt` / 사용 조건 점검표 탭 | 구현 |
| F2011 | 서비스 | 조건 기반 항목 탐색 | 자연어 조건을 필터·정렬로 바꾸고(구조화 출력), 메타데이터 필터 + 의미 검색으로 후보를 모은 뒤 LLM이 조건에 맞는 모델만 고른다. 결과 카드를 누르면 그 모델 대화로 이동한다. "많이 쓰는" = 30일 다운로드 정렬 | `services/condition_search.py`, `prompts/ko/condition_parse.txt`·`condition_select.txt` / `pages/1_조건_탐색.py`, `web/static/explore.html` | 구현 |
| F2012 | UI | 진행 상태 및 안내 | 단계별 진행 표시, API 키 없음·색인 없음·결과 없음·인용 없음 안내, 라이선스 면책 문구 | `app.py`, `ui/components.py`, `i18n/ko.json` / 질의응답 탭·사이드바 | 구현 |

### 2.2 확장 기능

| 번호 | 이름 | 설명 | 구현 위치 | 상태 |
|---|---|---|---|---|
| F2013 | 웹 프론트엔드 | Streamlit은 그대로 두고 HTML/CSS/JS 화면을 추가했다. 질의응답(스트리밍·근거 목록), 사용 조건 점검표, 조건 탐색, 리서치(준비 중 안내). 다크 모드·좁은 화면 대응 | `web/api.py`(FastAPI), `web/static/` / 화면: [web-chat.png](screenshots/web-chat.png), [web-usage-check.png](screenshots/web-usage-check.png), [web-explore.png](screenshots/web-explore.png) | 구현 (2026-10-23 첫 시안) |
| F2014 | MMR 검색 | 설정 `retrieve.search_type=mmr`이면 출처별로 후보 30개(`mmr_fetch_k`)에서 k개를 MMR로 고른다. 유사도 검색과 근거 목록을 비교했다 | `vectorstore/store.py` (`search`), `config/settings.json` | 구현 (기본값은 유사도. 평가 세트 적중이 MMR 72/99, 유사도 90/99) |
| F2015 | RAG 전후 품질 비교 | 대표 질문 5개를 RAG 없이/RAG로 답하게 해 비교하고, 답변 모델(gpt-5.4-nano / claude-haiku-5-5 / claude-sonnet-5-5)도 비교했다 | [rag-vs-no-rag.md](rag-vs-no-rag.md) | 완료 |
| F2016 | 여러 문서 출처 결합 | 모델 카드와 위키백과를 `docs` 컬렉션에 `doc_type`으로 구분해 색인하고, 근거에 출처 종류를 표시한다 | `vectorstore/docs_index.py`, `rag/evidence.py` / 근거 목록 출처 배지 | 구현 |

### 2.3 추가 기능

| 번호 | 이름 | 설명 | 구현 위치 |
|---|---|---|---|
| A-01 | 카드 즉석 수집 | 아직 색인되지 않은 모델에 질문하면 그 모델 카드를 즉석에서 수집·색인한다 (멱등) | `data_prep/indexing.py` `ensure_card_indexed`, `rag/graph.py` |
| A-02 | 인기도 기반 탐색 | "많이 쓰이는 모델" 조건을 30일 다운로드 정렬로 처리한다. 인기도가 성능 지표가 아님을 명시한다 | `services/condition_search.py` |
| A-03 | 지역·언어 확장 설계 | 데이터에는 코드값만 저장하고, 표시 문구·프롬프트·면책 문구는 언어별 파일로 둔다 | `i18n/`, `prompts/ko/`, `config/labels.ko.json` |
| A-04 | 제공사 독립 | LLM은 작업별 설정 키(`LLM_SUMMARY`, `LLM_SMALL`, `LLM_ANSWER`)로 제공사·모델을 고르고, 임베딩은 로컬 모델(BAAI/bge-m3)을 쓴다. 초기 개발 단계의 API 프록시에서 Anthropic API 직접 호출로 코드 수정 없이 옮겼다 | `config/llm.json`, `common/llm.py`, `vectorstore/embeddings.py` |
| A-05 | 값의 출처 표시 | 컨텍스트 길이 등은 출처(`config.json` / 라이브러리 기본값 / 해당 없음)를 함께 저장하고 보여 준다 | `scripts/enrich.py` (`context_source`), `data_prep/index_text.py` |

### 2.4 로드맵 (아직 구현하지 않음)

- 리서치: 여러 모델 비교 리포트, 리서치 노트 저장·내보내기, 메타데이터 트렌드 대시보드. 지금은 `pages/2_리서치.py`와 `web/static/research.html`에 준비 중 안내만 있다. 기본 질의응답은 "모델 하나로 검색 범위를 좁히는" 구조라 리서치는 별도 모듈로 둔다.

## 3. 비기능 요구사항

| 번호 | 분류 | 이름 | 구현 방안 |
|---|---|---|---|
| NF2001 | 성능 | 응답 시간 | 모델 카드를 미리 일괄 색인해 질문할 때의 수집 지연을 없앤다. 가벼운 작업(검색어 추출·선별)은 소형 작업 키(`LLM_SMALL`)로 돌린다. 측정: [performance.md](performance.md) |
| NF2002 | 성능 | 수집 캐시 | 카드: 모델·리비전 단위로 색인 상태를 기록한다. 위키: 수집한 검색어를 기록해 다시 수집하지 않는다 (선별 0건이고 선별 모델이나 프롬프트 버전이 바뀐 경우만 다시 선별) |
| NF2003 | 보안 | API 키 관리 | `.env`(`ANTHROPIC_API_KEY`, `HF_TOKEN`, `WIKI_CONTACT`)로 관리하고 `.gitignore`로 제외한다. `.env.example`에는 이름만 둔다 |
| NF2004 | 보안 | 내부 정보 비노출 | 화면에는 짧은 안내만 보이고 상세 오류는 `logs/app.log`에 남긴다. 프롬프트 전문과 키는 화면·API 응답에 넣지 않는다 |
| NF2005 | 확장성 | 모듈 분리 | 데이터 준비(`data_prep/`) / Vector Store(`vectorstore/`) / RAG 파이프라인(`rag/`) / 서비스 기능(`services/`) / UI(`app.py`, `ui/`, `web/`)를 나눈다. 도메인 의존 코드는 데이터 준비 영역에 둔다 |
| NF2006 | 품질 | 외부 API 예절 | 요청 간격을 두고, 재시도는 최대 3회, 식별 가능한 User-Agent를 쓴다 (위키백과는 연락처 포함) |
| NF2007 | 법·윤리 | 출처와 이용 조건 | README의 출처와 이용 조건, [domain.md](../design/domain.md)에 기록한다. 청크마다 원문 URL·리비전을 저장하고, 근거는 발췌와 링크로만 보여 준다 |

구조와 흐름: [architecture.md](architecture.md)
