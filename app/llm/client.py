from typing import Protocol


class LLMClient(Protocol):
    async def classify(self, prompt: str) -> str:
        """Return the model's raw, untrusted text output for the given prompt.

        Callers must parse and validate the result before using it.
        """
        ...
