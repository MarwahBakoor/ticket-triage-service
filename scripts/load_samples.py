"""Submit sample_data/tickets.json to a running service via POST /tickets.

Usage: uv run python scripts/load_samples.py [BASE_URL]

Safe to rerun: the service ignores ticket ids it has already stored.
"""

import json
import sys
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
SAMPLES_PATH = Path(__file__).resolve().parent.parent / "sample_data" / "tickets.json"


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL
    tickets = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    for ticket in tickets:
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/tickets",
            data=json.dumps(ticket).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            stored = json.load(response)
        print(f"{stored['id']}: {stored['classification_status']}")


if __name__ == "__main__":
    main()
