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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import ATTR_DSUID, ATTR_PLATFORM, KIND_LIGHT, SUBENTRY_TYPE_P44_DEVICE
from .web_client import (
    PLATFORM_BINARY_SENSOR,
    PLATFORM_SENSOR,
    Plan44WebApi,
    Plan44WebApiError,
    parse_push_light_channel_states,
    parse_push_sensor_states,
)

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
    def async_apply_push_channel_states(self, dsuid: str, msg: dict[str, Any]) -> None:
        """Apply a channelStates push notification from the plan44 TCP connection.

        Updates ``self.data`` in-place and notifies listeners immediately — no
        HTTP poll is triggered.  Unknown dSUIDs are silently ignored.
        """
        if dsuid not in self.imported_light_dsuids():
            return
        channel_states = msg.get("channelStates")
        if not isinstance(channel_states, dict):
            return
        ls = parse_push_light_channel_states(channel_states)
        if ls is None:
            return
        _LOGGER.debug("Push update for light %s: brightness=%.1f", dsuid, ls.brightness)
        current = dict(self.data or {})
        current[dsuid] = {**current.get(dsuid, {}), "light": ls}
        self.async_set_updated_data(current)

    @callback
    def async_apply_push_sensor_states(self, dsuid: str, msg: dict[str, Any]) -> None:
        """Apply a sensorStates/binaryInputStates push notification.

        Merges pushed values into the existing per-device state dict and notifies
        listeners immediately.  Unknown dSUIDs are silently ignored.
        """
        if dsuid not in self.imported_sensor_dsuids():
            return
        state_update = parse_push_sensor_states(msg)
        if state_update is None:
            return
        sensors = state_update.get(PLATFORM_SENSOR, {})
        inputs = state_update.get(PLATFORM_BINARY_SENSOR, {})
        _LOGGER.debug(
            "Push update for sensor device %s: %d sensors, %d binary inputs",
            dsuid,
            len(sensors),
            len(inputs),
        )
        current = dict(self.data or {})
        existing = dict(current.get(dsuid, {}))
        if sensors:
            merged_sensors = {**existing.get(PLATFORM_SENSOR, {}), **sensors}
            existing[PLATFORM_SENSOR] = merged_sensors
        if inputs:
            merged_inputs = {**existing.get(PLATFORM_BINARY_SENSOR, {}), **inputs}
            existing[PLATFORM_BINARY_SENSOR] = merged_inputs
        current[dsuid] = existing
        self.async_set_updated_data(current)

    async def _async_update_data(self) -> DeviceStates:
        sensor_dsuids = self.imported_sensor_dsuids()
        light_dsuids = self.imported_light_dsuids()
        if not sensor_dsuids and not light_dsuids:
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
            raise UpdateFailed(str(err)) from err
        return states
