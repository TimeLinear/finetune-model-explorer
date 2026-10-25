# 검증 결과

- 상태: 확정
- 최종 수정일: 2026-10-25
- 관련 문서: [features.md](features.md), [rag-vs-no-rag.md](rag-vs-no-rag.md), [performance.md](performance.md), [retrieval-and-ui.md](../design/retrieval-and-ui.md)

> 기능별 확인 항목과 결과. 상태: 통과 / 실패 / 미확인. 증빙은 `screenshots/` 아래 캡처 파일 또는 실행 출력.
> 버전: 1단계 개발 후 점검 · 2026-10-22 (출처별 분리 검색·F2015 반영), 이후 2026-10-23 결과 추가
> 실행 환경: Windows 11, Python 3.12.10, 임베딩 `BAAI/bge-m3`(CPU), 답변 `claude-haiku-5-5`, 검색어 추출·선별·조건 변환 `gpt-5.4-nano` (초기 개발 단계의 API 프록시 경유)

## 1. 데이터와 색인 (F2001~F2002)

| 확인 항목 | 상태 | 증빙 / 비고 |
|---|---|---|
| 로드한 항목 수(202)와 `items` 색인 청크 수가 일치 | 통과 | `python scripts/build_index.py` 출력: `items 색인: 202 건`, `색인 후 청크 수 {'items': 202, 'docs': 4667}` |
| 색인 작업을 두 번 실행해도 청크 수가 늘지 않음 | 통과 | 두 번째 실행 출력: `색인 전 {'items': 202, 'docs': 4667}` → `카드 색인 결과 {'done': 202}` → `색인 후 {'items': 202, 'docs': 4667}` |
| 항목 1건의 색인 텍스트에 의도한 속성이 모두 들어감 | 통과 | `python scripts/render_index_text.py kakaocorp/kanana-1.5-8b-instruct-2505` 출력: 모델·개발사·국가 / 크기·구조 / 모달리티 / 학습 단계 / 분야 / 지원 언어 / 컨텍스트 길이(출처 표시) / 라이선스 / 도구 호출 / 소개(요약 v0.2) 10줄. 계열·버전, 베이스 모델 줄은 원본 데이터에 값이 없어 규칙대로 빠짐 |

## 2. 문서 수집과 색인 (F2003~F2005)

| 확인 항목 | 상태 | 증빙 / 비고 |
|---|---|---|
| 한 질문에 대해 프롬프트 1이 뽑은 검색어 목록 | 통과 | kanana 모델, 질문 "이 모델은 MoE 구조야? 상업적으로 써도 되는 라이선스야?" → `Kanana`(계열), `전문가 혼합(MoE)`, `Apache 라이선스 2.0` |
| 프롬프트 2에 따라 색인된 문서와 버려진 문서(이유 포함) 구분 | 통과 | 같은 질문: 선택 1건 `전문가 혼합`, 제외 11건(예: `카카오 (기업)` "모델의 MoE 여부나 라이선스 설명이 없음", `MOE` "동음이의어", `아파치 라이선스` "개요만 있어 이 모델 라이선스를 특정하지 못함"). 기록 파일 `data/chroma/wiki_log.json` |
| 같은 질문을 다시 물었을 때 수집이 다시 일어나지 않음 | 통과 | 질문 "Llama 계열과 비교해서 이 모델의 컨텍스트 길이는?" 첫 번째 8.2초 `collected` 2건 → 두 번째 0.0초 `cached` 2건(외부 호출 없음). 처음 구현에서는 프롬프트 1 출력이 매번 달라 1건이 다시 수집됐고, 질문별 검색어를 저장해 재사용하도록 고친 뒤 확인 ([architecture.md](architecture.md) 9.2절) |
| 선택한 항목 자체를 다룬 문서(모델 카드)가 빠지지 않음 | 통과 | 모델 카드는 프롬프트 2 선별 없이 202개 전부 색인 (`카드 색인 결과 {'indexed': 202}`). 단, 검색 결과(근거 목록)에 카드 청크가 항상 들어가는 것은 아님 — 판단 필요 항목 참고 |
| 청크 크기·중복 길이를 바꿔 색인하면 청크 수가 달라짐 | 통과 | 같은 3개 모델 카드(kanana, gemma-3-4b-it, Mamba-Codestral): 1000자/200자 → 11·41·8 = 60개, 500자/100자(`APP_SETTINGS`로 바꾼 설정, 별도 색인 폴더) → 19·70·10 = 99개 |

## 3. 답변과 근거 (F2006~F2008)

