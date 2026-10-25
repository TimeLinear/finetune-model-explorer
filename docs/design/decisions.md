# 결정 기록

> 이 프로젝트의 설계 결정을 날짜순으로 쌓는다. 현재 규칙은 각 설계 문서에 있고, 여기에는 왜·언제 그렇게 정했는지와 바뀐 과정을 남긴다.
> 항목 형식: 배경 / 결정 / 영향 / 관련. 바뀐 결정은 지우지 않고 "→ YYYY-MM-DD 항목으로 대체"를 붙인다. 날짜를 기록에서 찾지 못한 항목은 문서 날짜로 추정하고 "(추정)"을 붙였다.

## 2026-10-21 도메인: 파인튜닝용 오픈 웨이트 언어 모델 (D-04)
- 배경: 근거 없이 답하면 틀리거나 위험해지는 질문이 많고, 항목마다 연결되는 외부 문서와 기계 판독 메타데이터가 있는 도메인이 필요했다.
- 결정: 파인튜닝할 중간 규모 오픈 웨이트 언어 모델을 고르는 사람을 위한 서비스. 공식 조직 계정만, 전체 파라미터 1~24B, 베이스+인스트럭트, 한국 모델·멀티모달·특수 목적 모델 포함.
- 영향: 항목 = Hugging Face 모델 저장소, 주 문서 = 모델 카드.
- 관련: [domain.md](domain.md)

## 2026-10-21 항목 목록 스냅샷 고정 (D-05·D-06)
- 배경: 다운로드 순위가 매일 바뀌어 개발 중 목록이 흔들리면 검증이 어렵다.
- 결정: `data/items_20261021.json`(202개, 2026-10-21 스냅샷)으로 고정한다. 이 파일은 수정하지 않고 보강 결과는 별도 파일에 저장한다.
- 영향: 갱신 기능 전까지 목록은 고정.
- 관련: [domain.md](domain.md), [data-refresh.md](data-refresh.md)

## 2026-10-21 (추정) 항목 설계 원칙 (D-07)
- 배경: 항목 데이터에 추정·판정이 섞이면 근거 없는 판단이 데이터처럼 굳는다.
- 결정:
  - 아키텍처·컨텍스트 길이는 기계 판독 출처만 쓴다 (`context_source`로 출처 표시: `config.json` / `library_default` / `not_applicable`).
  - 모델 소개 요약은 카드 기반 LLM 요약이며 `card_url`, `card_revision`, 생성 일시, 생성 모델명을 반드시 함께 저장한다.
  - "상업적 이용 가능 여부" 판정은 저장하지 않고 질문 시점에 원문 근거로만 답한다.
  - 항목 ID = Hugging Face 저장소 ID (`조직/모델명`). 바꾸지 않는다.
  - 필드 목록은 코드에 박지 않고 스키마·설정으로 관리한다 (NF2005).
  - 이름 규칙으로 추정한 값은 `stage_needs_review`, `modality_needs_review`로 표시한다.
- 영향: 항목 필드 구성, 소개 요약 저장 형식.
- 관련: [index-text.md](index-text.md), [collections.md](collections.md)

## 2026-10-21 (추정) 지역·언어 확장 원칙 (D-08)
- 배경: 지금은 한국 기준이지만 한국 기준을 빼거나 다국어로 넓힐 수 있어야 한다.
- 결정:
  1. 데이터에는 코드값만 (국가 ISO 3166, 언어 ISO 639, 분야 영문 코드). 표시 이름은 언어별 라벨 파일.
  2. "우선 지역"은 설정값.
  3. "한국어 지원 여부" 같은 판단은 저장하지 않고 계산.
  4. 생성 텍스트는 언어 코드를 키로 저장 (예: `summary.ko`).
  5. 색인 텍스트 언어(`INDEX_LANG`), 프롬프트 응답 언어, UI 문구, 면책 문구는 언어별 파일·설정.
  6. 청크 메타데이터에 `doc_lang`.
  7. 날짜는 ISO 형식으로 저장, 표시 형식은 화면에서.
- 영향: 라벨 파일·i18n 파일 분리, 청크 메타데이터 필드.
- 관련: [index-text.md](index-text.md), [collections.md](collections.md)

