# RAG 사용 전후 답변 원문 (질문 4~5, 머리말 색인 후)

- 상태: 확정
- 최종 수정일: 2026-10-25
- 관련 문서: [rag-vs-no-rag.md](rag-vs-no-rag.md), [rag-vs-no-rag-answers-1.md](rag-vs-no-rag-answers-1.md), [evaluation.md](evaluation.md)

> 실행 조건·평가 기준·판정 요약은 [rag-vs-no-rag.md](rag-vs-no-rag.md)에 있다. 답변은 원문 그대로 옮겼다.

## 질문 4. Llama 3.2 11B Vision을 이미지 입력용으로 쓸 때 지역 제한이 있나?

- 선택 모델: `meta-llama/Llama-3.2-11B-Vision-Instruct`
- 판정 근거: Llama 3.2 11B Vision 카드 본문 `Intended Use`의 Out of Scope: 무역 규정 포함 관련 법령 위반 사용, Acceptable Use Policy·Llama 3.2 Community License가 금지한 사용, 지원 언어 밖 사용. 항목 메타데이터 `license` = `llama3.2`, `gated` = `manual`. 카드 본문에는 지역(EU) 제한 문구가 없다. 같은 저장소 README의 YAML 머리말(`extra_gated_prompt`, data/cards의 .frontmatter.yaml)에는 "멀티모달 모델의 권리는 EU에 거주하는 개인·EU에 주된 사업장을 둔 회사에 부여되지 않는다(최종 사용자 제외)"는 문구가 있다.
- 참고: 판정 기준(카드 본문·메타데이터)으로는 지역 제한을 판정할 수 없다. 다만 머리말에는 EU 제한이 있고, 우리 색인은 머리말을 넣지 않아 RAG 답변이 이 내용을 놓쳤다 (판단 필요 항목 참고).
- RAG 처리: 카드 검색 문구 `image input regional restrictions usage policy`, 위키 검색어 `메타 Llama 3.2 Vision 사용 지역 제한`(collected), 처리 시간 8.1초
- RAG 근거 목록: [근거 1] item / [근거 2] model_card · New Capabilities and Use Cases / [근거 3] model_card · Intended Use / [근거 4] model_card · Intended Use / [근거 5] model_card · Use with transformers — 인용됨: [1, 2, 3]

| 답변 | 사실 정확성 (판정 근거) | 근거 제시 | 모름을 모른다고 함 |
|---|---|---|---|
| RAG 없이 (haiku) | 판정 불가 — 카드 본문·메타데이터 기준. EU 제한 설명은 머리말 `extra_gated_prompt` 문구와 내용이 일치함(참고). "한국 등 EU 외 지역은 별도 지역 제한 없음" 등은 판정 불가 | 없음 | 아니오 |
| RAG (haiku) | 카드 본문 기준 맞음 — Out of Scope·영어 전용·라이선스 동의 필요 내용 일치. 단 머리말의 EU 제한은 근거에 없어 "확인되지 않습니다"로 답함 | 있음 [근거 1][근거 2][근거 3] | 예 |
| RAG (gpt-5.4-nano) | 카드 본문 기준 맞음 — 지원 언어 밖 사용 금지 인용 일치 | 있음 [근거 1][근거 3][근거 4] | 예 |
| RAG (sonnet) | 카드 본문 기준 맞음 — Out of Scope·영어 전용 내용 일치, 지역 제한은 확인되지 않는다고 함 | 있음 [근거 1][근거 3] | 예 |

#### RAG 없이 (claude-haiku-5-5) — 입력 49 / 출력 1,245 토큰

````text
네, **있습니다.** Llama 3.2 11B Vision의 라이선스(Llama 3.2 Community License)에는 **EU 거주자 및 EU에 주된 사업장을 둔 기업에 대한 제한**이 있습니다.