| 확인 항목 | 상태 | 증빙 / 비고 |
|---|---|---|
| Top-k를 바꿨을 때 같은 질문의 근거 목록 변화 | 통과 | 출처별 분리 검색 후(2026-10-22), kanana, "이 모델의 라이선스 조건은?": `card_k=4, wiki_k=2` → 근거 7개(항목 1·카드 4·위키 2), `card_k=2, wiki_k=1` → 근거 4개(항목 1·카드 2·위키 1). 앞쪽 청크는 같고 뒤쪽이 빠짐. (분리 전 `docs_k` 5 → 3에서도 6개 → 4개로 줄어드는 것을 확인했었음) |
| (평가 세트) `card_k`별 카드 검색 적중 | 측정 | `tests/retrieval_eval/` 카드 검색 평가 세트(6개 모델·33개 사례×표현 3개=99개, 정답 조각은 색인 v2에서 미리 지정, P1 문구 고정), 유사도 검색, 색인 v2 사본, 2026-10-23. 적중 = 정답 조각이 상위 k개 안에 하나라도 있음, 안정 = 표현 3개 모두 적중. `card_k=2`: 82/99(0.828)·안정 25/33 / `card_k=4`(현재): 90/99(0.909)·27/33 / `card_k=6`: 96/99(0.970)·31/33, 4 대비 놓침으로 바뀐 것 0건·새로 적중 6건. 검색 단위로는 6이 낫지만 답변 입력이 늘어나므로, 아래 답변 단위 비교 후 `card_k=6` 적용 (2026-10-23). 결과: `tests/retrieval_eval/results/topk2.json`, `baseline.json`, `topk6.json` |
| (평가 세트) 카드 검색 보강 후보 비교 | 미채택 | 같은 평가 세트·사본, `card_k=4`, 2026-10-23. 기준선 90/99·안정 27/33 / (a) P1 문구 + 원래 질문 RRF 90/99·28/33(놓침으로 바뀐 것 5) / (b) 청크 머리 정보 92/99·28/33(2) / (c) 둘 다 88/99·27/33(5). 채택 규칙은 실험 전에 정함: 안정성(같은 뜻의 표현 3개 모두 적중)이 가장 높은 후보를 고르되, 기준선에서 맞히던 질의가 하나라도 놓침으로 바뀌면 제외하고, 동률이면 바꾸는 것이 적은 쪽(a < b < c), 기준선보다 나은 후보가 없으면 채택하지 않는다. 세 후보 모두 놓침이 생겨 채택하지 않았다. 결과: `a_rrf.json`, `b_header.json`, `c_rrf_header.json` |
| (평가 세트) 답변 단위 비교: `card_k` 4 vs 6 | 통과 → 6 적용 | 33개 사례 × 표현 1번 × k{4, 6} = 66회, 2026-10-23. 근거 = 항목 + 카드 청크(위키 제외), P1 문구는 `p1_cache.jsonl`, 답변 프롬프트·모델은 앱과 같음(claude-haiku-5-5, thinking 끔). 채점 기준(사례별 핵심 사실 1~2개, `tests/retrieval_eval/answer_rubric.jsonl`)은 답변 생성 전에 고정. 답변 66개를 설정 표시와 근거 번호를 지운 채 섞어 무작위 ID로 채점한 뒤 설정을 공개. 채택 규칙: k=6 정답 수 ≥ k=4 정답 수, 그리고 k=4 정답 → k=6 정답 아님 0건 |
| LangGraph가 retrieve / generate 두 노드로 구성 (그래프 출력 또는 코드 캡처) | 통과 | `get_graph().get_graph().draw_mermaid()` 출력: `__start__ --> retrieve; retrieve --> generate; generate --> __end__` (`rag/graph.py`) |
| 답변 본문의 근거 번호와 화면의 근거 목록 일치 | 통과 | gemma-3-4b-it 답변이 [근거 1][근거 2][근거 3][근거 6] 인용 → 화면 "답변에 사용한 근거 4건"에 1·2·3·6만 표시 (검색된 근거 6개 중 미인용 2개는 표시 안 함). [`answer-evidence-gemma.jpg`](screenshots/answer-evidence-gemma.jpg) |
| 근거 목록에 항목 메타데이터와 외부 문서가 구분 표시 | 통과 | 같은 화면: "항목 메타데이터", "모델 카드 · Description", "위키백과 · 아키텍처"로 구분 |
| 문서에 없는 것을 물으면 추측하지 않고 확인되지 않는다고 답함 | 통과 | kanana, "학습에 GPU를 몇 대 썼고 학습 비용은?" → "제공된 문서에서 확인되지 않습니다." 후 확인되는 관련 정보만 근거와 함께 덧붙임 |
| 인용된 근거가 하나도 없을 때 화면 안내 | 통과 (합성 입력) | `tests/test_no_citation.py`: 인용 표기가 없는 답변을 돌려주는 가짜 LLM으로 실제 `generate` 노드를 실행 → `cited=[]`, `no_citation=True`. 같은 모양의 메시지를 Streamlit `AppTest`로 실제 렌더링 → 안내 문구 "이 답변에는 인용된 근거가 없습니다." 표시, 근거 목록 없음. 실제 응답(API 프록시 경유)이 인용 없이 나온 경우는 화면에서 재현하지 못함(감사 인사에도 근거를 인용함) |