## 2026-10-21 (추정) 목록 갱신 정책 방향 (O-06) → 2026-10-25 항목으로 대체
- 배경: 자주 갱신하면 "어제 검토하던 모델이 오늘 목록에서 사라지는" 일이 생긴다.
- 결정: MVP는 스냅샷 고정. 최종 방향은 진입·퇴출 기준 분리 + 사용 중 모델 보존, 퇴출은 삭제가 아니라 `status=archived`. 갱신 주기는 월 단위로 잡았다. MVP에서는 구현하지 않는다.
- 영향: 갱신 대비 필드(`status`, `first_seen`, `last_qualified`, `snapshot_date`)만 미리 넣음.
- 관련: [data-refresh.md](data-refresh.md)

## 2026-10-21 (추정) 개발 단계와 범위 (D-01·D-03)
- 배경: 기본 질의응답과 리서치 기능을 함께 만들면 기본 기능 검증(근거 번호 일치, "확인되지 않음" 응답 등)이 흐려진다.
- 결정: 1단계(F2001~F2012) 완성 전에는 2단계(리서치)에 착수하지 않는다. 확장 기능은 F2016(출처 결합), F2014(MMR). 리서치 주제는 도메인 맞춤 파인튜닝 후보 선별 + 근거 제시 (최적 모델 판정은 하지 않음).
- 영향: 리서치 기능은 로드맵으로.
- 관련: [features.md](../reports/features.md), [backlog.md](backlog.md)

## 2026-10-22 리서치 기능은 별도 모듈·별도 페이지 (D-02, O-01)
- 배경: 리서치 기능 UI 위치를 정해야 했다.
- 결정: 전용 페이지로 둔다. 기본 질의응답 파이프라인은 리서치 기능 변경에 영향받지 않아야 한다.
- 영향: `pages/2_리서치.py`, `research.html` 자리만 둠.
- 관련: [retrieval-and-ui.md](retrieval-and-ui.md)

## 2026-10-22 (추정) 임베딩은 로컬 모델
- 배경: 한국어 질문 ↔ 영어 문서 교차 검색과 CPU로 수천 청크 처리가 필요했다. 초기 API 프록시는 기간이 정해져 있었고, Anthropic은 임베딩 API가 없다.
- 결정: 로컬 임베딩, 1순위 `BAAI/bge-m3`, 대안 `intfloat/multilingual-e5-large`/`-small`.
- 영향: `sentence-transformers`, PyTorch 의존성 추가.
- 관련: [models.md](models.md)

## 2026-10-22 (추정) LLM 호출 구조
- 배경: 개발 중 제공사·모델이 바뀔 수 있었다.
- 결정: LLM은 작업별 설정 키(`LLM_SUMMARY`, `LLM_SMALL`, `LLM_ANSWER`)로 제공사·모델을 고르고 모델 이름을 코드에 넣지 않는다. LangChain 채팅 모델 추상화 + `with_structured_output` (GPT·Claude 공통).
- 영향: `config/llm.json`, `common/llm.py`.
- 관련: [models.md](models.md)

## 2026-10-22 (추정) 초기 개발 단계 LLM 배정 (API 프록시) → 2026-10-23 항목으로 대체
- 배경: 초기 개발 단계(2026-10-23까지)에는 OpenAI 호환 API 프록시를 거쳐 주요 3사 모델 대부분을 쓸 수 있었다. 사용량 한도가 정해져 있었고 기간이 끝나면 쓸 수 없었다. 이후에는 개인 Anthropic API 크레딧(약 $100)으로 운영할 예정이었다.
- 결정: `LLM_SUMMARY` = Claude Sonnet급 (프록시 사용 기간 안에 실행), `LLM_SMALL` = gpt-5.4-nano, `LLM_ANSWER` = Claude Haiku급. 답변 생성 모델은 프록시 사용을 마친 뒤의 운영 모델과 맞추기 위해 Claude 계열로 정하고, nano / Haiku / Sonnet 답변을 비교해 최종 결정하기로 했다 (F2015 재료). 프록시 단계에서도 Claude는 같은 Messages API 형식을 썼다.
- 영향: 모델 소개 요약 202개를 프록시 사용 기간 안에 Sonnet급으로 생성했다.
- 관련: [models.md](models.md), [prompts.md](prompts.md)

