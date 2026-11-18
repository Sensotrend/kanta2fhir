"""Golden-file tests: the documents for the test fixtures must not change unnoticed.

If a change is intended, regenerate with ``uv run python tools/update_golden.py`` and review
the diff of tests/golden/.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from update_golden import GOLDEN, INPUTS, build  # noqa: E402


@pytest.mark.parametrize("name", list(INPUTS))
def test_documents_match_golden(name: str) -> None:
    actual = build(name)
    expected = {
        str(p.relative_to(GOLDEN)): json.loads(p.read_text(encoding="utf-8"))
        for p in (GOLDEN / name).rglob("*.json")
    }
    assert sorted(actual) == sorted(expected)
    for rel, bundle in actual.items():
        assert bundle == expected[rel], f"{rel} differs from golden file"
