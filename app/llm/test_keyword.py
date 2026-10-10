import asyncio
import json
from pathlib import Path

import pytest

from app.llm.keyword import BROKEN_RESPONSES, KeywordLLMClient
from app.llm.prompts import build_classification_prompt
from app.llm.validation import ClassificationError, parse_classification


def classify(client: KeywordLLMClient, prompt: str) -> str:
    return asyncio.run(client.classify(prompt))


SAMPLES_PATH = Path(__file__).parents[2] / "sample_data" / "tickets.json"


def keyword_classification(client: KeywordLLMClient, subject: str, body: str):
    return parse_classification(
        classify(client, build_classification_prompt(subject, body))
    )


def test_keyword_client_returns_valid_plausible_classifications_for_samples():
    client = KeywordLLMClient()
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


def test_keyword_client_returns_a_broken_response_every_nth_call():
    client = KeywordLLMClient(broken_every=2)
    prompt = build_classification_prompt("Charged twice", "Please refund")

    outputs = [classify(client, prompt) for _ in range(4)]

    assert parse_classification(outputs[0]).category == "billing"
    assert parse_classification(outputs[2]).category == "billing"
    for broken in (outputs[1], outputs[3]):
        with pytest.raises(ClassificationError):
            parse_classification(broken)


def test_keyword_client_cycles_through_every_kind_of_broken_response():
    client = KeywordLLMClient(broken_every=1)
    prompt = build_classification_prompt("Charged twice", "Please refund")

    outputs = [classify(client, prompt) for _ in range(len(BROKEN_RESPONSES))]

    assert outputs == list(BROKEN_RESPONSES)


@pytest.mark.parametrize("broken", BROKEN_RESPONSES)
def test_every_broken_response_is_rejected_by_validation(broken):
    with pytest.raises(ClassificationError):
        parse_classification(broken)


def test_keyword_client_summary_is_a_single_line():
    client = KeywordLLMClient()

    result = keyword_classification(client, "", "Line one\nline two\r\nline three")

    assert result.summary == "Customer wrote in about: Line one line two line three."
