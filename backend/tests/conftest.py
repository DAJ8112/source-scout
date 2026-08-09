from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_text():
    def load(relative: str) -> str:
        return (FIXTURES / relative).read_text()

    return load