## 2026-10-22 구조화 출력 방식을 모델별 설정으로
- 배경: `claude-sonnet-5-5`는 강제 도구 호출 방식을 지원하지 않는다는 경고가 확인됐다.
- 결정: 구조화 출력 방식(`function_calling` / `json_schema`)을 모델별 설정(`config/llm.json`)으로 두고 Sonnet은 `json_schema`를 쓴다. 파싱 실패 시 1회 재시도 후 실패로 기록하고 다음 항목으로 넘어간다.
- 영향: 프로필을 바꿔도 같은 규칙 적용.
- 관련: [models.md](models.md)

## 2026-10-22 (추정) 프롬프트 v0.2: 요약 프롬프트 S 규칙 추가
- 배경: 샘플 3건 결과를 반영해야 했다.
- 결정: 요약 프롬프트 S에 벤치마크 나열 제한(규칙 2), highlights 길이 규칙(규칙 7)을 추가했다.
- 영향: S 버전 v0.2 (`data_prep/summaries.py` `PROMPT_VERSION = "v0.2"`, v0.1 샘플을 대체).
- 관련: [prompts.md](prompts.md)

## 2026-10-22 (추정) 프롬프트 v0.3: P1 card_query_en 추가, P2 주석 이동, U 근거 개수 명확화
- 배경: 카드 검색용 영어 문구가 필요했고, P2 설명 주석과 U 근거 개수 표기를 정리해야 했다.
- 결정: P1에 카드 검색용 영어 문구(`card_query_en`)를 추가, P2 설명 주석을 프롬프트 밖으로 이동, U 근거 개수를 명확화했다.
- 영향: P1·P2·U 버전 v0.3 (`data_prep/wiki.py` `P1_PROMPT_VERSION`·`P2_PROMPT_VERSION = "v0.3"`).
- 관련: [prompts.md](prompts.md), [collections.md](collections.md)

## 2026-10-22 답변 생성 모델 `claude-haiku-5-5`
- 배경: 답변 생성 모델을 nano / Haiku / Sonnet 중에서 골라야 했다.
- 결정: `LLM_ANSWER` = `claude-haiku-5-5`. F2015 비교(같은 근거, 질문 5개): Haiku 5개 모두 정답 / Sonnet 5개 모두 정답, 호출당 비용은 Haiku의 약 27배 / nano 부분 오답 2건. Sonnet은 품질 이득 대비 운영 비용이 지나치게 크다.
- 영향: 프록시 단계의 "Claude Haiku급" 배정을 확정 모델로 바꿈.
- 관련: [models.md](models.md), [rag-vs-no-rag.md](../reports/rag-vs-no-rag.md)

## 2026-10-22 docs 검색을 출처별로 분리
- 배경: 한 컬렉션(`docs`)에서 카드와 위키를 한국어 질문 하나로 함께 검색하면 한국어 위키 청크와 유사도가 높게 나와, 영어 카드 청크가 근거에서 모두 밀려났다 (kanana 질문: 항목 1 + 위키 5, 카드 0).
- 결정: `doc_type=model_card`에서 `retrieve.card_k`(당시 4)개, `doc_type=wiki`에서 `retrieve.wiki_k`(2)개를 따로 검색해 합친다. 카드 검색에는 P1이 만든 영어 검색 문구(`card_query_en`)를 쓴다. 위키가 모자라도 카드로 채우지 않는다.
- 영향: 함께 검색하던 방식을 대체. 컬렉션 구성(`docs` 하나 + `doc_type`)은 그대로. `card_k` 값은 → 2026-10-23 항목으로 대체.
- 관련: [collections.md](collections.md), [retrieval-and-ui.md](retrieval-and-ui.md), [architecture.md](../reports/architecture.md)