**답변 단위 비교 결과 (card_k 4 vs 6)**

| 항목 | card_k=4 | card_k=6 |
|---|---|---|
| 정답 / 부분 / 오답 / 확인 안 됨 | 31 / 2 / 0 / 0 | 33 / 0 / 0 / 0 |
| 정답 조각이 근거에 들어감 | 29/33 | 31/33 |
| 정답 조각 인용률 (근거 번호 대조) | 29/33 (87.9%) | 31/33 (93.9%) |
| 입력 토큰 중앙값 | 2,458 | 3,086 (+26%) |
| 출력 토큰 중앙값 | 357 | 370 |
| 답변 생성 시간 중앙값 [범위] | 4.17초 [1.36~26.03] | 4.57초 [0.92~48.29] |
| 호출 비용 비율 (API 프록시 단가 기준, k=4 = 1) | 1 | 1.14 |

- k=4→6에서 나빠진 사례: 없음. 좋아진 사례 2건: c22(gemma 이미지 입력: k=4는 출력 형식 누락으로 부분), c31(Ministral 지원 언어: k=4는 10개 중 6개만 제시해 부분). 두 사례 모두 k=6에서만 정답 조각(5위)이 근거에 들어왔다.
- 답변 시간은 66건 중 38건이 0.9~5.0초, 25건이 20~48초, 3건이 10~15초로 갈렸다. 출력 길이와 관계없이 나타나 API 프록시의 스트림 종료 지연으로 보며, 중앙값만 비교에 쓴다.
- 결과: `tests/retrieval_eval/results/answer_k.jsonl`(답변·지표), `answer_blind_grades.json`(블라인드 채점과 공개 키)

**P1 v0.3 vs v0.4 카드 검색 비교 (claude-haiku-5-5, 2026-10-23)**

10-24부터 (실제 전환: 2026-10-23) P1 모델(LLM_SMALL)이 claude-haiku-5-5로 바뀌므로 API 프록시 경유 claude-haiku-5-5(thinking 끔)로 평가했다. 평가 세트 99개 표현 × 2회 × 버전 2개 = P1 396회, 검색은 `card_k=6`. v0.4 후보 문안(`tests/retrieval_eval/prompt_candidates/query_extract_v04.txt`)은 규칙 5 보강(묻는 속성 단어를 그대로 옮김)·규칙 6(이용 조건 질문이면 license, acceptable use policy, terms 덧붙임)·예시 3 추가. 채택 규칙은 실행 전에 정함: v0.4 전체 적중 ≥ v0.3, 그리고 사례별 적중이 v0.3보다 2회 이상 줄어든 사례 0건.

| 항목 | v0.3 (현행) | v0.4 후보 |
|---|---|---|
| 전체 적중 (198회 중) | 189 | 188 |
| 6회 모두 적중한 사례 (33개 중) | 30 | 28 |
| 검색 문구 길이 중앙값 (단어) | 5 | 5 |
| 사례별 적중이 달라진 사례 | — | c09 Llama 한계 6 → 4, c20 gemma 지원 언어 6 → 5, c33 Ministral 용도 0 → 2 |
| 앱 지시 표현 Llama "이 모델을 이미지 입력용으로 쓸 때 지역 제한이 있어?" 5회: EU 조각 순위 | 1, 2, 2, 2, 1 (5/5 적중) | 2, 2, 4, 3, 6 (5/5 적중) |

