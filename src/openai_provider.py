"""Small OpenAI Responses API adapter for tool-calling orchestration."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Mapping

import openai
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    InternalServerError,
    NotFoundError,
    OpenAI,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)


OPENAI_SDK_VERSION = openai.__version__
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_OUTPUT_TOKENS = 800
DEFAULT_RETRY_DELAY_SECONDS = 0.0

_NON_RETRYABLE_ERRORS = (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    UnprocessableEntityError,
)
_TRANSIENT_ERRORS = (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)


def _provider_failure(code: str, message: str) -> dict[str, Any]:
    return {
        "success": False,
        "response_id": None,
        "function_calls": [],
        "output_text": None,
        "refusal": None,
        "error": {"code": code, "message": message},
    }


def _get_value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _is_transient_provider_error(exc: Exception) -> bool:
    if isinstance(exc, _TRANSIENT_ERRORS):
        return True
    if isinstance(exc, APIStatusError):
        status_code = getattr(exc, "status_code", None)
        return isinstance(status_code, int) and status_code >= 500
    return False


class OpenAIProvider:
    """Normalize the installed OpenAI SDK behind a testable provider boundary."""

    provider_name = "openai"

    def __init__(
        self,
        client: Any,
        model: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.retry_delay_seconds = retry_delay_seconds
        self._sleep = sleep

    def generate(
        self,
        *,
        instructions: str,
        input_data: str | list[dict[str, Any]],
        tools: list[dict[str, Any]],
        previous_response_id: str | None = None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": input_data,
            "tools": tools,
            "tool_choice": "auto",
            "max_output_tokens": self.max_output_tokens,
            "timeout": self.timeout_seconds,
        }
        if previous_response_id is not None:
            request["previous_response_id"] = previous_response_id

        for attempt in range(2):
            try:
                response = self.client.responses.create(**request)
                return self._normalize_response(response)
            except _NON_RETRYABLE_ERRORS:
                return _provider_failure(
                    "provider_error",
                    "The OpenAI request was rejected and was not retried.",
                )
            except Exception as exc:
                if attempt == 0 and _is_transient_provider_error(exc):
                    if self.retry_delay_seconds > 0:
                        self._sleep(self.retry_delay_seconds)
                    continue
                return _provider_failure(
                    "provider_error",
                    "The OpenAI provider is temporarily unavailable.",
                )

        return _provider_failure(
            "provider_error", "The OpenAI provider is temporarily unavailable."
        )

    def _normalize_response(self, response: Any) -> dict[str, Any]:
        response_id = _get_value(response, "id")
        output = _get_value(response, "output")
        response_error = _get_value(response, "error")
        if response_error is not None:
            return _provider_failure(
                "provider_error", "The OpenAI provider could not complete the response."
            )
        if not isinstance(response_id, str) or not response_id.strip():
            return _provider_failure(
                "provider_response_invalid",
                "The OpenAI provider returned an invalid response identifier.",
            )
        if not isinstance(output, (list, tuple)):
            return _provider_failure(
                "provider_response_invalid",
                "The OpenAI provider returned malformed output.",
            )

        function_calls: list[dict[str, Any]] = []
        refusals: list[str] = []
        fallback_text: list[str] = []
        for item in output:
            item_type = _get_value(item, "type")
            if item_type == "function_call":
                call_id = _get_value(item, "call_id")
                name = _get_value(item, "name")
                arguments = _get_value(item, "arguments")
                if not isinstance(call_id, str) or not call_id.strip():
                    return _provider_failure(
                        "provider_response_invalid",
                        "The OpenAI provider returned a tool call without a call ID.",
                    )
                if not isinstance(name, str) or not name.strip():
                    return _provider_failure(
                        "provider_response_invalid",
                        "The OpenAI provider returned a tool call without a valid name.",
                    )
                arguments_valid = isinstance(arguments, dict)
                if isinstance(arguments, str):
                    try:
                        arguments_valid = isinstance(json.loads(arguments), dict)
                    except json.JSONDecodeError:
                        arguments_valid = False
                function_calls.append(
                    {
                        "call_id": call_id,
                        "name": name,
                        "arguments": arguments,
                        "arguments_valid": arguments_valid,
                    }
                )
            elif item_type == "message":
                content = _get_value(item, "content", [])
                if isinstance(content, (list, tuple)):
                    for content_item in content:
                        content_type = _get_value(content_item, "type")
                        if content_type == "output_text":
                            text = _get_value(content_item, "text")
                            if isinstance(text, str) and text.strip():
                                fallback_text.append(text.strip())
                        elif content_type == "refusal":
                            refusal = _get_value(content_item, "refusal")
                            if isinstance(refusal, str) and refusal.strip():
                                refusals.append(refusal.strip())

        output_text = _get_value(response, "output_text")
        if not isinstance(output_text, str) or not output_text.strip():
            output_text = "\n".join(fallback_text).strip() or None
        else:
            output_text = output_text.strip()

        if refusals:
            return {
                **_provider_failure(
                    "provider_refusal",
                    "The OpenAI provider declined to answer this request.",
                ),
                "response_id": response_id,
                "refusal": "Provider refusal",
            }
        if not function_calls and output_text is None:
            return _provider_failure(
                "provider_response_invalid",
                "The OpenAI provider returned no usable output.",
            )
        return {
            "success": True,
            "response_id": response_id,
            "function_calls": function_calls,
            "output_text": output_text,
            "refusal": None,
            "error": None,
        }


def create_openai_provider(
    *,
    api_key: str | None = None,
    model: str | None = None,
    environment: Mapping[str, str] | None = None,
    client_factory: Callable[..., Any] = OpenAI,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Construct a real provider only from explicit or environment configuration."""

    config = os.environ if environment is None else environment
    resolved_key = api_key if api_key is not None else config.get("OPENAI_API_KEY")
    resolved_model = model if model is not None else config.get("OPENAI_MODEL")
    if not isinstance(resolved_key, str) or not resolved_key.strip():
        return {
            "success": False,
            "provider": None,
            "model": resolved_model.strip() if isinstance(resolved_model, str) else None,
            "error": {
                "code": "configuration_error",
                "message": "OPENAI_API_KEY is not configured.",
            },
        }
    if not isinstance(resolved_model, str) or not resolved_model.strip():
        return {
            "success": False,
            "provider": None,
            "model": None,
            "error": {
                "code": "configuration_error",
                "message": "OPENAI_MODEL is not configured.",
            },
        }

    try:
        client = client_factory(
            api_key=resolved_key.strip(),
            timeout=timeout_seconds,
            max_retries=0,
        )
    except Exception:
        return {
            "success": False,
            "provider": None,
            "model": resolved_model.strip(),
            "error": {
                "code": "provider_error",
                "message": "The OpenAI client could not be initialized.",
            },
        }

    return {
        "success": True,
        "provider": OpenAIProvider(
            client,
            resolved_model.strip(),
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
            retry_delay_seconds=retry_delay_seconds,
            sleep=sleep,
        ),
        "model": resolved_model.strip(),
        "error": None,
    }
