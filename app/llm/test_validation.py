import json

import pytest

from app.api.schemas import TicketCategory, TicketPriority
from app.llm.fake import (
    EMPTY_SUMMARY_RESPONSE,
    INVALID_CATEGORY_RESPONSE,
    INVALID_PRIORITY_RESPONSE,
    MALFORMED_JSON_RESPONSE,
    VALID_RESPONSE,
)
from app.llm.validation import (
    ClassificationError,
    ClassificationResult,
    parse_classification,
)

VALID_OUTPUT = {
    "category": "billing",
    "priority": "high",
    "summary": "Customer was charged twice.",
}


def test_valid_output_returns_classification_result():
    result = parse_classification(VALID_RESPONSE)

    assert result == ClassificationResult(
        category=TicketCategory.BILLING,
        priority=TicketPriority.HIGH,
        summary="Customer was charged twice.",
    )


@pytest.mark.parametrize("category", ["billing", "technical", "account", "other"])
def test_accepts_every_allowed_category(category):
    output = json.dumps(VALID_OUTPUT | {"category": category})

    assert parse_classification(output).category == category


@pytest.mark.parametrize("priority", ["low", "medium", "high"])
def test_accepts_every_allowed_priority(priority):
    output = json.dumps(VALID_OUTPUT | {"priority": priority})

    assert parse_classification(output).priority == priority


def test_strips_surrounding_whitespace_from_summary():
    output = json.dumps(VALID_OUTPUT | {"summary": "  Charged twice.  "})

    assert parse_classification(output).summary == "Charged twice."


@pytest.mark.parametrize(
    "raw_output",
    [
        pytest.param(MALFORMED_JSON_RESPONSE, id="malformed-json"),
        pytest.param("", id="empty-output"),
        pytest.param("Sure! Here is the classification.", id="prose"),
        pytest.param(INVALID_CATEGORY_RESPONSE, id="invalid-category"),
        pytest.param(INVALID_PRIORITY_RESPONSE, id="invalid-priority"),
        pytest.param(EMPTY_SUMMARY_RESPONSE, id="empty-summary"),
        pytest.param(json.dumps(VALID_OUTPUT | {"summary": "   "}), id="blank-summary"),
        pytest.param(
            json.dumps(VALID_OUTPUT | {"category": "Billing"}),
            id="wrong-case-category",
        ),
        pytest.param(
            json.dumps(VALID_OUTPUT | {"extra": "field"}), id="unexpected-field"
        ),
    ],
)
def test_rejects_invalid_output(raw_output):
    with pytest.raises(ClassificationError, match="Invalid classification output"):
        parse_classification(raw_output)


@pytest.mark.parametrize("field", ["category", "priority", "summary"])
def test_rejects_output_missing_a_field(field):
    output = {key: value for key, value in VALID_OUTPUT.items() if key != field}

    with pytest.raises(ClassificationError, match=field):
        parse_classification(json.dumps(output))


@pytest.mark.parametrize(
    "output",
    [
        pytest.param([VALID_OUTPUT], id="top-level-list"),
        pytest.param("billing", id="top-level-string"),
        pytest.param(None, id="top-level-null"),
        pytest.param(VALID_OUTPUT | {"category": 1}, id="category-number"),
        pytest.param(VALID_OUTPUT | {"priority": None}, id="priority-null"),
        pytest.param(VALID_OUTPUT | {"priority": ["high"]}, id="priority-list"),
        pytest.param(VALID_OUTPUT | {"summary": 42}, id="summary-number"),
        pytest.param(VALID_OUTPUT | {"summary": True}, id="summary-bool"),
        pytest.param(VALID_OUTPUT | {"summary": {"text": "x"}}, id="summary-object"),
    ],
)
def test_rejects_wrong_json_types(output):
    with pytest.raises(ClassificationError):
        parse_classification(json.dumps(output))


def test_classification_error_preserves_validation_details():
    with pytest.raises(ClassificationError) as error_info:
        parse_classification(INVALID_PRIORITY_RESPONSE)

    assert "priority" in str(error_info.value)
    assert error_info.value.__cause__ is not None