**주요 내용**
- 라이선스의 멀티모달 모델(11B, 90B Vision) 관련 조항은, **EU에 거주(domicile)하는 개인이나 EU에 주사업장(principal place of business)을 둔 기업**에게는 권리를 부여하지 않는다고 명시합니다.
- 다만 이 제한은 **해당 모델이 포함된 제품이나 서비스의 최종 사용자(end user)에게는 적용되지 않습니다.** 즉, EU 기업이 만든 서비스를 EU 사용자가 쓰는 것은 가능하지만, EU 기업/개인이 직접 모델을 내려받아 사용·배포하는 것은 제한됩니다.
- 텍스트 전용 모델(1B, 3B 등)에는 이 제한이 적용되지 않습니다.
- Meta는 EU의 AI 및 데이터 규제(GDPR 등)에 대한 법적 불확실성을 이유로 든 것으로 알려져 있습니다.

**추가로 확인할 점**
- **클라우드 서비스의 지역 제한**: AWS Bedrock, Azure, Google Cloud 등에서 제공하는 경우 각 플랫폼의 리전별 가용성과 약관이 따로 있으니 확인이 필요합니다.
- **한국 등 EU 외 지역**: 라이선스상 별도의 지역 제한은 없습니다. 다만 국내 개인정보보호법 등 현지 법규와 Acceptable Use Policy는 준수해야 합니다.
- **최신 조건**: 라이선스와 정책은 바뀔 수 있으므로, 사용 전 Meta 공식 라이선스 문서와 Hugging Face 모델 카드를 직접 확인하세요. 법적 판단이 필요한 상황이라면 법률 전문가와 상담하는 것이 좋습니다.
````

#### RAG (claude-haiku-5-5) — 입력 2,468 / 출력 811 토큰

````text
제공된 문서에서 지역(국가·지역) 사용 제한은 확인되지 않습니다.

다만 관련해서 확인되는 내용은 다음과 같습니다.

- **라이선스:** 라이선스는 llama3.2이며, 사용 전 라이선스 동의가 필요합니다 [근거 1].
- **금지된 사용:** 적용 가능한 법령이나 규정(무역 컴플라이언스 법규 포함)을 위반하는 방식의 사용은 범위 밖입니다. Acceptable Use Policy와 Llama 3.2 Community License에서 금지하는 방식의 사용도 마찬가지입니다 [근거 3].
- **언어 범위:** 이미지+텍스트 작업은 영어만 공식 지원됩니다 [근거 1]. 모델 카드에 명시되지 않은 언어로의 사용도 범위 밖입니다 [근거 3].
- **개인 식별 위험:** 모델이 이미지 속 개인을 식별하는 위험에 대해 별도 평가와 완화 조치를 했다고 되어 있습니다. 개발자는 자신의 응용 프로그램 맥락에서 식별 위험을 평가하고, 필요하면 Llama Guard 3-11B-Vision 배포 등 추가 완화 조치를 고려하라고 권고합니다 [근거 2].

지역별 적용 가능 여부는 라이선스 원문과 해당 지역 법규를 직접 확인해야 합니다. 이 문서들만으로는 판단할 수 없습니다.
````

#### RAG (gpt-5.4-nano) — 입력 1,526 / 출력 113 토큰

````text
제공된 문서에서 확인되지 않습니다.  

다만, 문서의 “Intended Use / Out of Scope”에는 **지원 언어 이외로 사용하는 경우**(“Use in languages beyond those explicitly referenced as supported in this model card.”)를 금지하는 내용이 있습니다 [근거 3]. 또한 이 모델은 **텍스트+이미지 입력(이미지 추론/캡셔닝/질의응답)**에 대해 설명되어 있습니다 [근거 1][근거 4].
````

#### RAG (claude-sonnet-5-5) — 입력 2,468 / 출력 703 토큰

````text
지역 제한에 관해서는 제공된 문서에서 확인되지 않습니다.

