"""Support for RAMSES sensors."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from types import UnionType
from typing import Any, TypeAlias

from ramses_rf.const import (
    SZ_AIR_QUALITY,
    SZ_AIR_QUALITY_BASIS,
    SZ_CO2_LEVEL,
    SZ_EXHAUST_FAN_SPEED,
    SZ_EXHAUST_FLOW,
    SZ_EXHAUST_TEMP,
    SZ_FAN_INFO,
    SZ_FILTER_REMAINING,
    SZ_INDOOR_HUMIDITY,
    SZ_INDOOR_TEMP,
    SZ_OUTDOOR_HUMIDITY,
    SZ_OUTDOOR_TEMP,
    SZ_POST_HEAT,
    SZ_PRE_HEAT,
    SZ_REMAINING_MINS,
    SZ_SPEED_CAP,
    SZ_SUPPLY_FAN_SPEED,
    SZ_SUPPLY_FLOW,
    SZ_SUPPLY_TEMP,
)
from ramses_rf.device import Fakeable
from ramses_rf.device.heat import (
    SZ_BOILER_OUTPUT_TEMP,
    SZ_BOILER_RETURN_TEMP,
    SZ_BOILER_SETPOINT,
    SZ_CH_MAX_SETPOINT,
    SZ_CH_SETPOINT,
    SZ_CH_WATER_PRESSURE,
    SZ_DHW_FLOW_RATE,
    SZ_DHW_SETPOINT,
    SZ_DHW_TEMP,
    SZ_MAX_REL_MODULATION,
    SZ_OEM_CODE,
    SZ_OUTSIDE_TEMP,
    SZ_REL_MODULATION_LEVEL,
    DhwSensor,
    OtbGateway,
    OutSensor,
    Thermostat,
    TrvActuator,
    UfhController,
)
from ramses_rf.device.hvac import HvacCarbonDioxideSensor, HvacHumiditySensor
from ramses_rf.entity_base import Entity as RamsesRFEntity
from ramses_rf.system.heat import SystemBase
from ramses_rf.system.zones import ZoneBase
from ramses_tx.const import SZ_HEAT_DEMAND, SZ_RELAY_DEMAND, SZ_SETPOINT, SZ_TEMPERATURE

from homeassistant.components.binary_sensor import ENTITY_ID_FORMAT
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    EntityCategory,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    EntityPlatform,
    async_get_current_platform,
)

from . import RamsesEntity, RamsesEntityDescription
from .broker import RamsesBroker
from .const import ATTR_SETPOINT, DOMAIN, UnitOfVolumeFlowRate
from .schemas import SVCS_SENSOR


@dataclass(kw_only=True)
class RamsesSensorEntityDescription(RamsesEntityDescription, SensorEntityDescription):
    """Class describing Ramses binary sensor entities."""

    attr: str = None  # type: ignore[assignment]
    entity_class: _SensorEntityT = None  # type: ignore[assignment]
    ramses_class: type[RamsesRFEntity] | UnionType = RamsesRFEntity
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT
    entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC
    icon_off: str | None = None
    has_entity_name = True

    def __post_init__(self):
        """Defaults entity attr to key."""
        self.attr = self.attr or self.key
        self.entity_class = self.entity_class or RamsesSensor


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensor platform."""
    broker: RamsesBroker = hass.data[DOMAIN][entry.entry_id]
    platform: EntityPlatform = async_get_current_platform()

    for k, v in SVCS_SENSOR.items():
        platform.async_register_entity_service(k, v, k)

    @callback
    def add_devices(devices: list[RamsesRFEntity]) -> None:
        entities = [
            (description.entity_class or RamsesSensor)(broker, device, description)
            for device in devices
            for description in SENSOR_DESCRIPTIONS
            if isinstance(device, description.ramses_class)
            and hasattr(device, description.attr)
        ]
        async_add_entities(entities)

    broker.async_register_platform(platform, add_devices)


