"""작업별 LLM 생성 (design/models.md). 제공사·모델은 설정 키(LLM_SUMMARY, LLM_SMALL, LLM_ANSWER)로 고른다.

- 기본값은 config/llm.json 의 프로필(profiles) 중 active_profile 의 tasks.
- 프로필은 환경 변수 LLM_PROFILE 로 바꾼다. 기본 프로필 anthropic_direct 는 Anthropic API 직접 호출 (키 ANTHROPIC_API_KEY)
- 작업별 모델은 환경 변수로 바꿀 수 있다: LLM_SUMMARY="anthropic:claude-sonnet-5-5" 처럼 "제공사:모델".
- 모델별 옵션(model_options, 예: thinking 끄기)은 모델 이름 기준으로 모든 프로필에 적용한다. 작업 설정의 같은 키가 우선.
- LLM 클라이언트는 같은 설정이면 프로세스당 1개만 만들어 다시 쓴다.
모델 이름을 코드에 쓰지 않는다.
"""
import json
import os
from functools import lru_cache

from common.config import llm_config
from common.logs import get_logger


class MissingApiKey(RuntimeError):
    """API 키 환경 변수가 비어 있다. 메시지에는 변수 이름만 담는다."""


class TruncatedOutput(RuntimeError):
    """구조화 출력이 출력 상한(max_tokens)에서 잘렸다. 일부만 파싱될 수 있으므로 결과를 쓰지 않는다."""


def profile_name():
    return os.environ.get("LLM_PROFILE") or llm_config()["active_profile"]


def profile():
    return llm_config()["profiles"][profile_name()]


def task_config(task):
    cfg = dict(profile()["tasks"][task])
    override = os.environ.get(task)
    if override:
        provider, _, model = override.partition(":")
        cfg.update(provider=provider, model=model)
    return cfg


def model_name(task):
    return task_config(task)["model"]


def missing_api_keys(tasks=("LLM_SMALL", "LLM_ANSWER")):
    """비어 있는 API 키 환경 변수 이름 목록 (화면 안내용, 값은 다루지 않는다)."""
    names = {profile()["providers"][task_config(t)["provider"]]["api_key_env"] for t in tasks}
    return sorted(n for n in names if not os.environ.get(n))


def get_llm(task):
    cfg = task_config(task)
    provider = profile()["providers"][cfg["provider"]]
    if not os.environ.get(provider["api_key_env"]):
        raise MissingApiKey(provider["api_key_env"])
    extra = {**llm_config().get("model_options", {}).get(cfg["model"], {}),
             **{k: v for k, v in cfg.items() if k not in ("provider", "model")}}
    return _client(cfg["provider"], cfg["model"], provider["base_url"], provider["api_key_env"],
                   json.dumps(extra, sort_keys=True))


@lru_cache
def _client(provider, model, base_url, api_key_env, extra_json):
    """설정이 같으면 같은 클라이언트를 돌려준다 (키 값은 캐시 키에 넣지 않는다). 옵션은 캐시 키로 쓰려고 JSON 문자열로 받는다."""
    kwargs = {"model": model, "api_key": os.environ[api_key_env], **json.loads(extra_json)}
    if base_url:
        kwargs["base_url"] = base_url
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(**kwargs)
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(**kwargs)
    raise ValueError(f"지원하지 않는 제공사: {provider}")


def structured_output_method(task):
    """모델별 구조화 출력 방식 (function_calling / json_schema). config/llm.json 에서만 정한다."""
    cfg = llm_config()["structured_output_method"]
    return cfg["models"].get(model_name(task), cfg["default"])


def get_structured_llm(task, schema):
    """구조화 출력 LLM. 결과는 {"raw", "parsed", "parsing_error"} (토큰 사용량 확인용으로 raw 포함)."""
    return get_llm(task).with_structured_output(schema, method=structured_output_method(task), include_raw=True)


def is_truncated(raw):
    """응답이 출력 상한에서 잘렸는지. Anthropic: stop_reason == "max_tokens", OpenAI 호환: finish_reason == "length"."""
    meta = getattr(raw, "response_metadata", None) or {}
    return meta.get("stop_reason") == "max_tokens" or meta.get("finish_reason") == "length"


def check_truncated(out, task, prompt_name):
    """구조화 출력 결과({"raw", ...})가 잘렸으면 로그(프롬프트 이름·모델·출력 토큰)를 남기고 TruncatedOutput.
    파싱이 성공했어도 쓰지 않는다 (json_schema 방식은 잘린 출력을 오류 없이 부분 파싱한 사례가 있음)."""
    raw = out["raw"]
    if is_truncated(raw):
        usage = getattr(raw, "usage_metadata", None) or {}
        get_logger().warning("구조화 출력 잘림: prompt=%s model=%s output_tokens=%s",
                             prompt_name, model_name(task), usage.get("output_tokens"))
        raise TruncatedOutput(f"{prompt_name} 출력이 잘림")
    return out


def invoke_structured(task, schema, prompt_input, prompt_name):
    """구조화 출력 호출 + 잘림 확인. 반환: {"raw", "parsed", "parsing_error"}"""
    return check_truncated(get_structured_llm(task, schema).invoke(prompt_input), task, prompt_name)
