"""Buttons for imported plan44 devices.

Currently one entity: "Identify", which makes the physical device draw
attention to itself (a Hue lamp blinks).  Useful when several identical lamps
are imported and it is not obvious which row is which.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from homeassistant.components.button import ButtonEntity
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTR_DSUID,
    ATTR_MODEL,
    ATTR_NAME,
    ATTR_PLATFORM,
    ATTR_VENDOR,
    DOMAIN,
    KIND_LIGHT,
    SUBENTRY_TYPE_P44_DEVICE,
    Plan44ConfigEntry,
)
from .web_client import Plan44WebApiError, default_web_url

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Plan44ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    if runtime.web_api is None:
        return

    merged = {**entry.data, **entry.options}
    configuration_url = default_web_url(merged.get(CONF_HOST))

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_P44_DEVICE:
            continue
        data = getattr(subentry, "data", None)
        if not isinstance(data, Mapping):
            continue
        # Only lights so far: the bridge advertises identification for them,
        # and a battery sensor has no way to signal anything.
        if data.get(ATTR_PLATFORM) != KIND_LIGHT:
            continue
        dsuid = data.get(ATTR_DSUID)
        if not dsuid:
            continue

        async_add_entities(
            [
                Plan44IdentifyButton(
                    entry=entry,
                    subentry_id=subentry_id,
                    dsuid=str(dsuid),
                    device_name=str(data.get(ATTR_NAME) or dsuid),
                    model=str(data.get(ATTR_MODEL) or "") or None,
                    vendor=str(data.get(ATTR_VENDOR) or "") or None,
                    configuration_url=configuration_url,
                )
            ],
            config_subentry_id=subentry_id,
        )


class Plan44IdentifyButton(ButtonEntity):
    """Makes a plan44-provided device identify itself to the user."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_translation_key = "identify"

    def __init__(
        self,
        entry: Plan44ConfigEntry,
        subentry_id: str,
        dsuid: str,
        device_name: str,
        model: str | None,
        vendor: str | None,
        configuration_url: str | None,
    ) -> None:
        self._entry = entry
        self._dsuid = dsuid
        self._attr_unique_id = f"{entry.entry_id}_{subentry_id}_identify"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, dsuid)},
            name=device_name,
            model=model,
            manufacturer=vendor or "plan44",
            configuration_url=configuration_url,
        )

    async def async_press(self) -> None:
        web_api = self._entry.runtime_data.web_api
        if web_api is None:
            raise HomeAssistantError("plan44 web API is not configured")
        try:
            await web_api.async_identify(self._dsuid)
        except Plan44WebApiError as err:
            raise HomeAssistantError(
                f"plan44 could not identify the device: {err}"
            ) from err