- 결과: **v0.3 유지** (전체 적중 188 < 189, c09가 2회 줄어 규칙 두 조건 모두 불충족). 앱 프롬프트는 바꾸지 않았다.
- 참고: 같은 평가 세트에서 P1이 gpt-5.4-nano(v0.3)일 때는 99회 중 96 적중이었다(`r7_nano_k6`, 위 `topk6`과 같음). claude-haiku-5-5는 v0.3에서도 지시 표현을 "image input region restriction license territory" 같은 문구로 옮겨 EU 조각이 1~2위였다 (nano 저장분 "regional availability image input"은 24위).
- 결과 파일: `tests/retrieval_eval/p1_cache_haiku_v03.jsonl`, `p1_cache_haiku_v04.jsonl`, `results/haiku_v03.json`, `results/haiku_v04.json`, `results/r7/llama_instructed_p1.json`

## 4. 서비스 기능과 화면 (F2009~F2012)

| 확인 항목 | 상태 | 증빙 / 비고 |
|---|---|---|
| 모델을 바꿨을 때 이전 대화가 섞이지 않음 | 통과 | gemma 대화 후 kanana 선택 → 빈 대화, Qwen3-VL-8B 선택 → 빈 대화, 다시 gemma 선택 → gemma 대화 유지 (브라우저 확인) |
| 조건 기반 탐색 결과에 조건과 맞지 않는 모델이 섞이지 않음 | 통과 | 2026-10-23 재확인 (기본 프로필 `anthropic_direct`, C1·C2 = claude-haiku-5-5, C2 v0.4): "이미지도 받을 수 있는 10B 이하 모델 중 요즘 제일 많이 쓰는 거" → 후보 30개 중 5개(Qwen3.5-4B, Qwen3.5-9B, Qwen3-VL-8B-Instruct, Qwen2.5-VL-7B-Instruct, Qwen3-VL-4B-Instruct), 항목 원본에서 같은 조건(10B 이하·이미지 입력·다운로드 순)으로 직접 계산한 상위 5개와 순서까지 일치. 맞는 이유 문구의 파라미터 수는 항목 값과 모두 일치(API 프록시 경유 Haiku로 확인). (이전: v0.3 + gpt-5.4-nano 때 일치, v0.4 + nano는 2~4위를 건너뜀 — [architecture.md](architecture.md) 9.2절) [`condition-explore.jpg`](screenshots/condition-explore.jpg) |
| 사용 조건 점검표에도 근거가 함께 제시됨 | 통과 | kanana 점검표 7행, 행마다 근거 번호, 하단 "점검표 근거 (5)" 목록과 면책 문구. 근거가 없는 "이용 승인 절차"는 "문서에서 확인되지 않음". [`usage-check-kanana.jpg`](screenshots/usage-check-kanana.jpg) |
| 문서 수집과 답변 생성 중 진행 상태 표시 | 통과 | "카드 색인 확인 중 → 추가 문서 검색 중 → 수집된 위키 문서: Gemma (언어 모델) → 답변 생성 중 → 완료". [`progress-status.jpg`](screenshots/progress-status.jpg) |
| 색인이 없는 상태 / API 키가 없는 상태에서 안내 표시 | 통과 | API 키를 비우고 빈 색인 폴더로 실행: 두 안내 문구 표시, 채팅 입력 비활성화, 사이드바 "항목 0건 · 문서 청크 0건". 캡처는 기본 프로필의 키 `ANTHROPIC_API_KEY`를 비운 화면. [`missing-key-empty-index.png`](screenshots/missing-key-empty-index.png) |
| 라이선스 관련 면책 안내 표시 | 통과 | 사이드바 하단, 점검표 하단, 조건 탐색 페이지 하단 |
| (추가) highlights 말줄임·툴팁·전체 보기 | 통과 | 사이드바: `nvidia/NVIDIA-Nemotron-Nano-9B-v2`의 24자 항목이 말줄임되고(`scrollWidth > clientWidth`) `title`에 전체 문구, "특징 전체 보기"에 원문 목록. 이스케이프는 `tests/test_no_citation.py`(합성 입력). 조건 탐색 카드의 칩은 브라우저에서 따로 확인하지 않음. [`highlights-truncation.jpg`](screenshots/highlights-truncation.jpg) |

## 5. 확장 기능

