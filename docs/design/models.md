# 모델 선택 (2026-10-22)

## 전제
- 초기 개발 단계(2026-10-23까지)에는 API 프록시를 거쳐 주요 3사 모델 대부분을 쓸 수 있었다. 사용량 한도가 정해져 있었고 기간이 끝나면 쓸 수 없었다.
- 이후에는 개인 Anthropic API 크레딧(약 $100)으로 운영한다.

## 원칙
- 특정 회사 API에 묶이지 않는다. 작업별 설정 키로 제공사·모델 선택, LangChain 추상화, `with_structured_output`.
- 프롬프트에 특정 모델 전용 기법을 쓰지 않는다.

## 임베딩: 로컬 (확정)
- 1순위 `BAAI/bge-m3`, 대안 `intfloat/multilingual-e5-large`/`-small`.
- 요구: 한국어 질문 ↔ 영어 문서 교차 검색, CPU로 수천 청크 처리.
- 추가 의존성: `sentence-transformers`, PyTorch.
- 품질 확인: 대표 질문 10~20개 + 정답 청크로 상위 k 적중률 비교. 모델명은 설정값.

## LLM 배정 (확정)

현재 기본 프로필은 `anthropic_direct`(Anthropic API 직접 호출)다.

| 작업 | 설정 키 | 현재 (`anthropic_direct`) | 초기 API 프록시 단계 |
|---|---|---|---|
| 모델 소개 요약 (1회성) | `LLM_SUMMARY` | `claude-sonnet-5-5` | Claude Sonnet급 (프록시 사용 기간 안에 실행) |
| 검색어 추출, 후보 선별, 조건 변환·선별 | `LLM_SMALL` | `claude-haiku-5-5` | gpt-5.4-nano |
| 답변 생성, 사용 조건 점검표 | `LLM_ANSWER` | `claude-haiku-5-5` | Claude Haiku급 |

- 답변 생성 모델은 프록시 사용을 마친 뒤의 운영 모델과 맞추기 위해 Claude 계열로 정했다. nano / Haiku / Sonnet 답변 비교를 해 보고 최종 결정했다 (F2015 재료).
- **2026-10-23 API 프록시 사용을 마치고 Anthropic API 직접 호출(`anthropic_direct`)로 전환했다.** `LLM_SUMMARY` = `claude-sonnet-5-5`, `LLM_SMALL` = `LLM_ANSWER` = `claude-haiku-5-5`. 전환 전 Haiku 확인: 조건 탐색(C2) 결과가 다운로드 상위 5개와 순서까지 일치했고, 위키 선별(P2)도 정상적으로 문서를 골랐다 (nano에서 보인 누락·0건 문제 해소).
- **`LLM_ANSWER` = `claude-haiku-5-5`로 확정 (2026-10-22).** F2015 비교(같은 근거, 질문 5개): Haiku 5개 모두 정답 / Sonnet 5개 모두 정답, 호출당 비용은 Haiku의 약 27배 / nano 부분 오답 2건. Sonnet은 품질 이득 대비 운영 비용이 지나치게 크다.

## 구조화 출력 방식 (2026-10-22 추가)
- Claude는 Anthropic Messages API(헤더 `x-api-key`)로 호출한다. 모델 ID: `claude-sonnet-5-5`, `claude-haiku-5-5`. 초기 API 프록시 단계에서도 같은 Messages API 형식을 썼다.
- `claude-sonnet-5-5`는 강제 도구 호출 방식을 지원하지 않는다는 경고가 확인됐다. 구조화 출력 방식(`function_calling` / `json_schema`)은 **모델별 설정(`config/llm.json`)**으로 두고, Sonnet은 `json_schema`를 쓴다.
- 파싱 실패 시 1회 재시도 후 실패로 기록하고 다음 항목으로 넘어간다 (재실행 시 실패분만 다시 처리).

## 프롬프트 기법 방침
- F2003의 "도메인 전문가 역할"은 빈 페르소나가 아니라 구체적 작업 맥락으로 쓴다.
- 구조화 출력은 API 차원에서 강제. 근거는 번호·출처 종류가 붙은 블록으로. 선별 프롬프트는 이유 필드를 받는다.
- few-shot은 추출·변환 작업에 집중. **예시는 가상 모델명만.**
- 프롬프트 본문: [prompts.md](prompts.md)
