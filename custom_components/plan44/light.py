"""Light platform for plan44 — imports Hue and other output devices via the web API."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    LightEntity,
)
from homeassistant.components.light.const import ColorMode
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTR_COLOR_TEMP_MAX_MIRED,
    ATTR_COLOR_TEMP_MIN_MIRED,
    ATTR_DSUID,
    ATTR_HAS_COLOR_TEMP,
    ATTR_HAS_HS_COLOR,
    ATTR_MODEL,
    ATTR_NAME,
    ATTR_PLATFORM,
    DOMAIN,
    KIND_LIGHT,
    SUBENTRY_TYPE_P44_DEVICE,
    Plan44ConfigEntry,
)
from .device_coordinator import Plan44DeviceCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Plan44ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    if runtime.device_coordinator is None:
        return

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_P44_DEVICE:
            continue
        data = getattr(subentry, "data", None)
        if not isinstance(data, Mapping):
            continue
        if data.get(ATTR_PLATFORM) != KIND_LIGHT:
            continue
        dsuid = data.get(ATTR_DSUID)
        if not dsuid:
            continue

        entity = Plan44RestLight(
            coordinator=runtime.device_coordinator,
            entry_id=entry.entry_id,
            subentry_id=subentry_id,
            dsuid=str(dsuid),
            device_name=str(data.get(ATTR_NAME) or dsuid),
            model=str(data.get(ATTR_MODEL) or "") or None,
            has_color_temp=bool(data.get(ATTR_HAS_COLOR_TEMP, False)),
            color_temp_min_mired=float(data.get(ATTR_COLOR_TEMP_MIN_MIRED, 100.0)),
            color_temp_max_mired=float(data.get(ATTR_COLOR_TEMP_MAX_MIRED, 1000.0)),
            has_hs_color=bool(data.get(ATTR_HAS_HS_COLOR, False)),
        )
        async_add_entities([entity], config_subentry_id=subentry_id)


class Plan44RestLight(LightEntity):
    """A light entity polled from the plan44 web API for a discovered output device."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = None  # device name is the entity name

    def __init__(
        self,
        coordinator: Plan44DeviceCoordinator,
        entry_id: str,
        subentry_id: str,
        dsuid: str,
        device_name: str,
        model: str | None,
        has_color_temp: bool,
        color_temp_min_mired: float,
        color_temp_max_mired: float,
        has_hs_color: bool,
    ) -> None:
        self._coordinator = coordinator
        self._dsuid = dsuid
        self._has_color_temp = has_color_temp
        self._has_hs_color = has_hs_color
        self._attr_unique_id = f"{entry_id}_{subentry_id}_light"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, dsuid)},
            name=device_name,
            model=model,
            manufacturer="plan44",
        )

        # HA validates that BRIGHTNESS is not combined with other color modes;
        # HS and COLOR_TEMP already imply brightness control.
        modes: set[ColorMode] = set()
        if has_hs_color:
            modes.add(ColorMode.HS)
        if has_color_temp:
            modes.add(ColorMode.COLOR_TEMP)
        if not modes:
            modes.add(ColorMode.BRIGHTNESS)
        self._attr_supported_color_modes = modes

        if has_hs_color:
            self._attr_color_mode: ColorMode | None = ColorMode.HS
        elif has_color_temp:
            self._attr_color_mode = ColorMode.COLOR_TEMP
        else:
            self._attr_color_mode = ColorMode.BRIGHTNESS

        if has_color_temp and color_temp_max_mired > 0:
            # mired → kelvin conversion: 1_000_000 / mired
            # warmest (high mired) = lowest kelvin; coldest (low mired) = highest kelvin
            self._attr_min_color_temp_kelvin = max(
                1, round(1_000_000 / color_temp_max_mired)
            )
            self._attr_max_color_temp_kelvin = round(
                1_000_000 / max(1, color_temp_min_mired)
            )

        self._attr_available = False
        self._attr_is_on = None
        self._attr_brightness = None
        self._attr_color_temp_kelvin: int | None = None
        self._attr_hs_color: tuple[float, float] | None = None

    # ------------------------------------------------------------------
    # Coordinator subscription

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._coordinator.async_add_listener(self._handle_update))
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        data = self._coordinator.data or {}
        ls = data.get(self._dsuid, {}).get("light")
        self._attr_available = self._coordinator.last_update_success and ls is not None
        if ls is not None:
            self._attr_is_on = ls.brightness > 0
            self._attr_brightness = round(ls.brightness / 100 * 255)
            if self._has_color_temp and ls.color_temp_mired and ls.color_temp_mired > 0:
                self._attr_color_temp_kelvin = round(1_000_000 / ls.color_temp_mired)
            else:
                self._attr_color_temp_kelvin = None
            if self._has_hs_color and ls.hue is not None and ls.saturation is not None:
                self._attr_hs_color = (ls.hue, ls.saturation)
            else:
                self._attr_hs_color = None
        else:
            self._attr_is_on = None
            self._attr_brightness = None
            self._attr_color_temp_kelvin = None
            self._attr_hs_color = None
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Commands

    async def async_turn_on(self, **kwargs: Any) -> None:
        channels: dict[str, float] = {}

        brightness_ha = kwargs.get(ATTR_BRIGHTNESS)
        if brightness_ha is not None:
            channels["brightness"] = round(brightness_ha / 255 * 100, 2)
        else:
            ls = (self._coordinator.data or {}).get(self._dsuid, {}).get("light")
            if ls is None or ls.brightness == 0:
                channels["brightness"] = 100.0

        if ATTR_COLOR_TEMP_KELVIN in kwargs and self._has_color_temp:
            channels["colortemp"] = round(1_000_000 / kwargs[ATTR_COLOR_TEMP_KELVIN], 1)
            self._attr_color_mode = ColorMode.COLOR_TEMP

        if ATTR_HS_COLOR in kwargs and self._has_hs_color:
            h, s = kwargs[ATTR_HS_COLOR]
            channels["hue"] = float(h)
            channels["saturation"] = float(s)
            self._attr_color_mode = ColorMode.HS
            if "brightness" not in channels:
                ls = (self._coordinator.data or {}).get(self._dsuid, {}).get("light")
                if ls is None or ls.brightness == 0:
                    channels["brightness"] = 100.0

        if channels:
            await self._coordinator.web_api.async_set_channels(self._dsuid, channels)
            await self._coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._coordinator.web_api.async_set_channels(
            self._dsuid, {"brightness": 0.0}
        )
        await self._coordinator.async_request_refresh()
