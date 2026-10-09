import asyncio
import json
from pathlib import Path

import pytest

from app.llm.client import LLMClient
from app.llm.fake import (
    EMPTY_SUMMARY_RESPONSE,
    INVALID_CATEGORY_RESPONSE,
    INVALID_PRIORITY_RESPONSE,
    MALFORMED_JSON_RESPONSE,
    VALID_RESPONSE,
    FakeLLMClient,
    KeywordFakeLLMClient,
)
from app.llm.prompts import build_classification_prompt
from app.llm.validation import ClassificationError, parse_classification


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


SAMPLES_PATH = Path(__file__).parents[2] / "sample_data" / "tickets.json"


def keyword_classification(client: KeywordFakeLLMClient, subject: str, body: str):
    return parse_classification(
        classify(client, build_classification_prompt(subject, body))
    )


def test_keyword_fake_returns_valid_plausible_classifications_for_samples():
    client = KeywordFakeLLMClient()
    samples = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))

    results = {
        ticket["id"]: keyword_classification(client, ticket["subject"], ticket["body"])
        for ticket in samples
    }

    assert {
        ticket_id: (r.category, r.priority) for ticket_id, r in results.items()
    } == {
        "t-1001": ("billing", "medium"),
        "t-1002": ("account", "medium"),
        "t-1003": ("technical", "high"),
        "t-1004": ("account", "medium"),
        "t-1005": ("billing", "high"),
        "t-1006": ("other", "low"),
        "t-1007": ("billing", "medium"),
        "t-1008": ("other", "medium"),
        "t-1009": ("technical", "medium"),
        "t-1010": ("technical", "medium"),
    }
    assert (
        results["t-1001"].summary
        == "Customer wrote in about: Charged twice this month."
    )
    assert results["t-1008"].summary == "Customer wrote in about: asdf."


def test_keyword_fake_returns_malformed_json_every_nth_call():
    client = KeywordFakeLLMClient(broken_every=2)
    prompt = build_classification_prompt("Charged twice", "Please refund")

    outputs = [classify(client, prompt) for _ in range(4)]

    assert outputs[1] == MALFORMED_JSON_RESPONSE
    assert outputs[3] == MALFORMED_JSON_RESPONSE
    assert parse_classification(outputs[0]).category == "billing"
    with pytest.raises(ClassificationError):
        parse_classification(outputs[1])
