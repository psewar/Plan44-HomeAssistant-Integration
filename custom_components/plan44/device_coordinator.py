"""Polling coordinator for REST-discovered plan44 devices.

Periodically reads sensor/binary-input states for all imported (dSUID-based)
p44_device subentries from the web vdc JSON API.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import ATTR_DSUID, SUBENTRY_TYPE_P44_DEVICE
from .web_client import Plan44WebApi, Plan44WebApiError

_LOGGER = logging.getLogger(__name__)

# coordinator.data: {dsuid: {"sensor": {key: value}, "binary_sensor": {key: value}}}
DeviceStates = dict[str, dict[str, dict[str, Any]]]


class Plan44DeviceCoordinator(DataUpdateCoordinator[DeviceStates]):
    """Polls the plan44 web API for the states of imported devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        web_api: Plan44WebApi,
        interval_seconds: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="plan44 devices",
            update_interval=timedelta(seconds=max(5, interval_seconds)),
        )
        self._entry = entry
        self._web_api = web_api

    def imported_dsuids(self) -> set[str]:
        """Collect dSUIDs from all dSUID-based p44_device subentries."""
        dsuids: set[str] = set()
        for subentry in self._entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_TYPE_P44_DEVICE:
                continue
            data = getattr(subentry, "data", None)
            if isinstance(data, Mapping) and data.get(ATTR_DSUID):
                dsuids.add(str(data[ATTR_DSUID]))
        return dsuids

    async def _async_update_data(self) -> DeviceStates:
        dsuids = self.imported_dsuids()
        if not dsuids:
            return {}
        try:
            return await self._web_api.async_get_states(dsuids)
        except Plan44WebApiError as err:
            raise UpdateFailed(str(err)) from err