관련해서 근거에서 확인되는 내용은 다음과 같습니다.
- 라이선스는 llama3.2이며, 사용 전 라이선스 동의가 필요합니다 [근거 1].
- 모델 카드의 Out of Scope 항목에는 무역 규정(trade compliance laws)을 포함해 관련 법령을 위반하는 사용이 들어 있습니다. Acceptable Use Policy와 Llama 3.2 Community License가 금지하는 사용도 포함됩니다 [근거 3]. 이 문서들의 구체적인 조항은 제공된 근거에 없습니다.
- 이미지+텍스트 작업은 영어만 지원합니다. 모델 카드에 명시된 지원 언어 밖에서의 사용은 Out of Scope입니다 [근거 1][근거 3]. 지역 제한은 아니지만 언어 측면의 제약입니다.

지역별 이용 가능 여부는 라이선스 원문과 Acceptable Use Policy를 직접 확인해야 합니다.
````

## 질문 5. 최근 공개된 ibm-granite/granite-4.2-8b 모델의 파라미터 수와 MoE 여부는?

- 선택 모델: `ibm-granite/granite-4.2-8b`
- 판정 근거: 항목 메타데이터: `params_b` = 8.79, `is_moe` = false, `num_experts` = null. granite-4.2-8b 카드 본문 표: "Model Type: Decoder-only Dense Transformer (Reasoning)", "Parameters: 8B", `Model Design` 표의 "8B Dense".
- 참고: 선택 근거: 항목 목록에서 `created_at`이 가장 최근(2026-08-07)인 모델.
- RAG 처리: 카드 검색 문구 `parameter count and mixture of experts (MoE) architecture`, 위키 검색어 `IBM Granite`(collected), `전문가 혼합(MoE)`(reused), `파라미터 수`(collected), 처리 시간 43.5초
- RAG 근거 목록: [근거 1] item / [근거 2] model_card · Model Design / [근거 3] model_card · Stage 2: Supervised Fine-Tuning / [근거 4] model_card · Stage 3: Reinforcement Learning / [근거 5] model_card · Model Design / [근거 6] wiki · 성기게 게이팅된 MoE 층 · 전문가 혼합 / [근거 7] wiki · 트랜스포머 모델에의 응용 · 전문가 혼합 — 인용됨: [1, 2]

| 답변 | 사실 정확성 (판정 근거) | 근거 제시 | 모름을 모른다고 함 |
|---|---|---|---|
| RAG 없이 (haiku) | 판정 대상 사실 진술 없음 — 학습 데이터에 없어 단정할 수 없다고 하고, 이름 해석은 추정임을 밝힘 | 없음 | 예 |
| RAG (haiku) | 맞음 — 8.79B(메타데이터)·8B(카드 표)·Dense 일치, 두 수치 차이도 언급 | 있음 [근거 1][근거 2] | 해당 없음 |
| RAG (gpt-5.4-nano) | 부분 맞음 — 8.79B·Dense 표기는 맞음. 그러나 카드·메타데이터에 Dense가 명시돼 있는데 "MoE 여부는 확인되지 않습니다"라고 함 | 있음 [근거 1] | 과도 (확인 가능한 사실을 확인되지 않는다고 함) |
| RAG (sonnet) | 맞음 — 8.79B·Dense, 카드 Model Design 표의 8B·MLP hidden size 12800·KV heads 8 일치 | 있음 [근거 1][근거 2][근거 5] | 해당 없음 |

#### RAG 없이 (claude-haiku-5-5) — 입력 52 / 출력 1,036 토큰

````text
`ibm-granite/granite-4.2-8b`에 대한 정보는 제가 확인할 수 없습니다. 제 학습 데이터에 이 모델의 공식 발표 내용이 없어서, 파라미터 수나 MoE 여부를 단정해서 알려드리기 어렵습니다.

다만 이름과 기존 Granite 시리즈 구조를 보면 참고할 만한 점은 있습니다. 이름의 "8b"는 보통 총 파라미터가 약 80억이라는 뜻이지만, MoE 모델에서도 이런 표기를 쓸 수 있어서 이름만으로는 구조를 확정할 수 없습니다. 또 Granite 4.0 계열에는 dense 모델과 MoE 기반 하이브리드 모델이 함께 있었으므로, 4.2에서도 두 구조가 모두 있을 가능성이 있습니다.

정확한 정보는 아래에서 직접 확인하시는 것이 가장 확실합니다.

