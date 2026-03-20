from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from .coordinator import Plan44Coordinator
    from .plan44_client import Plan44Client
    from .store import Plan44Store

DOMAIN = "plan44_integration"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_VDC_MODEL_NAME = "vdc_model_name"
CONF_AUTO_REPUBLISH = "auto_republish"
CONF_REVERSE_ENABLED = "reverse_enabled"
CONF_RECONNECT_INTERVAL = "reconnect_interval"
CONF_BLOCKLIST_INTEGRATIONS = "blocklist_integrations"
CONF_BLOCKLIST_ENTITY_ID_PREFIXES = "blocklist_entity_id_prefixes"

DEFAULT_PORT = 8999
DEFAULT_VDC_MODEL_NAME = "Home Assistant Bridge"
DEFAULT_AUTO_REPUBLISH = True
DEFAULT_REVERSE_ENABLED = True
DEFAULT_RECONNECT_INTERVAL = 10
DEFAULT_BLOCKLIST_INTEGRATIONS = "digitalstrom,digitalstromsmart,ha_digitalstrom_smart"
DEFAULT_BLOCKLIST_ENTITY_ID_PREFIXES = ""

SERVICE_CREATE_VIRTUAL_DEVICE = "create_virtual_device"
SERVICE_REMOVE_VIRTUAL_DEVICE = "remove_virtual_device"
SERVICE_REPUBLISH_VIRTUAL_DEVICES = "republish_virtual_devices"
SERVICE_PUSH_ENTITY_STATE = "push_entity_state"

STORE_VERSION = 3
STORE_KEY_EXPORTS = "exports"

ATTR_ENTITY_ID = "entity_id"
ATTR_KIND = "kind"
ATTR_NAME = "name"
ATTR_ROOM_HINT = "room_hint"
ATTR_ALLOW_REVERSE = "allow_reverse"
ATTR_ENTRY_ID = "entry_id"

KIND_SWITCH = "switch"
KIND_LIGHT = "light"
KIND_SENSOR = "sensor"
KIND_BINARY_SENSOR = "binary_sensor"

SUPPORTED_KINDS = {
    KIND_SWITCH,
    KIND_LIGHT,
    KIND_SENSOR,
    KIND_BINARY_SENSOR,
}

ORIGIN_HA = "ha"
ORIGIN_P44 = "p44"

REVERSE_COOLDOWN_SECONDS = 1.5
FORWARD_COOLDOWN_SECONDS = 1.0

LIGHT_ON_THRESHOLD = 1
LIGHT_MAX_BRIGHTNESS = 255
P44_MAX_CHANNEL_VALUE = 100


@dataclass
class Plan44RuntimeData:
    client: "Plan44Client"
    coordinator: "Plan44Coordinator"
    store: "Plan44Store"


Plan44ConfigEntry = ConfigEntry[Plan44RuntimeData]