| 기능 | 확인 항목 | 상태 | 증빙 / 비고 |
|---|---|---|---|
| F2014 | 같은 질문에 유사도 검색과 MMR 검색의 근거 목록 차이 | 통과 | 출처별 분리 검색 후(2026-10-22), kanana, "이 모델의 라이선스 조건은?", 카드 4·위키 2: 유사도 → 카드 청크 6·9·2·3 + 위키 21·14, MMR(fetch 30, λ 0.5) → 카드 6·9·7·10 + 위키 21·23. 출처별 결과 수는 유사도와 같고 구성이 달라짐 |
| F2014 | (평가 세트) 유사도 대비 MMR 카드 검색 적중 | 측정 | 위 3절과 같은 평가 세트·사본, `card_k=4`, MMR(fetch 30, λ 0.5): 72/99(0.727)·안정 22/33. 유사도(90/99·27/33) 대비 놓침으로 바뀐 것 18건(제한 사항·이용 정책·컨텍스트 길이·지역 제한 등), 새로 적중 0건. 카드 검색에서는 MMR이 정답 조각과 비슷한 조각을 다양성 때문에 밀어내는 경우가 많아 기본값은 유사도 유지. 결과: `tests/retrieval_eval/results/mmr.json` |
| F2016 | 근거 목록에 출처 종류(모델 카드 / 위키백과) 구분 표시 | 통과 | 3절 화면과 같음 |
| F2015 | 대표 질문의 RAG 전후 답변 비교 | 통과 | 5개 질문의 RAG 전후 답변과 답변 모델 3종(gpt-5.4-nano / claude-haiku-5-5 / claude-sonnet-5-5) 답변을 나란히 확보·평가. [rag-vs-no-rag.md](rag-vs-no-rag.md), 아래 6절 |

## 6. RAG 사용 전후 품질 비교 (F2015)

> 원문과 판정 근거는 [rag-vs-no-rag.md](rag-vs-no-rag.md). 답변 모델 `claude-haiku-5-5`, 사실 정확성은 카드 본문·항목 메타데이터로만 판정 (2026-10-22 실행).

| # | 대표 질문 | RAG 없이 | RAG 사용 | 사실 정확성 | 근거 제시 | 모름을 모른다고 함 |
|---|---|---|---|---|---|---|
| 1 | kanana-1.5-8b-instruct와 kanana-nano-2.1b-instruct 중 상업적으로 쓸 수 있는 건? (선택 모델: kanana-1.5-8b-instruct) | 둘 다 상업 사용 허용되는 자체 라이선스라고 답함 | 8b는 apache-2.0, nano는 확인되지 않음 | 없이: 틀림 (메타데이터 8b `apache-2.0`, nano `cc-by-nc-4.0`) / 사용: 맞음 | 없이: 없음 / 사용: [근거 1][근거 5] | 없이: 아니오 / 사용: 예 (nano는 선택 모델 범위 밖이라 근거 없음) |
| 2 | EXAONE-3.5-7.8B-Instruct를 사내 업무용으로 파인튜닝해 배포해도 되나? | NC 원칙이라 권장하지 않는다고 결론 (출력 상한에 걸려 잘림) | 라이선스 이름(1.1 - NC)만 전달, 허용 여부는 확인되지 않음 | 없이: 라이선스 이름은 일치, 나머지 판정 불가 / 사용: 맞음 (카드 License 절) | 없이: 없음 / 사용: [근거 1][근거 2][근거 3] | 없이: 아니오 / 사용: 예 |
| 3 | Gemma 3 4B-it 최대 컨텍스트 길이는? | 128K, "입력과 출력을 합친" 기준 | 입력 128K, 출력 8192, 메타데이터 131,072 | 없이: 부분 틀림 (카드는 입력 128K·출력 8192 따로 표기) / 사용: 맞음 | 없이: 없음 / 사용: [근거 1][근거 2][근거 5] | 해당 없음 |
| 4 | Llama 3.2 11B Vision을 이미지 입력용으로 쓸 때 지역 제한이 있나? | EU 거주자·EU 기업 제한이 있다고 답함 | 지역 제한은 확인되지 않음, Out of Scope·영어 전용 전달 | 없이: 판정 불가 (카드 본문에 없음. 단 카드 머리말 `extra_gated_prompt`에 같은 EU 제한 문구 있음) / 사용: 본문 기준 맞음, 머리말의 EU 제한은 놓침 | 없이: 없음 / 사용: [근거 1][근거 2][근거 3] | 없이: 아니오 / 사용: 예 |
| 5 | 최근 공개된 ibm-granite/granite-4.2-8b의 파라미터 수와 MoE 여부는? | 학습 데이터에 없어 알 수 없다고 답함 | 8.79B(메타데이터)·8B(카드), Dense | 없이: 판정 대상 진술 없음 / 사용: 맞음 | 없이: 없음 / 사용: [근거 1][근거 2] | 없이: 예 / 사용: 해당 없음 |

## 7. 비기능 요구사항 (NF2001~NF2007)

