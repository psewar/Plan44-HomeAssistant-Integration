"""Shared helpers for inbound (P44 → HA) entity platforms."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .const import (
    ATTR_DEVICE_CLASS,
    ATTR_DSUID,
    ATTR_NAME,
    ATTR_P44_INDEX,
    ATTR_P44_TAG,
    ATTR_PLATFORM,
    ATTR_TEMPLATE,
    ATTR_UNIT,
    SUBENTRY_TYPE_P44_DEVICE,
)
from .device_templates import (
    PLATFORM_SENSOR,
    TEMPLATE_CUSTOM,
    ChannelTemplate,
    build_custom_template,
    get_template,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.helpers.entity import Entity
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .const import Plan44ConfigEntry
    from .coordinator import Plan44Coordinator
    from .device_coordinator import Plan44DeviceCoordinator

_LOGGER = logging.getLogger(__name__)


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


def setup_p44_device_entities[EntityT: Entity](
    entry: Plan44ConfigEntry,
    add_entities: AddConfigEntryEntitiesCallback,
    build_rest: Callable[
        [Plan44DeviceCoordinator, str, str, Mapping[str, Any]], list[EntityT]
    ],
    build_push: Callable[
        [Plan44Coordinator, str, str, Mapping[str, Any]], list[EntityT]
    ],
) -> None:
    """Create the entities of every p44_device sub-entry, attributed to it.

    dSUID-based sub-entries are REST-polled (``build_rest``); tag-based ones are
    push-fed (``build_push``).  Each sub-entry's entities are added with its
    ``config_subentry_id`` so the imported device shows under its own
    "Plan44 device" sub-entry instead of the entry-level "no sub-entry" bucket.
    """
    runtime = entry.runtime_data
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_P44_DEVICE:
            continue
        data = getattr(subentry, "data", None)
        if not isinstance(data, Mapping):
            continue

        if data.get(ATTR_DSUID):
            if runtime.device_coordinator is None:
                _LOGGER.warning(
                    "p44_device %s needs the web API; configure it in the options",
                    subentry_id,
                )
                continue
            entities = build_rest(
                runtime.device_coordinator, entry.entry_id, subentry_id, data
            )
        else:
            entities = build_push(
                runtime.coordinator, entry.entry_id, subentry_id, data
            )

        if entities:
            add_entities(entities, config_subentry_id=subentry_id)