## 2026-10-22 카드 머리말 색인
- 배경: Llama 3.2 Vision의 EU 이용 제한처럼 중요한 이용 조건이 카드 본문이 아니라 머리말(`extra_gated_prompt`)에만 있는 경우가 확인됐다 (F2015 질문 4).
- 결정: 머리말(YAML front matter)에서 정해 둔 키(설정 `card.front_matter_keys`)만 읽기 쉬운 텍스트로 바꿔 `section="front_matter"` 문서 조각으로 색인한다. `model-index`, `widget`, `tags`는 제외.
- 영향: 카드 색인 대상에 머리말 추가.
- 관련: [collections.md](collections.md)

## 2026-10-22 가치가 낮은 카드 섹션 제외 (잠정)
- 배경: 분리 검색 후 kanana 질문에서 카드 근거 4개가 Instruct Model Evaluation / Citation / Table of Contents / Contributors로 채워졌다.
- 결정: 소제목이 Citation, BibTeX, Contributors, Acknowledgement(s), Table of Contents, Contact인 섹션(설정 `chunk.exclude_sections`, 대소문자 무시 부분 일치)을 색인에서 뺀다. 카드 파일은 그대로 둔다.
- 영향: 해당 섹션 청크가 검색 대상에서 빠짐.
- 관련: [collections.md](collections.md)

## 2026-10-22 색인 규칙 버전
- 배경: 청킹·머리말 규칙이 바뀌면 같은 카드 리비전이어도 다시 색인해야 한다.
- 결정: 색인 상태 기록에 `index_version`을 두고, 건너뛰기 기준을 `model_id` + `card_revision` + `index_version`으로 한다 (설정 `index.version`).
- 영향: 건너뛰기 기준이 카드 리비전만에서 규칙 버전까지로 넓어짐.
- 관련: [collections.md](collections.md)

## 2026-10-22 (추정) 한국어 위키백과를 보조 출처로 (F2016)
- 배경: 개념·계열 설명용 보조 출처로 한국어 위키백과를 F2016(여러 문서 출처 결합) 후보로 두었다.
- 결정: F2016으로 구현해 한국어 위키백과를 보조 출처로 쓴다.
- 영향: 근거 목록에 출처 종류 구분 표시.
- 관련: [domain.md](domain.md), [evaluation.md](../reports/evaluation.md)

## 2026-10-22 (추정) 소개 요약을 넣은 색인 텍스트 최종 형태 확인
- 배경: 템플릿을 소개 요약 생성 전에 만들어, 요약을 넣은 최종 형태 확인이 남아 있었다.
- 결정: 요약(v0.2)이 들어간 색인 텍스트를 렌더링해 확인했다 (계열·버전, 베이스 모델 줄은 값이 없어 규칙대로 빠짐).
- 영향: 템플릿 확정.
- 관련: [index-text.md](index-text.md), [evaluation.md](../reports/evaluation.md)

## 2026-10-22 저장소에 올리는 데이터 범위
- 배경: 모델 카드와 색인을 저장소에 올리면 라이선스 동의 절차를 우회해 재배포하는 셈이 될 수 있었다.
- 결정:
  - 모델 카드 원문(`data/cards/`)과 Chroma 색인 폴더는 저장소에 올리지 않는다. 게이트 저장소 카드는 라이선스 동의를 거쳐야 볼 수 있는 내용이고, 공개 카드도 저작권은 올린 조직에 있으며 이용 허락은 Hugging Face 서비스를 통한 이용 범위다. Chroma 색인에도 카드 본문 청크가 들어 있다.
  - 재현성은 "리비전 고정 + 다시 받기"로 보장한다. `data/cards/_manifest.json`(모델 ID, 카드 리비전, URL, 본문 해시, 길이)은 올리고, `scripts/fetch_cards.py`가 같은 리비전의 카드를 받아 해시로 동일성을 확인한다 (게이트 모델은 각자 라이선스 동의 필요).
  - 모델 소개 요약(`data/summaries.jsonl`)은 올린다. 짧은 파생 텍스트이고, 카드 URL·리비전으로 출처를 남기며, 다시 만들려면 202개 전체를 다시 요약해야 하기 때문이다.
  - `logs/`는 올리지 않는다.
- 영향: `.gitignore`.
- 관련: [README](../../README.md)의 데이터 출처와 이용 조건