| 번호 | 확인 항목 | 상태 | 증빙 / 비고 |
|---|---|---|---|
| NF2001 | 대표 질문의 전체 처리 시간 | 통과 (2026-10-23 재측정, 중앙값 기준) | 2026-10-23 anthropic_direct 재측정([performance.md](performance.md) 10절): 중앙값 웜 2.19초·콜드 12.90초로 목표 충족. 이전 측정: 2026-10-22 측정 48건 ([performance.md](performance.md), 질문 2개 × 모델 2개 × 콜드/웜 × 실행 방식 3개 × 2회). 목표(2026-10-23 확정, [retrieval-and-ui.md](../design/retrieval-and-ui.md)) 웜 15초·콜드 40초 대비: 웜 중앙값 7.0초·최대 16.2초(1건 초과), 콜드 중앙값 16.9초·최대 42.6초(1건 초과). 병목은 답변 생성 43%(출력 토큰 수에 비례), P2 22%, P1 12%. 파일 감시 켬/끔에 따른 차이는 측정되지 않음 |
| NF2002 | 이미 수집한 검색어 재수집 안 함 | 통과 | 2절 세 번째 항목과 같음. 검색어 단위 기록 + 질문 단위 검색어 재사용, 받은 위키 본문 캐시(`data/chroma/wiki_pages/`) |
| NF2003 | 소스코드·문서에 API 키 없음 | 통과 | `.env`의 값 3개로 저장소 전체 파일(`.venv`·`.git`·이미지 제외)과 `data/chroma` JSON을 검색: `.env` 외 0건 |
| NF2004 | 화면에 키·프롬프트 전문·오류 추적 정보 노출 없음 | 통과 | 2026-10-23 가짜 키로 오류를 일부러 내 확인: 화면에는 짧은 안내만, 상세는 `logs/app.log`. 이전 기록: 정상 화면(질의응답·점검표·조건 탐색·키 누락·색인 없음)에는 노출 없음. 예외 발생 화면은 실제로 발생시켜 확인하지 않음(코드상 짧은 안내 + `logs/app.log` 기록) |
| NF2005 | 수집·색인·검색·생성·UI 모듈 분리 | 통과 | `data_prep/`(항목·카드·요약·위키 수집, 도메인 의존 코드), `vectorstore/`(컬렉션·청킹·임베딩·색인), `rag/`(LangGraph·근거 번호), `services/`(점검표·조건 탐색), `ui/`+`app.py`+`pages/`(화면), `common/`(설정·LLM·로그) |
| NF2006 | 재시도·호출 간격·User-Agent 식별 정보 | 통과 | Hugging Face: 간격 `hf.request_interval_sec`=0.5초, 재시도 `http.max_retries`=3(401·403·404 제외, 429는 Retry-After), 카드 202개 ok / 실패 0. 위키백과: 간격 `wiki.request_interval_sec`=1.0초, 같은 재시도 규칙, User-Agent에 `WIKI_CONTACT` 포함(ASCII 확인, 값은 출력·기록 안 함) |
| NF2007 | 데이터·문서 출처와 이용 조건 기록 | 통과 | README의 출처와 이용 조건, [domain.md](../design/domain.md)에 기록. 청크마다 원문 URL·리비전 저장, 근거 목록에 원문 링크 표시. 카드 원문은 저장소 제외, manifest(리비전·본문 해시)만 포함 |

## 8. 기능 대조표

번호는 [features.md](features.md)의 기능 번호(F2001~F2016, NF2001~NF2007)다. 결과는 이 문서 1~7절의 상태와 같고, 캡처는 `screenshots/` 아래 파일이다.

