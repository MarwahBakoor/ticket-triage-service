"""Tunable values for classification, in one place.

Code reads these as `constants.NAME` when it needs them, so a test can
monkeypatch this module and every caller sees the change. The exception is
MAX_SUMMARY_LENGTH, which is fixed when the validation model is defined.
"""

# Classification attempts per ticket before it is marked failed.
MAX_ATTEMPTS = 3
# A call that has not answered by then counts as a failed attempt, so a hung
# provider cannot hold a worker forever.
LLM_TIMEOUT_SECONDS = 30.0
# Wait before retry n is this times 2 ** (n - 1): 1 s, then 2 s.
RETRY_BASE_DELAY_SECONDS = 1.0

# Classifications that may run at once when CLASSIFICATION_WORKERS is unset.
DEFAULT_WORKER_COUNT = 4
# How long an idle worker waits before asking the database for work again. A
# new ticket is picked up within this time.
POLL_INTERVAL_SECONDS = 1.0

# Room for one long sentence. "One sentence" itself is asked for in the prompt
# but not parsed: abbreviations like "e.g." would turn good answers into
# failures. A single line and a length cap keep essays out of the store.
MAX_SUMMARY_LENGTH = 300

# The local fake model returns broken output on every n-th call, so retries
# happen during local use.
FAKE_LLM_BROKEN_EVERY = 4
