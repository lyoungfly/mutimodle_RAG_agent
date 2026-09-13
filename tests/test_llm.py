import json

import httpx
import pytest

from papermind.errors import ModelResponseError
from papermind.llm.client import CompatibleLLM
from papermind.llm.response import parse_completion


def install_transport(monkeypatch, handler):
    original_client = httpx.Client
    monkeypatch.setattr(
        "papermind.llm.client.httpx.Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    monkeypatch.setattr("papermind.llm.client.time.sleep", lambda duration: None)


def test_retries_transient_server_error(monkeypatch):
    attempts = []

    def handler(request):
        attempts.append(request)
        if len(attempts) < 3:
            return httpx.Response(503)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"abstain":true}'}}]}
        )

    install_transport(monkeypatch, handler)
    assert CompatibleLLM("http://model/v1", "test").answer("Question", []) == {
        "abstain": True
    }
    assert len(attempts) == 3


def test_auth_error_is_not_retried(monkeypatch):
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(401)

    install_transport(monkeypatch, handler)
    with pytest.raises(RuntimeError):
        CompatibleLLM("http://model/v1", "test").answer("Question", [])
    assert len(attempts) == 1


@pytest.mark.parametrize(
    "body", [{}, {"choices": []}, {"choices": [{"message": {"content": "not-json"}}]}]
)
def test_malformed_response_is_explicit(monkeypatch, body):
    install_transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(ModelResponseError):
        CompatibleLLM("http://model/v1", "test").answer("Question", [])


@pytest.mark.parametrize(
    "content",
    [
        '{"abstain":true}',
        '\ufeff {"abstain":true}',
        '```json\n{"abstain":true}\n```',
        '```\n{"abstain":true}\n```',
        [{"type": "text", "text": '{"abstain":true}'}],
    ],
)
def test_supported_json_wrappers(content):
    assert parse_completion({"choices": [{"message": {"content": content}}]}) == {
        "abstain": True
    }


@pytest.mark.parametrize(
    "content",
    [
        'Here is the result: {"abstain":true}',
        '<think>{"abstain":true}</think>',
        "[]",
        '```json\n{"abstain":true}\n```\nextra text',
        [{"type": "image_url", "image_url": {}}],
    ],
)
def test_does_not_guess_json_from_invalid_content(content):
    with pytest.raises(ModelResponseError):
        parse_completion({"choices": [{"message": {"content": content}}]})


@pytest.mark.parametrize(
    "finish_reason,content",
    [("length", '{"abstain":true}'), ("stop", ""), ("stop", "not-json")],
)
def test_incomplete_output_is_retried_with_bounded_budget(
    monkeypatch, finish_reason, content
):
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": finish_reason,
                            "message": {
                                "content": content,
                                "reasoning_content": "do not parse this",
                            },
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"abstain":true}'},
                    }
                ]
            },
        )

    install_transport(monkeypatch, handler)
    assert CompatibleLLM("http://model/v1", "test").answer("Question", []) == {
        "abstain": True
    }
    assert len(payloads) == 2
    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert payloads[1]["max_tokens"] == (8192 if finish_reason == "length" else 4096)


def test_exhausted_truncation_has_clear_error(monkeypatch):
    budgets = []

    def handler(request):
        budgets.append(json.loads(request.content)["max_tokens"])
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "length", "message": {"content": ""}}]},
        )

    install_transport(monkeypatch, handler)
    with pytest.raises(ModelResponseError, match="截断"):
        CompatibleLLM("http://model/v1", "test").answer("Question", [])
    assert budgets == [4096, 8192, 8192]


@pytest.mark.parametrize(
    "message,expected_attempts",
    [("response_format json_object is not supported", 2), ("Invalid model ID", 1)],
)
def test_only_explicitly_unsupported_json_mode_can_fall_back(
    monkeypatch, message, expected_attempts
):
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return httpx.Response(400, json={"error": {"message": message}})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '```json\n{"abstain":true}\n```'}}]
            },
        )

    install_transport(monkeypatch, handler)
    llm = CompatibleLLM("http://model/v1", "test")
    if expected_attempts == 1:
        with pytest.raises(RuntimeError):
            llm.answer("Question", [])
    else:
        assert llm.answer("Question", []) == {"abstain": True}
        assert "response_format" not in payloads[1]
        assert payloads[0]["messages"] == payloads[1]["messages"]
    assert len(payloads) == expected_attempts


def test_refusal_is_not_retried_or_parsed(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"refusal": "blocked", "content": '{"abstain":false}'}}
                ]
            },
        )

    install_transport(monkeypatch, handler)
    with pytest.raises(ModelResponseError, match="拒绝"):
        CompatibleLLM("http://model/v1", "test").answer("Question", [])
    assert len(requests) == 1