| 번호 | 기능명 | 구현 위치 | 확인 방법 | 결과 | 증빙 |
|---|---|---|---|---|---|
| F2001 | 항목 메타데이터 적재 | `data_prep/items.py`, `data_prep/index_text.py` | 로드 건수(202)와 `items` 청크 수 비교, 항목 1건 색인 텍스트 출력 (1절) | 통과 | `scripts/build_index.py`·`scripts/render_index_text.py` 출력 (1절) |
| F2002 | 메타데이터 색인 (RAG 1) | `data_prep/indexing.py`, `vectorstore/store.py`, `scripts/build_index.py` | 색인 2회 실행 전후 청크 수 비교 (1절) | 통과 | `scripts/build_index.py` 두 번째 실행 출력 (1절) |
| F2003 | 검색어 추출 (프롬프트 1) | `data_prep/wiki.py` `extract_queries`, `prompts/ko/query_extract.txt` | 질문 1개의 검색어 목록 출력 (2절) | 통과 | 검색어 목록 출력 (2절) |
| F2004 | 외부 문서 수집 (프롬프트 2) | `data_prep/wiki.py` `select_candidates`·`collect_for_question`, `data_prep/cards.py`, `prompts/ko/doc_select.txt` | 선택·제외와 이유 기록 확인, 모델 카드 누락 없음 (2절) | 통과 | `data/chroma/wiki_log.json` |
| F2005 | 외부 문서 색인 (RAG 2) | `vectorstore/chunking.py`, `vectorstore/docs_index.py` | 청크 크기·중복 길이를 바꿔 재색인 후 청크 수 비교 (2절) | 통과 | 청크 수 비교 (2절) |
| F2006 | 근거 검색 및 병합 | `rag/graph.py` `retrieve`·`search_cards`, `rag/evidence.py`, `config/settings.json` `retrieve.*` | Top-k 변경 시 근거 목록 변화, 평가 세트 `card_k` 비교 (3절) | 통과 | `tests/retrieval_eval/results/` |
| F2007 | 근거 기반 답변 생성 (프롬프트 3) | `rag/graph.py` `generate`, `prompts/ko/answer.txt` | 그래프 구조 출력(retrieve → generate), 문서에 없는 질문 (3절) | 통과 | 그래프 출력·답변 (3절) |
| F2008 | 근거 표시 | `rag/evidence.py`, `ui/components.py`, `web/static/js/common.js` | 답변의 근거 번호와 화면 목록 대조, 인용 없음 안내(합성 입력 테스트) (3절) | 통과 (인용 없음 안내는 합성 입력) | [`answer-evidence-gemma.jpg`](screenshots/answer-evidence-gemma.jpg), `tests/test_no_citation.py` |
| F2009 | 항목 선택 및 질의응답 | `app.py`, `web/static/index.html`·`js/chat.js` | 모델 A 대화 후 모델 B로 바꿔 질문 (4절) | 통과 | 브라우저 확인 (4절) |
| F2010 | 도메인 특화 기능 (사용 조건 점검표) | `services/usage_check.py`, `prompts/ko/usage_check.txt` | 점검표 행마다 근거 번호·근거 목록 확인 (4절) | 통과 | [`usage-check-kanana.jpg`](screenshots/usage-check-kanana.jpg), [`web-usage-check.png`](screenshots/web-usage-check.png) |
| F2011 | 조건 기반 항목 탐색 | `services/condition_search.py`, `pages/1_조건_탐색.py`, `web/static/explore.html` | 결과를 항목 원본에서 직접 계산한 상위 5개와 대조 (4절) | 통과 | [`condition-explore.jpg`](screenshots/condition-explore.jpg), [`web-explore.png`](screenshots/web-explore.png) |
| F2012 | 진행 상태 및 안내 | `app.py`, `ui/components.py`, `i18n/ko.json` | 진행 표시, 색인 없음·키 없음 안내, 면책 문구 (4절) | 통과 | [`progress-status.jpg`](screenshots/progress-status.jpg), [`missing-key-empty-index.png`](screenshots/missing-key-empty-index.png) |
| F2013 | 프론트엔드 직접 구현 | `web/api.py`, `web/static/` | 웹 화면에서 질문·답변·근거·점검표·조건 탐색 확인, 단위 테스트 (README의 웹 화면 실행 방법, 9절) | 통과 | [`web-chat.png`](screenshots/web-chat.png), [`web-usage-check.png`](screenshots/web-usage-check.png), [`web-explore.png`](screenshots/web-explore.png), [`web-dark.png`](screenshots/web-dark.png), [`web-mobile.png`](screenshots/web-mobile.png), `tests/test_web_api.py` |
| F2014 | MMR 검색 적용 | `rag/graph.py` `search_source` (`retrieve.search_type=mmr`) | 같은 질문의 유사도·MMR 근거 목록 비교, 평가 세트 적중 비교 (5절) | 통과 | `tests/retrieval_eval/results/mmr.json` |
| F2015 | RAG 전후 품질 비교 | [rag-vs-no-rag.md](rag-vs-no-rag.md) | 대표 질문 5개를 RAG 없이·RAG로 답하게 해 비교 (5·6절) | 통과 | [`rag-effect-a-kanana-commercial.jpg`](screenshots/rag-effect-a-kanana-commercial.jpg), [`rag-effect-b-llama-region.jpg`](screenshots/rag-effect-b-llama-region.jpg) |
| F2016 | 여러 문서 출처 결합 | `vectorstore/docs_index.py` (`doc_type`), `data_prep/wiki.py`, `rag/graph.py` 출처별 분리 검색 | 근거 목록의 출처 종류 구분 표시 (5절) | 통과 | [`answer-evidence-gemma.jpg`](screenshots/answer-evidence-gemma.jpg) |
| NF2001 | 응답 시간 | `common/perf.py`, `logs/perf.jsonl` | 콜드·웜 처리 시간 측정 (7절, [performance.md](performance.md)) | 통과 (2026-10-23 anthropic_direct 재측정, 중앙값 기준. [performance.md](performance.md) 10절) | `logs/perf.jsonl`, [performance.md](performance.md) |
| NF2002 | 수집 캐시 | `data_prep/wiki.py` (`wiki_log.json`), `data_prep/indexing.py` (카드 색인 상태) | 같은 질문 재실행 시 외부 호출 0건 (2·7절) | 통과 | `data/chroma/wiki_log.json` (2절) |
| NF2003 | API 키 관리 | `.env`(저장소 제외), `common/llm.py` | `.env` 값으로 저장소 전체 검색 (7절) | 통과 | 검색 결과 `.env` 외 0건 (7절) |
| NF2004 | 내부 정보 비노출 | `ui/components.py` `show_error`, `common/logs.py`, `web/api.py` | 정상·오류 화면 확인 (7절) | 통과 | 가짜 키 오류 화면 확인, `logs/app.log` (7절) |
| NF2005 | 모듈 분리 | `data_prep/`, `vectorstore/`, `rag/`, `services/`, `ui/`·`web/` | 파일 구성 확인 (7절) | 통과 | README의 디렉터리 구조 |
| NF2006 | 외부 API 예절 | `data_prep/cards.py`, `data_prep/wiki.py`, `scripts/enrich.py` | 재시도·호출 간격·User-Agent 코드 확인 (7절) | 통과 | `config/settings.json` 값 (7절) |
| NF2007 | 출처와 이용 조건 | README의 데이터·출처와 이용 조건, 청크 메타데이터(URL·리비전) | 기록 확인 (7절) | 통과 | README, [domain.md](../design/domain.md) |