1. **Hugging Face 모델 카드**: 모델 소개와 아키텍처 설명, 공식 발표 링크가 있습니다.
2. **`config.json`**: MoE 여부는 `num_local_experts`(또는 `num_experts`)와 `num_experts_per_tok` 값이 있는지로 판단할 수 있습니다. 이 값이 없거나 1이면 dense 모델일 가능성이 큽니다.
3. **파라미터 수**: HF 모델 페이지의 Safetensors 항목에 표시된 총 파라미터 수를 보면 됩니다. MoE라면 총 파라미터와 활성 파라미터(active parameters)가 다를 수 있으니 둘 다 확인하세요.
4. **IBM 공식 블로그나 release notes**: 새 모델의 구조와 벤치마크가 정리되어 있을 가능성이 높습니다.

원하시면 `config.json`의 항목을 붙여 주셨을 때 구조를 해석하는 것을 도와드릴 수 있습니다.
````

#### RAG (claude-haiku-5-5) — 입력 3,769 / 출력 662 토큰

````text
**파라미터 수:** 항목 메타데이터에 따르면 파라미터는 8.79B입니다 [근거 1]. 모델 카드의 구조 비교표에서도 해당 모델 열의 파라미터 수는 8B로 표기되어 있습니다 [근거 2]. 두 문서가 서로 다른 표기를 쓰고 있으며, 문서에서는 그 차이를 설명하지 않습니다.

**MoE 여부:** 메타데이터에서 구조는 "Dense"로 명시되어 있습니다 [근거 1]. 따라서 이 모델은 MoE가 아닌 Dense 구조로 기재되어 있습니다.

참고로 근거 6과 7은 MoE 일반에 관한 위키백과 내용이라 이 모델의 구조를 설명하지 않습니다.
````

#### RAG (gpt-5.4-nano) — 입력 2,372 / 출력 84 토큰

````text
`ibm-granite/granite-4.2-8b`의 파라미터 수는 **8.79B**입니다 [근거 1]. 또한 모델 구조는 **Dense**로 표기되어 있어, 문서 기준으로 **MoE 여부는 확인되지 않습니다**(MoE라고 명시되어 있지 않음) [근거 1].
````

#### RAG (claude-sonnet-5-5) — 입력 3,769 / 출력 298 토큰

````text
ibm-granite/granite-4.2-8b의 파라미터 수는 8.79B이고, 구조는 Dense로 MoE가 아닙니다 [근거 1].

- 소개 문구에도 이 모델이 디코더 전용 Dense 추론 모델이라고 되어 있습니다 [근거 1].
- 모델 카드의 Model Design 표에는 3B, 8B, 30B 세 가지 크기가 함께 나옵니다. 8B 열은 파라미터 수를 "8B"로, MLP hidden size를 12800, KV heads 수를 8로 적고 있습니다 [근거 2][근거 5].

MoE 여부를 따로 명시한 문장이 표에서 확인되지는 않습니다. 다만 메타데이터의 구조 항목이 Dense로 기재되어 있습니다 [근거 1].
````


## 머리말 색인 후 (2026-10-22, 색인 규칙 v2)

> 카드 머리말의 정해 둔 키를 `section="front_matter"` 조각으로 색인하고, 저가치 소제목(Citation·Contributors·Table of Contents·Contact 등)의 청크를 뺀 뒤 다시 실행한 결과. 답변 모델 `claude-haiku-5-5`, 카드 4 + 위키 2. 위 기존 결과는 그대로 둔다.

### 이 모델은 MoE 구조야? 상업적으로 써도 되는 라이선스야? (`kakaocorp/kanana-1.5-8b-instruct-2505`)

- 카드 검색 문구: `mixture of experts architecture license Apache-2.0 commercial use`
- 근거 목록: [근거 1] item / [근거 2] model_card · front_matter / [근거 3] model_card · Instruct Model Evaluation / [근거 4] model_card · Base Model Evaluation / [근거 5] model_card / [근거 6] wiki · 트랜스포머 모델에의 응용 / [근거 7] wiki · 추가 읽을거리 — 인용됨: [1, 2]
- 토큰: 입력 3,451 / 출력 654

