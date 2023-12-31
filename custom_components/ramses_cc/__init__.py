"""Support for Honeywell's RAMSES-II RF protocol, as used by CH/DHW & HVAC.

Requires a Honeywell HGI80 (or compatible) gateway.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from ramses_rf.entity_base import Entity as RamsesRFEntity
from ramses_tx.exceptions import TransportSerialError
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.service import verify_domain_control
from homeassistant.helpers.typing import ConfigType

from .broker import RamsesBroker
from .const import (
    ATTR_DEVICE_ID,
    CONF_ADVANCED_FEATURES,
    CONF_MESSAGE_EVENTS,
    CONF_SEND_PACKET,
    DOMAIN,
    SIGNAL_UPDATE,
    SVC_FAKE_DEVICE,
    SVC_FORCE_UPDATE,
    SVC_SEND_PACKET,
)
from .schemas import SCH_DOMAIN_CONFIG


@dataclass(kw_only=True)
class RamsesEntityDescription(EntityDescription):
    """Class describing Ramses entities."""

    has_entity_name: bool = True
    extra_attributes: dict[str, str] | None = None


_LOGGER = logging.getLogger(__name__)


CONFIG_SCHEMA = vol.Schema({DOMAIN: SCH_DOMAIN_CONFIG}, extra=vol.ALLOW_EXTRA)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.REMOTE,
    Platform.WATER_HEATER,
]

SVC_FAKE_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.matches_regex(r"^[0-9]{2}:[0-9]{6}$"),
        vol.Optional("create_device", default=False): vol.Any(None, cv.boolean),
        vol.Optional("start_binding", default=False): vol.Any(None, cv.boolean),
    }
)

SVC_SEND_PACKET_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.matches_regex(r"^[0-9]{2}:[0-9]{6}$"),
        vol.Required("verb"): vol.In((" I", "I", "RQ", "RP", " W", "W")),
        vol.Required("code"): cv.matches_regex(r"^[0-9A-F]{4}$"),
        vol.Required("payload"): cv.matches_regex(r"^[0-9A-F]{1,48}$"),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Ramses integration."""
    hass.data[DOMAIN] = {}

    # One-off import of entry from config yaml
    if DOMAIN in config and not hass.config_entries.async_entries(DOMAIN):
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_IMPORT},
                data=config[DOMAIN],
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Create a ramses_rf (RAMSES_II)-based system."""
    broker = RamsesBroker(hass, entry)
    try:
        await broker.async_setup()
    except TransportSerialError as exc:
        raise ConfigEntryNotReady(
            f"There is a problem with the serial port: {exc}"
        ) from exc

    # Setup is complete and config is valid, so start polling
    hass.data[DOMAIN][entry.entry_id] = broker
    await broker.async_start()

    async_register_domain_services(hass, broker)
    async_register_domain_events(hass, broker)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    broker: RamsesBroker = hass.data[DOMAIN][entry.entry_id]
    if not await broker.async_unload_platforms():
        return False

    hass.services.async_remove(DOMAIN, SVC_FAKE_DEVICE)
    hass.services.async_remove(DOMAIN, SVC_FORCE_UPDATE)
    hass.services.async_remove(DOMAIN, SVC_SEND_PACKET)

    hass.data[DOMAIN].pop(entry.entry_id)

    return True


@callback  # TODO: the following is a mess - to add register/deregister of clients
def async_register_domain_events(hass: HomeAssistant, broker: RamsesBroker) -> None:
    """Set up the handlers for the system-wide events."""

    @callback
    def process_msg(msg, *args, **kwargs):  # process_msg(msg, prev_msg=None)
        if (
            regex := broker.config[CONF_ADVANCED_FEATURES][CONF_MESSAGE_EVENTS]
        ) and regex.match(f"{msg!r}"):
            event_data = {
                "dtm": msg.dtm.isoformat(),
                "src": msg.src.id,
                "dst": msg.dst.id,
                "verb": msg.verb,
                "code": msg.code,
                "payload": msg.payload,
                "packet": str(msg._pkt),
            }
            hass.bus.async_fire(f"{DOMAIN}_message", event_data)

        if broker.learn_device_id and broker.learn_device_id == msg.src.id:
            event_data = {
                "src": msg.src.id,
                "code": msg.code,
                "packet": str(msg._pkt),
            }
            hass.bus.async_fire(f"{DOMAIN}_learn", event_data)

    broker.client.add_msg_handler(process_msg)


@callback
def async_register_domain_services(hass: HomeAssistant, broker: RamsesBroker):
    """Set up the handlers for the domain-wide services."""

    @verify_domain_control(hass, DOMAIN)
    async def async_fake_device(call: ServiceCall) -> None:
        try:
            broker.client.fake_device(**call.data)
        except LookupError as exc:
            _LOGGER.error("%s", exc)
            return
        hass.helpers.event.async_call_later(5, broker.async_update)

    @verify_domain_control(hass, DOMAIN)
    async def async_force_update(_: ServiceCall) -> None:
        await broker.async_update()

    @verify_domain_control(hass, DOMAIN)
    async def async_send_packet(call: ServiceCall) -> None:
        kwargs = dict(call.data.items())  # is ReadOnlyDict
        if (
            call.data["device_id"] == "18:000730"
            and kwargs.get("from_id", "18:000730") == "18:000730"
            and broker.client.hgi.id
        ):
            kwargs["device_id"] = broker.client.hgi.id
        broker.client.send_cmd(broker.client.create_cmd(**kwargs))
        hass.helpers.event.async_call_later(5, broker.async_update)

    hass.services.async_register(
        DOMAIN, SVC_FAKE_DEVICE, async_fake_device, schema=SVC_FAKE_DEVICE_SCHEMA
    )
    hass.services.async_register(DOMAIN, SVC_FORCE_UPDATE, async_force_update)

    if broker.config[CONF_ADVANCED_FEATURES].get(CONF_SEND_PACKET):
        hass.services.async_register(
            DOMAIN,
            SVC_SEND_PACKET,
            async_send_packet,
            schema=SVC_SEND_PACKET_SCHEMA,
        )


class RamsesEntity(Entity):
    """Base for any RAMSES II-compatible entity (e.g. Climate, Sensor)."""

    _broker: RamsesBroker
    _device: RamsesRFEntity

    _attr_should_poll = False

    entity_description: RamsesEntityDescription

    def __init__(
        self,
        broker: RamsesBroker,
        device: RamsesRFEntity,
        entity_description: RamsesEntityDescription,
    ) -> None:
        """Initialize the entity."""
        self.hass = broker.hass
        self._broker = broker
        self._device = device
        self.entity_description = entity_description

        self._attr_unique_id = device.id
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device.id)})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the integration-specific state attributes."""
        attrs = {
            ATTR_ID: self._device.id,
        }
        if self.entity_description.extra_attributes:
            attrs |= {
                k: getattr(self._device, v)
                for k, v in self.entity_description.extra_attributes.items()
                if hasattr(self._device, v)
            }
        return attrs

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        self._broker._entities[self.unique_id] = self
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_UPDATE, self.async_write_ha_state
            )
        )

    @callback
    def async_write_ha_state_delayed(self, delay=3) -> None:
        """Write the state to the state machine after a short delay to allow system to quiesce."""
        async_call_later(self.hass, delay, self.async_write_ha_state)
