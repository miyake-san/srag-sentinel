import json
from pathlib import Path
from typing import Any

import pytest

CORPUS_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "kg" / "corpus.json"


@pytest.fixture(scope="session")
def corpus() -> list[dict[str, Any]]:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
