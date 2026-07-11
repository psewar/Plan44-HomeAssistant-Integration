"""Guard against tag-like markup in translation strings.

Home Assistant renders translation strings through intl-messageformat, which
treats ``<word>`` as a rich-text tag. An unclosed one (e.g. ``https://<host>``)
makes the frontend throw "Translation error: UNCLOSED_TAG" when the dialog
opens. This integration uses no rich-text tags, so any ``<letter`` in a
translatable string is a mistake — fail fast here instead of in the UI.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_PKG = Path(__file__).resolve().parents[2] / "custom_components" / "plan44"
_FILES = [
    _PKG / "strings.json",
    _PKG / "translations" / "en.json",
    _PKG / "translations" / "de.json",
]
_TAG_LIKE = re.compile(r"<[a-zA-Z/]")


def _iter_strings(node: Any) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _iter_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_strings(value)


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_no_tag_like_markup_in_translations(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    offenders = [s for s in _iter_strings(data) if _TAG_LIKE.search(s)]
    assert not offenders, (
        f"{path.name}: tag-like '<...' would break the HA translation renderer "
        f"(UNCLOSED_TAG): {offenders}"
    )