````text
**MoE 구조 여부:** 제공된 문서에서 이 모델은 MoE가 아닌 **Dense** 구조로 되어 있습니다 [근거 1]. 파라미터는 8.03B입니다 [근거 1]. 근거 6과 7은 전문가 혼합(MoE) 일반에 관한 위키백과 내용으로, 이 모델에 대한 설명은 아닙니다.

**라이선스:** 근거 문서에 적힌 라이선스는 **apache-2.0**입니다 [근거 1][근거 2]. 제공된 문서에는 이 라이선스의 상업적 이용 조건을 자세히 설명한 내용이 없으므로, 적용 여부는 Apache-2.0 라이선스 원문과 모델 저장소의 라이선스 정보를 직접 확인하시기 바랍니다.
````

### Llama 3.2 11B Vision을 이미지 입력용으로 쓸 때 지역 제한이 있나? (`meta-llama/Llama-3.2-11B-Vision-Instruct`)

- 카드 검색 문구: `image input regional restrictions usage policy`
- 근거 목록: [근거 1] item / [근거 2] model_card · New Capabilities and Use Cases / [근거 3] model_card · front_matter / [근거 4] model_card · Intended Use / [근거 5] model_card · front_matter — 인용됨: [1, 2, 3, 4, 5]
- 토큰: 입력 2,342 / 출력 958

````text
네, 근거 문서에는 EU 관련 지역 제한이 있습니다. 멀티모달 모델에 대해 Llama 3.2 Community License 1(a)조에서 부여되는 권리는 **EU에 주소(domicile)를 둔 개인이나 EU에 주된 영업소(principal place of business)를 둔 기업에는 부여되지 않는다고 명시되어 있습니다** [근거 3]. 다만 이 제한은 해당 멀티모달 모델을 포함한 제품이나 서비스의 **최종 사용자**에게는 적용되지 않는다고 적혀 있습니다 [근거 3].

이미지 입력과 관련해 함께 확인할 조건은 다음과 같습니다.

- **라이선스 동의**: 라이선스는 llama3.2이며 사용 전 동의가 필요합니다 [근거 1].
- **지원 언어**: 이미지+텍스트 작업은 영어만 공식 지원됩니다 [근거 1]. 모델 카드도 명시적으로 지원된다고 적힌 언어 밖의 사용을 범위 밖(Out of Scope)으로 둡니다 [근거 4].
- **이미지 속 개인 식별**: 모델이 이미지 속 개인을 식별하는 위험에 대해 평가와 완화 조치를 했다고 되어 있으며, 개발자가 응용 분야에서 식별 위험을 평가하고 Llama Guard 3-11B-Vision 배포 등을 고려하라고 권고합니다 [근거 2].
- **사용 정책**: 금지된 용도(예: 폭력이나 테러, 아동 착취 관련 콘텐츠 등)는 Acceptable Use Policy에 정해져 있습니다 [근거 5].

EU 제한이 귀사나 서비스에 실제로 어떻게 적용되는지는 제공된 문서만으로는 판단할 수 없습니다. 라이선스 전문과 적용 여부는 법무 검토를 거치시기를 권합니다.
````

**변화:** kanana 질문은 카드 근거 4개가 Instruct Model Evaluation / Citation / Table of Contents / Contributors → front_matter / Instruct Model Evaluation / Base Model Evaluation / (소제목 없음)으로 바뀌었고, 라이선스 apache-2.0을 메타데이터와 함께 머리말 조각으로도 인용했다. Llama 질문은 머리말 조각 2개(`extra_gated_prompt`의 라이선스 전문 일부)가 근거에 들어와, 이전에 "확인되지 않습니다"였던 EU 이용 제한을 근거 번호와 함께 답했다. 사실 정확성: Llama 답변의 EU 제한 내용은 카드 머리말 `extra_gated_prompt` 문구와 일치 (머리말이 이제 색인 대상이므로 판정 근거로 사용).
