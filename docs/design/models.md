# 모델 선택

- 상태: 확정
- 최종 수정일: 2026-10-25
- 관련 문서: [prompts.md](prompts.md), [decisions.md](decisions.md), [retrieval-and-ui.md](retrieval-and-ui.md), [rag-vs-no-rag.md](../reports/rag-vs-no-rag.md), [evaluation.md](../reports/evaluation.md)

## 요약

- LLM은 Anthropic API 직접 호출(`anthropic_direct`, `config/llm.json`)로, 개인 크레딧으로 운영한다: `LLM_SUMMARY` = `claude-sonnet-5-5`, `LLM_SMALL` = `LLM_ANSWER` = `claude-haiku-5-5`.
- 답변 모델이 Haiku인 이유: F2015 비교에서 Haiku·Sonnet 모두 5개 질문 정답이었고, 호출당 비용은 Sonnet이 Haiku의 약 27배다.
- 임베딩은 로컬 `BAAI/bge-m3` (한국어 질문 ↔ 영어 문서 교차 검색, CPU 처리).
- 구조화 출력 방식은 모델별 설정이다. Sonnet은 강제 도구 호출 미지원 경고 때문에 `json_schema`를 쓴다. 파싱 실패 시 1회 재시도.
- 제공사·모델은 작업별 설정 키로 고르고, 프롬프트에 특정 모델 전용 기법을 쓰지 않는다.

## 전제
- 개인 Anthropic API 크레딧(약 $100)으로 운영한다.

## 원칙
- 특정 회사 API에 묶이지 않는다. 작업별 설정 키로 제공사·모델 선택, LangChain 추상화, `with_structured_output`.
- 프롬프트에 특정 모델 전용 기법을 쓰지 않는다.

## 임베딩: 로컬
- 1순위 `BAAI/bge-m3`, 대안 `intfloat/multilingual-e5-large`/`-small`.
- 요구: 한국어 질문 ↔ 영어 문서 교차 검색, CPU로 수천 청크 처리.
- 추가 의존성: `sentence-transformers`, PyTorch.
- 품질 확인: 대표 질문 10~20개 + 정답 청크로 상위 k 적중률 비교. 모델명은 설정값.

## LLM 배정

현재 기본 프로필은 `anthropic_direct`(Anthropic API 직접 호출)다.

| 작업 | 설정 키 | 현재 (`anthropic_direct`) |
|---|---|---|
| 모델 소개 요약 (1회성) | `LLM_SUMMARY` | `claude-sonnet-5-5` |
| 검색어 추출, 후보 선별, 조건 변환·선별 | `LLM_SMALL` | `claude-haiku-5-5` |
| 답변 생성, 사용 조건 점검표 | `LLM_ANSWER` | `claude-haiku-5-5` |

- `LLM_SMALL` = `claude-haiku-5-5`: 확인 결과 조건 탐색(C2) 결과가 다운로드 상위 5개와 순서까지 일치했고, 위키 선별(P2)도 정상적으로 문서를 골랐다 (nano에서 보인 누락·0건 문제 해소).
- `LLM_ANSWER` = `claude-haiku-5-5`: F2015 비교(같은 근거, 질문 5개): Haiku 5개 모두 정답 / Sonnet 5개 모두 정답, 호출당 비용은 Haiku의 약 27배 / nano 부분 오답 2건. Sonnet은 품질 이득 대비 운영 비용이 지나치게 크다.

## 구조화 출력 방식
- Claude는 Anthropic Messages API(헤더 `x-api-key`)로 호출한다. 모델 ID: `claude-sonnet-5-5`, `claude-haiku-5-5`.
- `claude-sonnet-5-5`는 강제 도구 호출 방식을 지원하지 않는다는 경고가 확인됐다. 구조화 출력 방식(`function_calling` / `json_schema`)은 **모델별 설정(`config/llm.json`)**으로 두고, Sonnet은 `json_schema`를 쓴다.
- 파싱 실패 시 1회 재시도 후 실패로 기록하고 다음 항목으로 넘어간다 (재실행 시 실패분만 다시 처리).

## 프롬프트 기법 방침
- F2003의 "도메인 전문가 역할"은 빈 페르소나가 아니라 구체적 작업 맥락으로 쓴다.
- 구조화 출력은 API 차원에서 강제. 근거는 번호·출처 종류가 붙은 블록으로. 선별 프롬프트는 이유 필드를 받는다.
- few-shot은 추출·변환 작업에 집중. **예시는 가상 모델명만.**
- 프롬프트 본문: [prompts.md](prompts.md)