## 2026-10-22 화면 개발 순서
- 배경: Streamlit 화면과 직접 구현한 웹 화면(F2013)의 순서를 정해야 했다.
- 결정: MVP 화면은 Streamlit으로 완성·검증한다. F2013(HTML/CSS/JS + FastAPI)은 Streamlit을 대체하지 않고 추가하며, 기본 기능 검증과 F2015를 마친 뒤 착수한다.
- 영향: Streamlit과 웹 화면이 같은 모듈을 쓰는 구조.
- 관련: [retrieval-and-ui.md](retrieval-and-ui.md)

## 2026-10-22 웹 화면 디자인은 시안을 먼저 만든다 → 2026-10-23 항목으로 대체
- 배경: 웹 화면 디자인 진행 방식을 정해야 했다.
- 결정: 디자인 시안을 먼저 만든 뒤 구현한다.
- 영향: (대체됨)
- 관련: [retrieval-and-ui.md](retrieval-and-ui.md)

## 2026-10-22 highlights 표시 규칙
- 배경: LLM이 만든 highlights 문구의 길이를 화면에서 어떻게 다룰지 정해야 했다.
- 결정: 데이터는 원문 그대로 저장하고 화면에서만 CSS 말줄임 + `title` 툴팁으로 처리한다. 사이드바 요약 카드에는 "전체 보기" 접기 영역. HTML 이스케이프.
- 영향: `ui/components.py`, 웹 화면 같은 규칙.
- 관련: [retrieval-and-ui.md](retrieval-and-ui.md)

## 2026-10-23 선별 0건 위키 검색어 재수집
- 배경: 같은 검색어는 다시 수집하지 않는 규칙(NF2002) 때문에, 선별 결과가 0건이었던 검색어도 선별 모델이 바뀐 뒤 다시 수집되지 않았다.
- 결정: 선별 결과가 0건이었던 검색어는 선별 모델이나 P2 프롬프트 버전이 바뀌면 다시 수집한다.
- 영향: NF2002 재수집 방지 규칙에 예외 추가.
- 관련: [collections.md](collections.md), [architecture.md](../reports/architecture.md)

## 2026-10-23 카드 검색 보강 후보 (a) RRF, (b) 청크 머리 정보, (c) 둘 다 미채택
- 배경: 카드 검색이 P1 문구 하나에 좌우되는 문제를 줄이려고 평가 세트(`tests/retrieval_eval/`, 33사례 × 표현 3개)로 보강안을 비교했다.
- 결정: 채택 규칙을 실험 전에 정했다 — 안정성(같은 뜻의 표현 3개 모두 적중)이 가장 높은 후보를 고르되, 기준선에서 맞히던 질의가 하나라도 놓침으로 바뀌면 제외하고, 동률이면 바꾸는 것이 적은 쪽(a < b < c), 기준선보다 나은 후보가 없으면 채택하지 않는다. 세 후보 모두 기준선에서 맞히던 질의를 놓치게 만들어 채택하지 않았다. 설정(`retrieve.card_query_mode`, `index.chunk_header`)은 실험용으로 남긴다. 남은 실패는 P1 문구가 질문의 핵심어를 빠뜨리는 경우(예: "지역 제한" → "regional availability", 정답 조각 24위)로, 프롬프트 쪽에서 다룬다.
- 영향: 카드 검색은 `card_query_en` 단일 질의 유지 (`card_query_mode=single`, `chunk_header=false`).
- 관련: [collections.md](collections.md), [retrieval-and-ui.md](retrieval-and-ui.md), [evaluation.md](../reports/evaluation.md)

## 2026-10-23 retrieve.card_k 4 → 6
- 배경: 평가 세트에서 정답 조각이 5~6위에 걸린 경우가 많았다.
- 결정: `retrieve.card_k`를 4에서 6으로 올렸다. 답변 단위 비교에서 손해가 없었다 (정답 31→33/33, 입력 토큰 +26%, 답변 시간 중앙값 +0.4초).
- 영향: 카드 근거 청크 수 4 → 6. 2026-10-22 "docs 검색을 출처별로 분리"의 `card_k` 값을 대체.
- 관련: [collections.md](collections.md), [retrieval-and-ui.md](retrieval-and-ui.md), [evaluation.md](../reports/evaluation.md)

