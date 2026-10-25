# 문서 지도

저장소의 `docs/`가 이 프로젝트의 유일한 기준 문서다. 설계(`design/`)는 현재 규칙과 그 이유, 결과(`reports/`)는 구현·검증·측정 결과를 담는다. 바뀐 과정은 [결정 기록](design/decisions.md)에 날짜순으로 쌓는다.

상태: 확정(현재 기준) / 초안(검토 중) / 폐기(참고용으로만 남김)

## 문서 목록

### 설계 (`design/`)

| 문서 | 목적 | 상태 | 최종 수정일 |
|---|---|---|---|
| [design/domain.md](design/domain.md) | 이 도메인이 RAG에 맞는 이유, 위험 도메인 여부와 면책 안내 | 확정 | 2026-10-25 |
| [design/index-text.md](design/index-text.md) | 항목(모델) 1건의 색인 텍스트 템플릿과 렌더링 규칙 | 확정 | 2026-10-25 |
| [design/collections.md](design/collections.md) | 컬렉션 구성, 메타데이터 배치, 외부 문서 수집·색인 방식, 청크 메타데이터·식별자 | 확정 | 2026-10-25 |
| [design/models.md](design/models.md) | 임베딩·LLM 작업별 배정과 이유, 구조화 출력 방식 | 확정 | 2026-10-25 |
| [design/prompts.md](design/prompts.md) | 프롬프트 공통 규칙·모델 배정, 질의응답 프롬프트 S·P1~P3의 현재 버전·본문 | 확정 | 2026-10-25 |
| [design/prompts-services.md](design/prompts-services.md) | 서비스 기능 프롬프트 C1·C2(조건 탐색)·U(사용 조건 점검표)의 현재 버전·본문 | 확정 | 2026-10-25 |
| [design/retrieval-and-ui.md](design/retrieval-and-ui.md) | 검색·청킹 설정 기본값 표(`config/settings.json`과 테스트로 대조), 화면 구성, 성능 목표, 안내·오류 처리 | 확정 | 2026-10-25 |
| [design/data-refresh.md](design/data-refresh.md) | 데이터 갱신 절차, 목록 기준, 평가 기반 교체 판정, 비용 원칙 (구현 전) | 확정 | 2026-10-25 |
| [design/decisions.md](design/decisions.md) | 설계 결정과 바뀐 과정 (날짜순 누적) | 확정 | 2026-10-25 |
| [design/backlog.md](design/backlog.md) | 로드맵 순서의 남은 작업 (남은 작업은 여기 한 곳에서 관리) | 확정 | 2026-10-25 |

### 결과 (`reports/`)

| 문서 | 목적 | 상태 | 최종 수정일 |
|---|---|---|---|
| [reports/features.md](reports/features.md) | 기능(F)·비기능(NF) 번호, 설명, 구현 위치, 상태 | 확정 | 2026-10-25 |
| [reports/architecture.md](reports/architecture.md) | RAG 파이프라인 흐름, 설정 근거, 겪은 문제와 해결 | 확정 | 2026-10-25 |
| [reports/evaluation.md](reports/evaluation.md) | 기능별 확인 결과, 평가 세트 결과, 채택 판정, 기능 대조표 | 확정 | 2026-10-25 |
| [reports/rag-vs-no-rag.md](reports/rag-vs-no-rag.md) | 대표 질문 5개의 RAG 없이 / RAG 비교: 실행 조건, 판정 요약, 소비 토큰 | 확정 | 2026-10-25 |
| [reports/rag-vs-no-rag-answers-1.md](reports/rag-vs-no-rag-answers-1.md) | 위 비교의 답변 원문: 질문 1~3 | 확정 | 2026-10-25 |
| [reports/rag-vs-no-rag-answers-2.md](reports/rag-vs-no-rag-answers-2.md) | 위 비교의 답변 원문: 질문 4~5, 머리말 색인 후 | 확정 | 2026-10-25 |
| [reports/performance.md](reports/performance.md) | 단계별 처리 시간, 병목, 개선 전후, Anthropic API 직접 호출 재측정 | 확정 | 2026-10-25 |
| [reports/screenshots/](reports/screenshots/) | 화면 캡처 (README·evaluation.md에서 사용) | 확정 | 2026-10-25 |

저장소 루트: [README](../README.md)(소개·실행 방법), [CLAUDE.md](../CLAUDE.md)(Claude Code 작업 규칙)

## 작업별로 읽을 문서

모든 작업에서 먼저: [CLAUDE.md](../CLAUDE.md), [backlog.md](design/backlog.md)(해당 항목), [decisions.md](design/decisions.md)(관련 결정)

| 작업 | 읽을 문서 |
|---|---|
| 데이터 갱신 | [data-refresh.md](design/data-refresh.md), [collections.md](design/collections.md)(수집·색인·청크 식별자), [index-text.md](design/index-text.md), [evaluation.md](reports/evaluation.md)(평가 세트·채택 규칙), [prompts.md](design/prompts.md)(S 요약) |
| 검색·청킹 설정 | [retrieval-and-ui.md](design/retrieval-and-ui.md)(검색 설정 표), [collections.md](design/collections.md), [architecture.md](reports/architecture.md), [evaluation.md](reports/evaluation.md)(평가 세트 결과) |
| 프롬프트 수정 | [prompts.md](design/prompts.md), [prompts-services.md](design/prompts-services.md)(C1·C2·U), [models.md](design/models.md), [evaluation.md](reports/evaluation.md)(P1 비교와 채택 규칙), `prompts/ko/*.txt` |
| 화면 작업 | [retrieval-and-ui.md](design/retrieval-and-ui.md)(서비스 기능과 화면), [features.md](reports/features.md), [README](../README.md)(Streamlit·웹 화면 실행), [screenshots/](reports/screenshots/) |
| 평가·성능 측정 | [evaluation.md](reports/evaluation.md), [performance.md](reports/performance.md), [rag-vs-no-rag.md](reports/rag-vs-no-rag.md), [retrieval-and-ui.md](design/retrieval-and-ui.md)(성능 목표) |
| 배포 | [backlog.md](design/backlog.md)(웹 화면·배포), [decisions.md](design/decisions.md)(저장소에 올리는 데이터 범위), [data-refresh.md](design/data-refresh.md)(자동 갱신), [models.md](design/models.md)(모델·비용), [performance.md](reports/performance.md) |
