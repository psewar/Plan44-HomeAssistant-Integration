"""Polling coordinator for REST-discovered plan44 devices.

Periodically reads sensor/binary-input states and light channel states for all
imported (dSUID-based) p44_device subentries from the web vdc JSON API.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_DSUID,
    ATTR_PLATFORM,
    DOMAIN,
    ISSUE_WEB_API_UNREACHABLE,
    KIND_LIGHT,
    SUBENTRY_TYPE_P44_DEVICE,
)
from .web_client import Plan44WebApi, Plan44WebApiError

_LOGGER = logging.getLogger(__name__)

# coordinator.data shape:
#   {dsuid: {"sensor": {key: value}, "binary_sensor": {key: value}}}  for sensor devices
#   {dsuid: {"light": LightChannelState}}                              for light devices
DeviceStates = dict[str, dict[str, Any]]


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

    @property
    def web_api(self) -> Plan44WebApi:
        return self._web_api

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

    def imported_sensor_dsuids(self) -> set[str]:
        """Collect dSUIDs for sensor/binary-sensor (non-light) subentries."""
        dsuids: set[str] = set()
        for subentry in self._entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_TYPE_P44_DEVICE:
                continue
            data = getattr(subentry, "data", None)
            if (
                isinstance(data, Mapping)
                and data.get(ATTR_DSUID)
                and data.get(ATTR_PLATFORM) != KIND_LIGHT
            ):
                dsuids.add(str(data[ATTR_DSUID]))
        return dsuids

    def imported_light_dsuids(self) -> set[str]:
        """Collect dSUIDs for light subentries."""
        dsuids: set[str] = set()
        for subentry in self._entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_TYPE_P44_DEVICE:
                continue
            data = getattr(subentry, "data", None)
            if (
                isinstance(data, Mapping)
                and data.get(ATTR_DSUID)
                and data.get(ATTR_PLATFORM) == KIND_LIGHT
            ):
                dsuids.add(str(data[ATTR_DSUID]))
        return dsuids

    @callback
    def _set_web_api_issue(self, *, active: bool) -> None:
        """Create or clear the 'web API unreachable' repair issue."""
        if active:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_WEB_API_UNREACHABLE,
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_WEB_API_UNREACHABLE,
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_WEB_API_UNREACHABLE)

    async def _async_update_data(self) -> DeviceStates:
        sensor_dsuids = self.imported_sensor_dsuids()
        light_dsuids = self.imported_light_dsuids()
        if not sensor_dsuids and not light_dsuids:
            self._set_web_api_issue(active=False)
            return {}
        states: DeviceStates = {}
        try:
            if sensor_dsuids:
                states = await self._web_api.async_get_states(sensor_dsuids)
            if light_dsuids:
                light_states = await self._web_api.async_get_light_states(light_dsuids)
                for dsuid, ls in light_states.items():
                    states.setdefault(dsuid, {})["light"] = ls
        except Plan44WebApiError as err:
            self._set_web_api_issue(active=True)
            raise UpdateFailed(str(err)) from err
        self._set_web_api_issue(active=False)
        return states
