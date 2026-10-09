import asyncio
import json

import pytest

from app.llm.client import LLMClient
from app.llm.fake import (
    EMPTY_SUMMARY_RESPONSE,
    INVALID_CATEGORY_RESPONSE,
    INVALID_PRIORITY_RESPONSE,
    MALFORMED_JSON_RESPONSE,
    VALID_RESPONSE,
    FakeLLMClient,
)


def classify(client: LLMClient, prompt: str = "prompt") -> str:
    return asyncio.run(client.classify(prompt))


def test_returns_scripted_responses_in_order():
    client = FakeLLMClient([VALID_RESPONSE, MALFORMED_JSON_RESPONSE])

    assert classify(client) == VALID_RESPONSE
    assert classify(client) == MALFORMED_JSON_RESPONSE


def test_records_prompts_it_receives():
    client = FakeLLMClient([VALID_RESPONSE, VALID_RESPONSE])

    classify(client, "first")
    classify(client, "second")

    assert client.prompts == ["first", "second"]


def test_raises_scripted_exception():
    client = FakeLLMClient([TimeoutError("model timed out"), VALID_RESPONSE])

    with pytest.raises(TimeoutError, match="model timed out"):
        classify(client)
    assert classify(client) == VALID_RESPONSE


def test_raises_when_scripted_responses_are_exhausted():
    client = FakeLLMClient([])

    with pytest.raises(RuntimeError, match="no scripted responses left"):
        classify(client)


def test_valid_response_is_well_formed_classification_json():
    assert json.loads(VALID_RESPONSE) == {
        "category": "billing",
        "priority": "high",
        "summary": "Customer was charged twice.",
    }


def test_malformed_response_is_not_parseable_json():
    with pytest.raises(json.JSONDecodeError):
        json.loads(MALFORMED_JSON_RESPONSE)


@pytest.mark.parametrize(
    ("response", "field", "value"),
    [
        (INVALID_CATEGORY_RESPONSE, "category", "refunds"),
        (INVALID_PRIORITY_RESPONSE, "priority", "urgent"),
        (EMPTY_SUMMARY_RESPONSE, "summary", ""),
    ],
)
def test_invalid_responses_differ_from_valid_response_only_in_one_field(
    response, field, value
):
    assert json.loads(response) == json.loads(VALID_RESPONSE) | {field: value}