## 2026-10-23 P1 v0.4 후보 미채택, v0.3 유지
- 배경: "속성어 보존 + license/acceptable use policy 덧붙이기" 규칙을 넣은 P1 v0.4 후보를 검토했다.
- 결정: v0.3 유지. 채택 규칙(실행 전에 정함: v0.4 전체 적중 ≥ v0.3, 사례별 적중이 2회 이상 줄어든 사례 0건)에 못 미쳤다 — Haiku 비교(평가 세트 99개 × 2회, `card_k`=6) 전체 적중 189 → 188, Llama 한계 사례 6 → 4.
- 영향: Haiku는 v0.3에서도 "지역 제한"을 "region restriction"으로 옮겨 Llama EU 조각을 10회 모두 6위 안에서 찾았다. "regional availability" 문제는 nano의 문구였다. 후보 문안: `tests/retrieval_eval/prompt_candidates/query_extract_v04.txt`.
- 관련: [prompts.md](prompts.md), [evaluation.md](../reports/evaluation.md)

## 2026-10-23 프롬프트 v0.4: C2 출력 방식 변경, 구조화 출력 잘림 처리
- 배경: C2 v0.3은 후보 30개 전부에 판정·이유를 써서 Haiku `max_tokens` 2048에서 잘렸다 (화면에는 맞는 후보만 표시하므로 나머지 판정은 쓰이지 않았다).
- 결정: C2를 "맞는 후보만, 최대 `limit`개" 출력으로 바꾸고, 구조화 출력이 잘리면 결과를 쓰지 않고 실패로 처리한다.
- 영향: v0.4 확인 — Haiku 출력 468토큰, 다운로드 상위 5개와 일치. nano는 상위 후보 일부를 건너뛰었으나 `LLM_SMALL`이 Haiku로 바뀌어 그대로 둔다 (실제 전환: 2026-10-23, 아래 "API 프록시 사용 종료" 항목). C2 v0.3(후보마다 판정)을 대체.
- 관련: [prompts-services.md](prompts-services.md), [architecture.md](../reports/architecture.md)

## 2026-10-23 위키 선별(P2) 병렬 실행
- 배경: 성능 조사에서 P2 후보 선별이 처리 시간의 22%를 차지했다.
- 결정: 위키 후보 선별(P2)을 동시에 최대 3개 실행한다 (`wiki.p2_concurrency`=3).
- 영향: 첫 질문당 2.7~9.1초 단축.
- 관련: [retrieval-and-ui.md](retrieval-and-ui.md), [performance.md](../reports/performance.md)

## 2026-10-23 성능 목표 확정과 중앙값 판정
- 배경: 외부 API 응답 속도가 날마다 달라 개별 측정값이 튄다.
- 결정: 성능 목표(웜 15초·콜드 40초 이내)를 확정하고, 판정은 측정값의 중앙값으로 한다. 최댓값은 참고로 함께 기록한다.
- 영향: 이전에 잠정이던 목표를 확정.
- 관련: [retrieval-and-ui.md](retrieval-and-ui.md), [performance.md](../reports/performance.md), [evaluation.md](../reports/evaluation.md)

## 2026-10-23 API 프록시 사용 종료, Anthropic API 직접 호출(`anthropic_direct`)로 전환
- 배경: API 프록시 사용 기간이 끝났다.
- 결정: 기본 프로필을 `anthropic_direct`로 전환한다. `LLM_SUMMARY` = `claude-sonnet-5-5`, `LLM_SMALL` = `LLM_ANSWER` = `claude-haiku-5-5`. 전환 전 Haiku 확인: 조건 탐색(C2) 결과가 다운로드 상위 5개와 순서까지 일치했고, 위키 선별(P2)도 정상적으로 문서를 골랐다 (nano에서 보인 누락·0건 문제 해소). 직접 호출은 개인 크레딧이 들므로 시험 호출도 횟수를 정해서 한다.
- 영향: `LLM_SMALL`이 gpt-5.4-nano에서 `claude-haiku-5-5`로 바뀜 (P1·P2·C1·C2). 필요 네트워크 도메인: `huggingface.co`, `*.hf.co`, `ko.wikipedia.org`, `api.anthropic.com`. `.env` 키: `ANTHROPIC_API_KEY`, `HF_TOKEN`, `WIKI_CONTACT`. 2026-10-22 (추정) "초기 개발 단계 LLM 배정"을 대체.
- 관련: [models.md](models.md), [prompts.md](prompts.md)

