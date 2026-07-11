"""Light platform for plan44 — imports Hue and other output devices via the web API."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
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

        has_color_temp = bool(data.get(ATTR_HAS_COLOR_TEMP, False))
        entity = Plan44RestLight(
            coordinator=runtime.device_coordinator,
            entry_id=entry.entry_id,
            subentry_id=subentry_id,
            dsuid=str(dsuid),
            device_name=str(data.get(ATTR_NAME) or dsuid),
            model=str(data.get(ATTR_MODEL) or "") or None,
            has_color_temp=has_color_temp,
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

        modes: set[ColorMode] = {ColorMode.BRIGHTNESS}
        if has_color_temp:
            modes.add(ColorMode.COLOR_TEMP)
        if has_hs_color:
            modes.add(ColorMode.HS)
        self._attr_supported_color_modes = modes

        if has_color_temp and color_temp_max_mired > 0:
            # mired → kelvin: 1_000_000 / mired
            # warmest (high mired) = lowest kelvin; coldest (low mired) = highest kelvin
            self._attr_min_color_temp_kelvin = max(
                1, round(1_000_000 / color_temp_max_mired)
            )
            self._attr_max_color_temp_kelvin = round(
                1_000_000 / max(1, color_temp_min_mired)
            )

        # Track which color mode was last requested so we can report it accurately.
        if has_hs_color:
            self._current_color_mode: ColorMode = ColorMode.HS
        elif has_color_temp:
            self._current_color_mode = ColorMode.COLOR_TEMP
        else:
            self._current_color_mode = ColorMode.BRIGHTNESS

    # ------------------------------------------------------------------
    # Internal helpers

    def _light_state(self) -> Any:
        return (self._coordinator.data or {}).get(self._dsuid, {}).get("light")

    # ------------------------------------------------------------------
    # LightEntity properties

    @property
    def available(self) -> bool:
        return self._coordinator.last_update_success and self._light_state() is not None

    @property
    def color_mode(self) -> ColorMode:
        return self._current_color_mode

    @property
    def is_on(self) -> bool | None:
        ls = self._light_state()
        return (ls.brightness > 0) if ls is not None else None

    @property
    def brightness(self) -> int | None:
        ls = self._light_state()
        if ls is None:
            return None
        return round(ls.brightness / 100 * 255)

    @property
    def color_temp_kelvin(self) -> int | None:
        if not self._has_color_temp:
            return None
        ls = self._light_state()
        if ls is None or not ls.color_temp_mired or ls.color_temp_mired <= 0:
            return None
        return round(1_000_000 / ls.color_temp_mired)

    @property
    def hs_color(self) -> tuple[float, float] | None:
        if not self._has_hs_color:
            return None
        ls = self._light_state()
        if ls is None or ls.hue is None or ls.saturation is None:
            return None
        return (ls.hue, ls.saturation)

    # ------------------------------------------------------------------
    # Coordinator subscription

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._coordinator.async_add_listener(self._handle_update))
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Commands

    async def async_turn_on(self, **kwargs: Any) -> None:
        channels: dict[str, float] = {}

        brightness_ha = kwargs.get(ATTR_BRIGHTNESS)
        if brightness_ha is not None:
            channels["brightness"] = round(brightness_ha / 255 * 100, 2)
        else:
            ls = self._light_state()
            if ls is None or ls.brightness == 0:
                channels["brightness"] = 100.0

        if ATTR_COLOR_TEMP_KELVIN in kwargs and self._has_color_temp:
            channels["colortemp"] = round(1_000_000 / kwargs[ATTR_COLOR_TEMP_KELVIN], 1)
            self._current_color_mode = ColorMode.COLOR_TEMP

        if ATTR_HS_COLOR in kwargs and self._has_hs_color:
            h, s = kwargs[ATTR_HS_COLOR]
            channels["hue"] = float(h)
            channels["saturation"] = float(s)
            self._current_color_mode = ColorMode.HS
            if "brightness" not in channels:
                ls = self._light_state()
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
