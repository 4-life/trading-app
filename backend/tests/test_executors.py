"""Pure unit tests, no database."""

import pytest

from app.executors.base import direction_allowed


@pytest.mark.parametrize(
    ("paper_direction", "direction", "expected"),
    [
        ("long", "long", True),
        ("long", "short", False),
        ("short", "short", True),
        ("short", "long", False),
        ("both", "long", True),
        ("both", "short", True),
    ],
)
def test_direction_allowed(paper_direction: str, direction: str, expected: bool) -> None:
    assert direction_allowed(paper_direction, direction) is expected  # type: ignore[arg-type]