class RamsesSensor(RamsesEntity, SensorEntity):
    """Representation of a generic sensor."""

    entity_description: RamsesSensorEntityDescription

    def __init__(
        self,
        broker: RamsesBroker,
        device: RamsesRFEntity,
        entity_description: RamsesEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        _LOGGER.info("Found %r: %s", device, entity_description.key)
        super().__init__(broker, device, entity_description)

        self.entity_id = ENTITY_ID_FORMAT.format(
            f"{device.id}_{entity_description.key}"
        )
        self._attr_unique_id = f"{device.id}-{entity_description.key}"

    @property
    def available(self) -> bool:
        """Return True if the entity is available."""
        # TODO: Should use dtm of last packet received, rather than is not None
        return (
            isinstance(self._device, Fakeable) and self._device.is_faked
        ) or self.state is not None  # TODO: but what if None _is_ its state?

    @property
    def native_value(self) -> Any | None:
        """Return the native value of the sensor."""
        val = getattr(self._device, self.entity_description.attr)
        if self.native_unit_of_measurement == PERCENTAGE:
            return None if val is None else val * 100
        return val

    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend, if any."""
        if self.entity_description.icon_off and not self.native_value:
            return self.entity_description.icon_off
        return super().icon

    # the following methods are integration-specific service calls

    @callback
    def put_co2_level(self, co2_level: int) -> None:
        """Cast the CO2 level (if faked)."""

        # TODO: Remove from here...
        assert self.device_class == SensorDeviceClass.CO2
        assert self.native_unit_of_measurement == CONCENTRATION_PARTS_PER_MILLION

        if not isinstance(self._device, HvacCarbonDioxideSensor):
            raise TypeError(f"Cannot set CO2 level on {self._device}")
        # TODO: Until here

        # setter will raise an exception if device is not faked
        self._device.co2_level = co2_level  # would accept None

    @callback
    def put_dhw_temp(self, temperature: float) -> None:
        """Cast the DHW cylinder temperature (if faked)."""

        # TODO: Remove from here...
        assert self.device_class == SensorDeviceClass.TEMPERATURE
        assert self.native_unit_of_measurement == UnitOfTemperature.CELSIUS

        if not isinstance(self._device, DhwSensor):
            raise TypeError(f"Cannot set CO2 level on {self._device}")
        # TODO: Until here

        # setter will raise an exception if device is not faked
        self._device.temperature = temperature  # would accept None

    @callback
    def put_indoor_humidity(self, indoor_humidity: float) -> None:
        """Cast the indoor humidity level (if faked)."""

        # TODO: Remove from here...
        assert self.device_class == SensorDeviceClass.HUMIDITY
        assert self.native_unit_of_measurement == PERCENTAGE

        if not isinstance(self._device, HvacHumiditySensor):
            raise TypeError(f"Cannot set indoor humidity level on {self._device}")
        # TODO: Until here

        # setter will raise an exception if device is not faked
        self._device.indoor_humidity = indoor_humidity / 100  # would accept None

    @callback
    def put_room_temp(self, temperature: float) -> None:
        """Cast the room temperature (if faked)."""

        # TODO: Remove from here...
        assert self.device_class == SensorDeviceClass.TEMPERATURE
        assert self.native_unit_of_measurement == UnitOfTemperature.CELSIUS

        if not isinstance(self._device, Thermostat):
            raise TypeError(f"Cannot set CO2 level on {self._device}")
        # TODO: Until here

        # setter will raise an exception if device is not faked
        self._device.temperature = temperature  # would accept None


SENSOR_DESCRIPTIONS: tuple[RamsesSensorEntityDescription, ...] = (
    RamsesSensorEntityDescription(
        key=SZ_TEMPERATURE,
        device_class=SensorDeviceClass.TEMPERATURE,
        ramses_class=TrvActuator,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        extra_attributes={
            ATTR_SETPOINT: SZ_SETPOINT,
        },
    ),
    RamsesSensorEntityDescription(  # not TrvActuator
        key=SZ_TEMPERATURE,
        device_class=SensorDeviceClass.TEMPERATURE,
        ramses_class=DhwSensor | OutSensor | Thermostat,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=None,
        extra_attributes={
            ATTR_SETPOINT: SZ_SETPOINT,
        },
    ),
    RamsesSensorEntityDescription(
        key=SZ_HEAT_DEMAND,
        name="Heat demand",
        icon="mdi:radiator",
        icon_off="mdi:radiator-off",
        ramses_class=OtbGateway,
        native_unit_of_measurement=PERCENTAGE,
    ),
    RamsesSensorEntityDescription(  # not OtbGateway
        key=SZ_HEAT_DEMAND,
        name="Heat demand",
        icon="mdi:radiator",
        icon_off="mdi:radiator-off",
        ramses_class=SystemBase | TrvActuator | UfhController | ZoneBase,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=None,
    ),
    RamsesSensorEntityDescription(
        key=SZ_RELAY_DEMAND,
        name="Relay demand",
        icon="mdi:power-plug",
        icon_off="mdi:power-plug-off",
        native_unit_of_measurement=PERCENTAGE,
    ),
    RamsesSensorEntityDescription(
        key=f"{SZ_RELAY_DEMAND}_fa",
        name="Relay demand (FA)",
        icon="mdi:power-plug",
        icon_off="mdi:power-plug-off",
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
    ),
    RamsesSensorEntityDescription(
        key=SZ_BOILER_OUTPUT_TEMP,
        name="Boiler output temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    RamsesSensorEntityDescription(
        key=SZ_BOILER_RETURN_TEMP,
        name="Boiler return temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    RamsesSensorEntityDescription(
        key=SZ_BOILER_SETPOINT,
        name="Boiler setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    RamsesSensorEntityDescription(
        key=SZ_CH_SETPOINT,
        name="CH setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    RamsesSensorEntityDescription(
        key=SZ_CH_MAX_SETPOINT,
        name="CH max setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    RamsesSensorEntityDescription(
        key=SZ_CH_WATER_PRESSURE,
        name="CH water pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.BAR,
    ),
    RamsesSensorEntityDescription(
        key=SZ_DHW_FLOW_RATE,
        name="DHW flow rate",
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_MINUTE,
    ),
    RamsesSensorEntityDescription(
        key=SZ_DHW_SETPOINT,
        name="DHW setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    RamsesSensorEntityDescription(
        key=SZ_DHW_TEMP,
        name="DHW temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    RamsesSensorEntityDescription(
        key=SZ_OUTSIDE_TEMP,
        name="Outside temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    RamsesSensorEntityDescription(
        key=SZ_REL_MODULATION_LEVEL,
        name="Relative modulation level",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=None,
    ),
    RamsesSensorEntityDescription(
        key=SZ_MAX_REL_MODULATION,
        name="Max relative modulation level",
        native_unit_of_measurement=PERCENTAGE,
    ),
    # HVAC
    RamsesSensorEntityDescription(
        key=SZ_AIR_QUALITY,
        name="Air quality",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=None,
    ),
    RamsesSensorEntityDescription(
        key=SZ_AIR_QUALITY_BASIS,
        name="Air quality basis",
        native_unit_of_measurement=PERCENTAGE,
    ),
    RamsesSensorEntityDescription(
        key=SZ_CO2_LEVEL,
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
        entity_category=None,
    ),
    RamsesSensorEntityDescription(
        key=SZ_EXHAUST_FAN_SPEED,
        name="Exhaust fan speed",
        native_unit_of_measurement=PERCENTAGE,
    ),
    RamsesSensorEntityDescription(
        key=SZ_EXHAUST_FLOW,
        name="Exhaust flow",
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_SECOND,
    ),
    RamsesSensorEntityDescription(
        key=SZ_EXHAUST_TEMP,
        name="Exhaust temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    RamsesSensorEntityDescription(
        key=SZ_FAN_INFO,
        name="Fan info",
        state_class=None,
    ),
    RamsesSensorEntityDescription(
        key=SZ_FILTER_REMAINING,
        name="Filter remaining",
        native_unit_of_measurement=UnitOfTime.DAYS,
    ),
    RamsesSensorEntityDescription(
        key=SZ_INDOOR_HUMIDITY,
        name="Indoor humidiity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=None,
    ),
    RamsesSensorEntityDescription(
        key=SZ_INDOOR_TEMP,
        name="Indoor temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=None,
    ),
    RamsesSensorEntityDescription(
        key=SZ_OUTDOOR_HUMIDITY,
        name="Outdoor humidiity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
    ),
    RamsesSensorEntityDescription(
        key=SZ_OUTDOOR_TEMP,
        name="Outdoor temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    RamsesSensorEntityDescription(
        key=SZ_POST_HEAT,
        name="Post heat",
        native_unit_of_measurement=PERCENTAGE,
    ),
    RamsesSensorEntityDescription(
        key=SZ_PRE_HEAT,
        name="Pre heat",
        native_unit_of_measurement=PERCENTAGE,
    ),
    RamsesSensorEntityDescription(
        key=SZ_REMAINING_MINS,
        name="Remaining time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    RamsesSensorEntityDescription(
        key=SZ_SPEED_CAP,
        name="Speed cap",
        native_unit_of_measurement="units",
    ),
    RamsesSensorEntityDescription(
        key=SZ_SUPPLY_FAN_SPEED,
        name="Supply fan speed",
        native_unit_of_measurement=PERCENTAGE,
    ),
    RamsesSensorEntityDescription(
        key=SZ_SUPPLY_FLOW,
        name="Supply flow",
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_SECOND,
    ),
    RamsesSensorEntityDescription(
        key=SZ_SUPPLY_TEMP,
        name="Supply temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    # Special projects
    RamsesSensorEntityDescription(
        key=SZ_OEM_CODE,
        name="OEM code",
        ramses_class=OtbGateway,
        state_class=None,
        entity_registry_enabled_default=False,
    ),
    RamsesSensorEntityDescription(
        key="percent",
        name="Percent",
        ramses_class=OtbGateway,
        icon="mdi:power-plug",
        icon_off="mdi:power-plug-off",
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
    ),
    RamsesSensorEntityDescription(
        key="value",
        name="Value",
        ramses_class=OtbGateway,
        native_unit_of_measurement="units",
        entity_registry_enabled_default=False,
    ),
)

_SensorEntityT: TypeAlias = type[RamsesSensor]