## 9. 확장 기능과 기본 구현 비교

새로 측정하지 않고, 이미 기록한 결과를 요약한다.

- **F2013 웹 화면 vs Streamlit**: 같은 모듈(`rag/`, `services/`)을 불러 질의응답(스트리밍·근거 목록)·사용 조건 점검표·조건 탐색을 같은 결과로 보여 준다. 응답 시간(2026-10-23, anthropic_direct)은 웜 중앙값 Streamlit 2.19초 / 웹 2.99초로 둘 다 목표 안이다. 웹 콜드 1회(5.27초)는 위키 검색어가 이미 수집돼 P2가 없었으므로 Streamlit 콜드(12.90초)와 조건이 다르다. → [performance.md](performance.md) 10절, README의 웹 화면 실행 방법
- **F2014 MMR vs 유사도**: 같은 질문에서 MMR은 출처별 결과 수는 같고 구성이 달라졌다(kanana: 카드 6·9·2·3 → 6·9·7·10). 평가 세트(`card_k=4`)에서는 MMR 적중 72/99로 유사도 90/99보다 낮아(놓침으로 바뀐 것 18건), 기본값은 유사도로 둔다. → 5절
- **F2015 RAG 없이 vs RAG**: 대표 질문 5개 중 RAG 없이 답한 것은 틀림 1(kanana 상업 이용)·부분 틀림 1(Gemma 출력 길이)·판정 불가 1(근거 없음)이었고, RAG는 근거 번호와 함께 맞게 답하거나 문서에 없는 것은 확인되지 않는다고 답했다. → [rag-vs-no-rag.md](rag-vs-no-rag.md), 6절
- **F2016 모델 카드만 vs 카드 + 위키백과**: 위키백과는 개념·계열 설명을 보탠다. 처음에는 한 컬렉션을 한국어 질문으로 함께 검색해 근거가 모두 한국어 위키 청크로 채워지고 영어 카드 청크가 빠졌다(항목 1 + 위키 5, 카드 0). 그래서 출처별로 나눠 카드(영어 검색 문구, `card_k`)와 위키(원래 질문, `wiki_k`)를 따로 검색한다(항목 1 + 카드 4 + 위키 2, 이후 카드 6). → [architecture.md](architecture.md) 9.2절