## 2026-10-23 웹 화면(F2013) 첫 시안
- 배경: 2026-10-22 결정대로라면 구현 전에 별도 시안 단계가 필요했다.
- 결정: 시안 단계를 따로 두지 않고 구현 결과를 첫 시안으로 삼는다. `web/`(FastAPI + 순수 HTML/CSS/JS, 빌드 도구·CDN 없음)로 질의응답·점검표·조건 탐색·리서치 안내 화면을 만들고 디자인을 한 차례 다듬어 main에 병합했다. 서버는 대화 상태를 갖지 않고 대화 기록은 브라우저에 둔다. 127.0.0.1에만 바인딩. 이후 화면 수정은 이 시안을 기준으로 한다.
- 영향: 2026-10-22 "웹 화면 디자인은 시안을 먼저 만든다"를 대체.
- 관련: [retrieval-and-ui.md](retrieval-and-ui.md), [README](../../README.md)의 웹 화면

## 2026-10-25 공개 저장소 전환
- 배경: 개인 공개 포트폴리오로 전환했다.
- 결정: 새 git 이력으로 시작하고, LLM은 `anthropic_direct` 프로필만 남긴다 (API 프록시 프로필 삭제). 문서는 `docs/design/`(설계)과 `docs/reports/`(결과)로 나눈다.
- 영향: 과거 API 프록시 기록은 "초기 개발 단계의 API 프록시"로 남김.
- 관련: [README](../../README.md)

## 2026-10-25 데이터 갱신 설계
- 배경: 스냅샷 고정 목록을 최신 상태로 유지하면서 검색 품질이 깨지지 않게 해야 한다.
- 결정: 갱신은 주 1회 (설정으로 변경 가능). 진입·퇴출 기준 분리, 보관(`status=archived`), 평가 세트로 교체 판정, 비용 원칙은 [data-refresh.md](data-refresh.md)를 따른다.
- 영향: 2026-10-21 (추정) "목록 갱신 정책 방향 (O-06)"의 월 단위 주기를 대체.
- 관련: [data-refresh.md](data-refresh.md), [backlog.md](backlog.md)

## 2026-10-25 작업 규칙과 커밋 방침
- 배경: 구현을 Claude Code에 맡기므로 작업 범위·비용·커밋 규칙을 저장소에 두어야 했다.
- 결정: 저장소 루트 [CLAUDE.md](../../CLAUDE.md)에 작업 규칙을 둔다. 커밋 메시지의 Co-Authored-By 줄은 유지한다 (AI 협업을 투명하게 밝히는 방침). 커밋 서명은 하지 않는다. 커밋 전 검사(비밀 값, 금지 문자열, 제외 대상 경로)를 한다.
- 영향: 남은 작업은 [backlog.md](backlog.md) 한 곳에서 관리.
- 관련: [CLAUDE.md](../../CLAUDE.md), [backlog.md](backlog.md)

## 2026-10-25 문서 체계
- 배경: 문서가 늘어 필요한 문서를 제때 찾기 어려워졌다.
- 결정: 저장소의 `docs/`를 유일한 기준 문서로 삼는다. [docs/README.md](../README.md)에 문서 지도와 작업별로 읽을 문서를 두고, 설계 문서는 머리 정보(상태, 최종 수정일, 관련 문서)와 요약 다음에 현재 유효한 내용만 둔다. 바뀐 과정은 이 결정 기록에 날짜순으로 쌓는다.
- 영향: 설계 문서의 경과 서술을 이 문서로 옮김. 제목에 붙어 있던 버전·날짜(예: retrieval-and-ui.md "v1.1")는 머리 정보로 대체.
- 관련: [docs/README.md](../README.md)
