"""Shared helpers for inbound (P44 → HA) entity platforms."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import (
    ATTR_DEVICE_CLASS,
    ATTR_NAME,
    ATTR_P44_INDEX,
    ATTR_P44_TAG,
    ATTR_PLATFORM,
    ATTR_TEMPLATE,
    ATTR_UNIT,
)
from .device_templates import (
    PLATFORM_SENSOR,
    TEMPLATE_CUSTOM,
    ChannelTemplate,
    build_custom_template,
    get_template,
)


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def resolve_device(
    data: Mapping[str, Any],
) -> tuple[str, str, tuple[ChannelTemplate, ...]] | None:
    """Resolve a p44_device subentry to (tag, device_name, channels).

    Returns None if the subentry has no valid tag.
    """
    tag = _str_or_none(data.get(ATTR_P44_TAG))
    if tag is None:
        return None

    device_name = _str_or_none(data.get(ATTR_NAME)) or tag
    template_key = str(data.get(ATTR_TEMPLATE, ""))

    if template_key == TEMPLATE_CUSTOM:
        channels = build_custom_template(
            index=int(data.get(ATTR_P44_INDEX, 0)),
            platform=str(data.get(ATTR_PLATFORM, PLATFORM_SENSOR)),
            unit=_str_or_none(data.get(ATTR_UNIT)),
            device_class=_str_or_none(data.get(ATTR_DEVICE_CLASS)),
        ).channels
    else:
        template = get_template(template_key)
        channels = template.channels if template else ()

    return tag, device_name, channels
