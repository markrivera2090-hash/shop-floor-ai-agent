"""Fake-client tests for the OpenAI Responses API adapter."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx2
import pytest
from openai import APITimeoutError, AuthenticationError, BadRequestError

from src.openai_provider import OpenAIProvider, create_openai_provider
from src.tool_registry import TOOL_SCHEMAS


class FakeResponses:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, scripted):
        self.responses = FakeResponses(scripted)


def fake_response(response_id="resp_1", output=None, output_text=None, error=None):
    return SimpleNamespace(
        id=response_id,
        output=[] if output is None else output,
        output_text=output_text,
        error=error,
    )


def function_call(name="get_panel", arguments='{"panel_code":"P-1001"}', call_id="call_1"):
    return SimpleNamespace(
        type="function_call", name=name, arguments=arguments, call_id=call_id
    )


def test_model_tools_system_and_user_input_are_sent_to_responses_api():
    client = FakeClient([fake_response(output_text="Done")])
    provider = OpenAIProvider(client, "test-model", timeout_seconds=7, max_output_tokens=321)

    result = provider.generate(
        instructions="System safety instructions",
        input_data="Operator input",
        tools=TOOL_SCHEMAS,
    )
    sent = client.responses.calls[0]

    assert result["success"] is True
    assert sent["model"] == "test-model"
    assert sent["instructions"] == "System safety instructions"
    assert sent["input"] == "Operator input"
    assert sent["tools"] == TOOL_SCHEMAS
    assert sent["tool_choice"] == "auto"
    assert sent["timeout"] == 7
    assert sent["max_output_tokens"] == 321


def test_function_call_items_are_normalized_and_arguments_are_checked():
    client = FakeClient([fake_response(output=[function_call()])])
    provider = OpenAIProvider(client, "test-model")

    result = provider.generate(instructions="safe", input_data="input", tools=TOOL_SCHEMAS)

    assert result["function_calls"] == [
        {
            "call_id": "call_1",
            "name": "get_panel",
            "arguments": '{"panel_code":"P-1001"}',
            "arguments_valid": True,
        }
    ]


def test_malformed_function_arguments_are_detected_without_raw_failure():
    client = FakeClient([fake_response(output=[function_call(arguments="{")])])
    provider = OpenAIProvider(client, "test-model")

    result = provider.generate(instructions="safe", input_data="input", tools=TOOL_SCHEMAS)

    assert result["success"] is True
    assert result["function_calls"][0]["arguments_valid"] is False


def test_function_call_outputs_use_previous_response_id_on_next_turn():
    client = FakeClient([fake_response(output_text="Final")])
    provider = OpenAIProvider(client, "test-model")
    outputs = [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": '{"success":true}',
        }
    ]

    provider.generate(
        instructions="safe",
        input_data=outputs,
        tools=TOOL_SCHEMAS,
        previous_response_id="resp_previous",
    )
    sent = client.responses.calls[0]

    assert sent["input"] == outputs
    assert sent["previous_response_id"] == "resp_previous"
    assert sent["instructions"] == "safe"


def test_final_response_text_is_normalized_from_output_text():
    provider = OpenAIProvider(FakeClient([fake_response(output_text="  Final answer  ")]), "m")

    result = provider.generate(instructions="safe", input_data="input", tools=[])

    assert result["output_text"] == "Final answer"
    assert result["function_calls"] == []


def test_final_text_can_be_read_from_message_content():
    message = SimpleNamespace(
        type="message",
        content=[SimpleNamespace(type="output_text", text="Grounded answer")],
    )
    provider = OpenAIProvider(FakeClient([fake_response(output=[message])]), "m")

    result = provider.generate(instructions="safe", input_data="input", tools=[])

    assert result["output_text"] == "Grounded answer"


@pytest.mark.parametrize(
    "response",
    [
        fake_response(output=[]),
        SimpleNamespace(id="resp", output=None, output_text=None, error=None),
        fake_response(response_id=None, output_text="answer"),
    ],
)
def test_missing_or_malformed_provider_output_fails_safely(response):
    provider = OpenAIProvider(FakeClient([response]), "m")

    result = provider.generate(instructions="safe", input_data="input", tools=[])

    assert result["success"] is False
    assert result["error"]["code"] == "provider_response_invalid"


def test_missing_call_id_fails_safely():
    provider = OpenAIProvider(
        FakeClient([fake_response(output=[function_call(call_id=None)])]), "m"
    )

    result = provider.generate(instructions="safe", input_data="input", tools=[])

    assert result["error"]["code"] == "provider_response_invalid"


def test_provider_refusal_is_detected_and_sanitized():
    refusal_message = SimpleNamespace(
        type="message",
        content=[SimpleNamespace(type="refusal", refusal="Sensitive raw refusal")],
    )
    provider = OpenAIProvider(FakeClient([fake_response(output=[refusal_message])]), "m")

    result = provider.generate(instructions="safe", input_data="input", tools=[])

    assert result["success"] is False
    assert result["error"]["code"] == "provider_refusal"
    assert "Sensitive raw refusal" not in json.dumps(result)


def test_transient_timeout_retries_at_most_once():
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    client = FakeClient([APITimeoutError(request), fake_response(output_text="Recovered")])
    sleeps = []
    provider = OpenAIProvider(client, "m", retry_delay_seconds=0.01, sleep=sleeps.append)

    result = provider.generate(instructions="safe", input_data="input", tools=[])

    assert result["success"] is True
    assert len(client.responses.calls) == 2
    assert sleeps == [0.01]


def test_repeated_transient_failure_stops_after_one_retry():
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    client = FakeClient([APITimeoutError(request), APITimeoutError(request)])
    provider = OpenAIProvider(client, "m")

    result = provider.generate(instructions="safe", input_data="input", tools=[])

    assert result["error"]["code"] == "provider_error"
    assert len(client.responses.calls) == 2


@pytest.mark.parametrize("error_class", [AuthenticationError, BadRequestError])
def test_authentication_and_invalid_requests_are_not_retried(error_class):
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx2.Response(401, request=request)
    provider_error = error_class("secret provider detail", response=response, body=None)
    client = FakeClient([provider_error])
    provider = OpenAIProvider(client, "m")

    result = provider.generate(instructions="safe", input_data="input", tools=[])

    assert result["error"]["code"] == "provider_error"
    assert len(client.responses.calls) == 1
    assert "secret provider detail" not in json.dumps(result)


def test_provider_errors_and_fake_secret_are_sanitized(capsys):
    fake_secret = "sk-fake-secret-that-must-not-leak"
    client = FakeClient([RuntimeError(fake_secret)])
    provider = OpenAIProvider(client, "m")

    result = provider.generate(instructions="safe", input_data="input", tools=[])
    captured = capsys.readouterr()

    assert fake_secret not in json.dumps(result)
    assert fake_secret not in captured.out
    assert fake_secret not in captured.err


def test_missing_api_key_returns_configuration_error():
    result = create_openai_provider(environment={"OPENAI_MODEL": "test-model"})

    assert result["success"] is False
    assert result["error"]["code"] == "configuration_error"


def test_missing_model_returns_configuration_error():
    result = create_openai_provider(environment={"OPENAI_API_KEY": "fake-key"})

    assert result["success"] is False
    assert result["error"]["code"] == "configuration_error"


def test_explicit_empty_environment_does_not_inherit_real_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-looking-parent-value")
    monkeypatch.setenv("OPENAI_MODEL", "parent-model")

    result = create_openai_provider(environment={})

    assert result["success"] is False
    assert result["error"]["code"] == "configuration_error"


def test_real_client_construction_disables_sdk_retries_and_keeps_secret_private():
    captured = {}

    def factory(**kwargs):
        captured.update(kwargs)
        return FakeClient([])

    result = create_openai_provider(
        api_key="sk-fake-build-key",
        model="test-model",
        environment={},
        client_factory=factory,
        timeout_seconds=9,
    )

    assert result["success"] is True
    assert captured == {
        "api_key": "sk-fake-build-key",
        "timeout": 9,
        "max_retries": 0,
    }
    assert not hasattr(result["provider"], "api_key")
