from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app import constants
from app.labels import TicketCategory, TicketPriority


class ClassificationError(ValueError):
    """Raised when raw model output is not a valid classification."""


class ClassificationResult(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, str_strip_whitespace=True
    )

    category: TicketCategory
    priority: TicketPriority
    summary: str = Field(
        min_length=1, max_length=constants.MAX_SUMMARY_LENGTH, pattern=r"^[^\r\n]+$"
    )


def parse_classification(raw_output: str) -> ClassificationResult:
    """Parse untrusted model text into a validated classification or raise."""
    try:
        return ClassificationResult.model_validate_json(raw_output)
    except ValidationError as error:
        raise ClassificationError(f"Invalid classification output: {error}") from error
