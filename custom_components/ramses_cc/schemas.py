"""Schemas for RAMSES integration."""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import logging
from typing import Any, TypeAlias

from ramses_rf.const import SZ_DEVICE_ID
from ramses_rf.helpers import deep_merge, shrink
from ramses_rf.schemas import (
    SCH_GATEWAY_CONFIG,
    SCH_GLOBAL_SCHEMAS_DICT,
    SCH_RESTORE_CACHE_DICT,
    SZ_CONFIG,
    SZ_RESTORE_CACHE,
)
from ramses_tx.schemas import (
    SCH_ENGINE_DICT,
    SZ_PORT_CONFIG,
    SZ_SERIAL_PORT,
    extract_serial_port,
    sch_global_traits_dict_factory,
    sch_packet_log_dict_factory,
    sch_serial_port_dict_factory,
)
import voluptuous as vol

from homeassistant.const import ATTR_ENTITY_ID as CONF_ENTITY_ID, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import SYSTEM_MODE_LOOKUP, SystemMode, ZoneMode

_SchemaT: TypeAlias = dict[str, Any]

_LOGGER = logging.getLogger(__name__)

CONF_MODE = "mode"
CONF_SYSTEM_MODE = "system_mode"
CONF_DURATION_DAYS = "period"
CONF_DURATION_HOURS = "hours"

CONF_DURATION = "duration"
CONF_LOCAL_OVERRIDE = "local_override"
CONF_MAX_TEMP = "max_temp"
CONF_MIN_TEMP = "min_temp"
CONF_MULTIROOM = "multiroom_mode"
CONF_OPENWINDOW = "openwindow_function"
CONF_SCHEDULE = "schedule"
CONF_SETPOINT = "setpoint"
CONF_TEMPERATURE = "temperature"
CONF_UNTIL = "until"

CONF_ACTIVE = "active"
CONF_DIFFERENTIAL = "differential"
CONF_OVERRUN = "overrun"

#
# Generic services for Integration/domain
SVC_FAKE_DEVICE = "fake_device"
SVC_FORCE_UPDATE = "force_update"
SVC_SEND_PACKET = "send_packet"

SCH_FAKE_DEVICE = vol.Schema(
    {
        vol.Required(SZ_DEVICE_ID): cv.matches_regex(r"^[0-9]{2}:[0-9]{6}$"),
        vol.Optional("create_device", default=False): vol.Any(None, cv.boolean),
        vol.Optional("start_binding", default=False): vol.Any(None, cv.boolean),
    }
)
SCH_SEND_PACKET = vol.Schema(
    {
        vol.Required(SZ_DEVICE_ID): cv.matches_regex(r"^[0-9]{2}:[0-9]{6}$"),
        vol.Required("verb"): vol.In((" I", "I", "RQ", "RP", " W", "W")),
        vol.Required("code"): cv.matches_regex(r"^[0-9A-F]{4}$"),
        vol.Required("payload"): cv.matches_regex(r"^[0-9A-F]{1,48}$"),
    }
)

SVCS_DOMAIN = {
    SVC_FAKE_DEVICE: SCH_FAKE_DEVICE,
    SVC_FORCE_UPDATE: None,
    SVC_SEND_PACKET: SCH_SEND_PACKET,
}

_SCH_ENTITY_ID = vol.Schema({vol.Required(CONF_ENTITY_ID): cv.entity_id})

#
# Climate platform services for CH/DHW CTLs
SVC_RESET_SYSTEM_MODE = "reset_system_mode"
SVC_SET_SYSTEM_MODE = "set_system_mode"

SCH_SYSTEM_MODE = _SCH_ENTITY_ID.extend(
    {
        vol.Required(CONF_MODE): vol.In(SYSTEM_MODE_LOOKUP),
    }
)
SCH_SYSTEM_MODE_HOURS = _SCH_ENTITY_ID.extend(
    {
        vol.Required(CONF_MODE): vol.In([SystemMode.ECO_BOOST]),
        vol.Optional(CONF_DURATION, default=timedelta(hours=1)): vol.All(
            cv.time_period, vol.Range(min=timedelta(hours=1), max=timedelta(hours=24))
        ),
    }
)
SCH_SYSTEM_MODE_DAYS = _SCH_ENTITY_ID.extend(
    {
        vol.Required(CONF_MODE): vol.In(
            [
                SystemMode.AWAY,
                SystemMode.CUSTOM,
                SystemMode.DAY_OFF,
                SystemMode.DAY_OFF_ECO,
            ]
        ),
        vol.Optional(CONF_DURATION_DAYS, default=timedelta(days=0)): vol.All(
            cv.time_period, vol.Range(min=timedelta(days=0), max=timedelta(days=99))
        ),  # 0 means until the end of the day
    }
)
SCH_SYSTEM_MODE = vol.Any(SCH_SYSTEM_MODE, SCH_SYSTEM_MODE_HOURS, SCH_SYSTEM_MODE_DAYS)

SVCS_CLIMATE_EVO_TCS = {
    SVC_RESET_SYSTEM_MODE: _SCH_ENTITY_ID,
    SVC_SET_SYSTEM_MODE: SCH_SYSTEM_MODE,
}

#
# Climate platform services for CH/DHW Zones
SVC_GET_ZONE_SCHED = "get_zone_schedule"
SVC_PUT_ZONE_TEMP = "put_zone_temp"
SVC_RESET_ZONE_CONFIG = "reset_zone_config"
SVC_RESET_ZONE_MODE = "reset_zone_mode"
SVC_SET_ZONE_CONFIG = "set_zone_config"
SVC_SET_ZONE_MODE = "set_zone_mode"
SVC_SET_ZONE_SCHED = "set_zone_schedule"

SCH_SET_ZONE_CONFIG = _SCH_ENTITY_ID.extend(
    {
        vol.Optional(CONF_MAX_TEMP, default=35): vol.All(
            cv.positive_float,
            vol.Range(min=21, max=35),
        ),
        vol.Optional(CONF_MIN_TEMP, default=5): vol.All(
            cv.positive_float,
            vol.Range(min=5, max=21),
        ),
        vol.Optional(CONF_LOCAL_OVERRIDE, default=True): cv.boolean,
        vol.Optional(CONF_OPENWINDOW, default=True): cv.boolean,
        vol.Optional(CONF_MULTIROOM, default=True): cv.boolean,
    }
)

SCH_SET_ZONE_MODE = _SCH_ENTITY_ID.extend(
    {
        vol.Optional(CONF_MODE): vol.In([ZoneMode.SCHEDULE]),
    }
)
SCH_SET_ZONE_MODE_SETPOINT = _SCH_ENTITY_ID.extend(
    {
        vol.Optional(CONF_MODE): vol.In([ZoneMode.PERMANENT, ZoneMode.ADVANCED]),
        vol.Optional(CONF_SETPOINT, default=21): vol.All(
            cv.positive_float,
            vol.Range(min=5, max=30),
        ),
    }
)
SCH_SET_ZONE_MODE_UNTIL = _SCH_ENTITY_ID.extend(
    {
        vol.Optional(CONF_MODE): vol.In([ZoneMode.TEMPORARY]),
        vol.Optional(CONF_SETPOINT, default=21): vol.All(
            cv.positive_float,
            vol.Range(min=5, max=30),
        ),
        vol.Exclusive(CONF_UNTIL, CONF_UNTIL): cv.datetime,
        vol.Exclusive(CONF_DURATION, CONF_UNTIL): vol.All(
            cv.time_period,
            vol.Range(min=timedelta(minutes=5), max=timedelta(days=1)),
        ),
    }
)
SCH_SET_ZONE_MODE = vol.Any(
    SCH_SET_ZONE_MODE,
    SCH_SET_ZONE_MODE_SETPOINT,
    SCH_SET_ZONE_MODE_UNTIL,
)

SCH_PUT_ZONE_TEMP = _SCH_ENTITY_ID.extend(
    {
        vol.Required(CONF_TEMPERATURE): vol.All(
            vol.Coerce(float), vol.Range(min=-20, max=99)
        ),
    }
)

SCH_SET_ZONE_SCHED = _SCH_ENTITY_ID.extend({vol.Required(CONF_SCHEDULE): cv.string})


SVCS_CLIMATE_EVO_ZONE = {
    SVC_GET_ZONE_SCHED: _SCH_ENTITY_ID,
    SVC_PUT_ZONE_TEMP: SCH_PUT_ZONE_TEMP,
    SVC_RESET_ZONE_CONFIG: _SCH_ENTITY_ID,
    SVC_RESET_ZONE_MODE: _SCH_ENTITY_ID,
    SVC_SET_ZONE_CONFIG: SCH_SET_ZONE_CONFIG,
    SVC_SET_ZONE_MODE: SCH_SET_ZONE_MODE,
    SVC_SET_ZONE_SCHED: SCH_SET_ZONE_SCHED,
}

#
# WaterHeater platform services for CH/DHW
SVC_GET_DHW_SCHED = "get_dhw_schedule"
SVC_PUT_DHW_TEMP = "put_dhw_temp"
SVC_RESET_DHW_MODE = "reset_dhw_mode"
SVC_RESET_DHW_PARAMS = "reset_dhw_params"
SVC_SET_DHW_BOOST = "set_dhw_boost"
SVC_SET_DHW_MODE = "set_dhw_mode"
SVC_SET_DHW_PARAMS = "set_dhw_params"
SVC_SET_DHW_SCHED = "set_dhw_schedule"

SCH_SET_DHW_MODE = _SCH_ENTITY_ID.extend(
    {
        vol.Optional(CONF_MODE): vol.In(
            [ZoneMode.SCHEDULE, ZoneMode.PERMANENT, ZoneMode.TEMPORARY]
        ),
        vol.Optional(CONF_ACTIVE): cv.boolean,
        vol.Exclusive(CONF_UNTIL, CONF_UNTIL): cv.datetime,
        vol.Exclusive(CONF_DURATION, CONF_UNTIL): vol.All(
            cv.time_period,
            vol.Range(min=timedelta(minutes=5), max=timedelta(days=1)),
        ),
    }
)

SCH_SET_DHW_CONFIG = _SCH_ENTITY_ID.extend(
    {
        vol.Optional(CONF_SETPOINT, default=50): vol.All(
            cv.positive_float,
            vol.Range(min=30, max=85),
        ),
        vol.Optional(CONF_OVERRUN, default=5): vol.All(
            cv.positive_int,
            vol.Range(max=10),
        ),
        vol.Optional(CONF_DIFFERENTIAL, default=1): vol.All(
            cv.positive_float,
            vol.Range(max=10),
        ),
    }
)

SCH_PUT_DHW_TEMP = _SCH_ENTITY_ID.extend(
    {
        vol.Required(CONF_TEMPERATURE): vol.All(
            vol.Coerce(float), vol.Range(min=-20, max=99)
        ),
    }
)

SCH_SET_DHW_SCHED = _SCH_ENTITY_ID.extend({vol.Required(CONF_SCHEDULE): cv.string})


SVCS_WATER_HEATER_EVO_DHW = {
    SVC_GET_DHW_SCHED: _SCH_ENTITY_ID,
    SVC_RESET_DHW_MODE: _SCH_ENTITY_ID,
    SVC_RESET_DHW_PARAMS: _SCH_ENTITY_ID,
    SVC_SET_DHW_BOOST: _SCH_ENTITY_ID,
    SVC_SET_DHW_MODE: SCH_SET_DHW_MODE,
    SVC_SET_DHW_PARAMS: SCH_SET_DHW_CONFIG,
    SVC_PUT_DHW_TEMP: SCH_PUT_DHW_TEMP,
    SVC_SET_DHW_SCHED: SCH_SET_DHW_SCHED,
}

#
# BinarySensor/Sensor platform services for HVAC
SZ_CO2_LEVEL = "co2_level"
SZ_INDOOR_HUMIDITY = "indoor_humidity"
SVC_PUT_CO2_LEVEL = f"put_{SZ_CO2_LEVEL}"
SVC_PUT_INDOOR_HUMIDITY = f"put_{SZ_INDOOR_HUMIDITY}"

SCH_PUT_CO2_LEVEL = _SCH_ENTITY_ID.extend(
    {
        vol.Required(SZ_CO2_LEVEL): vol.All(
            cv.positive_int,
            vol.Range(min=0, max=16384),
        ),
    }
)

SCH_PUT_INDOOR_HUMIDITY = _SCH_ENTITY_ID.extend(
    {
        vol.Required(SZ_INDOOR_HUMIDITY): vol.All(
            cv.positive_float,
            vol.Range(min=0, max=100),
        ),
    }
)

SVCS_BINARY_SENSOR = {}

SVCS_SENSOR = {
    SVC_PUT_CO2_LEVEL: SCH_PUT_CO2_LEVEL,
    SVC_PUT_INDOOR_HUMIDITY: SCH_PUT_INDOOR_HUMIDITY,
}

#
# Remote platform services for HVAC
SZ_COMMAND = "command"
SZ_TIMEOUT = "timeout"
SZ_NUM_REPEATS = "num_repeats"
SZ_DELAY_SECS = "delay_secs"
SVC_DELETE_COMMAND = "delete_command"
SVC_LEARN_COMMAND = "learn_command"
SVC_SEND_COMMAND = "send_command"

SCH_VERB_COMMAND_BASE = _SCH_ENTITY_ID.extend({vol.Required(SZ_COMMAND): cv.string})
SCH_DELETE_COMMAND = SCH_VERB_COMMAND_BASE
SCH_LEARN_COMMAND = SCH_VERB_COMMAND_BASE.extend(
    {
        vol.Required(SZ_TIMEOUT, default=60): vol.All(
            cv.positive_int, vol.Range(min=30, max=300)
        )
    }
)
SCH_SEND_COMMAND = SCH_VERB_COMMAND_BASE.extend(
    {
        vol.Required(SZ_NUM_REPEATS, default=3): cv.positive_int,
        vol.Required(SZ_DELAY_SECS, default=0.2): cv.positive_float,
    }
)

SVCS_REMOTE = {
    SVC_DELETE_COMMAND: SCH_DELETE_COMMAND,
    SVC_LEARN_COMMAND: SCH_LEARN_COMMAND,
    SVC_SEND_COMMAND: SCH_SEND_COMMAND,
}

#
# Configuration schema for Integration/domain
SCAN_INTERVAL_DEFAULT = timedelta(seconds=60)
SCAN_INTERVAL_MINIMUM = timedelta(seconds=3)

SZ_ADVANCED_FEATURES = "advanced_features"
SZ_MESSAGE_EVENTS = "message_events"
SZ_DEV_MODE = "dev_mode"
SZ_UNKNOWN_CODES = "unknown_codes"


SCH_ADVANCED_FEATURES = vol.Schema(
    {
        vol.Optional(SVC_SEND_PACKET, default=False): cv.boolean,
        vol.Optional(SZ_MESSAGE_EVENTS, default=None): vol.Any(None, cv.is_regex),
        vol.Optional(SZ_DEV_MODE): cv.boolean,
        vol.Optional(SZ_UNKNOWN_CODES): cv.boolean,
    }
)

SCH_GLOBAL_TRAITS_DICT, SCH_TRAITS = sch_global_traits_dict_factory(
    hvac_traits={vol.Optional("commands"): dict}
)

SCH_GATEWAY_CONFIG = SCH_GATEWAY_CONFIG.extend(
    SCH_ENGINE_DICT,
    extra=vol.PREVENT_EXTRA,
)

SCH_DOMAIN_CONFIG = (
    vol.Schema(
        {
            vol.Optional("ramses_rf", default={}): SCH_GATEWAY_CONFIG,
            vol.Optional(CONF_SCAN_INTERVAL, default=SCAN_INTERVAL_DEFAULT): vol.All(
                cv.time_period, vol.Range(min=SCAN_INTERVAL_MINIMUM)
            ),
            vol.Optional(SZ_ADVANCED_FEATURES, default={}): SCH_ADVANCED_FEATURES,
        },
        extra=vol.PREVENT_EXTRA,  # will be system, orphan schemas for ramses_rf
    )
    .extend(SCH_GLOBAL_SCHEMAS_DICT)
    .extend(SCH_GLOBAL_TRAITS_DICT)
    .extend(sch_packet_log_dict_factory(default_backups=7))
    .extend(SCH_RESTORE_CACHE_DICT)
    .extend(sch_serial_port_dict_factory())
)

SCH_MINIMUM_TCS = vol.Schema(
    {
        vol.Optional("system"): vol.Schema(
            {vol.Required("appliance_control"): vol.Match(r"^10:[0-9]{6}$")}
        ),
        vol.Optional("zones", default={}): vol.Schema(
            {
                vol.Required(str): vol.Schema(
                    {vol.Required("sensor"): vol.Match(r"^01:[0-9]{6}$")}
                )
            }
        ),
    },
    extra=vol.PREVENT_EXTRA,
)


def _is_subset(subset, superset) -> bool:  # TODO: move to ramses_rf?
    """Return True is one dict (or list/set) is a subset of another."""
    if isinstance(subset, dict):
        return all(
            key in superset and _is_subset(val, superset[key])
            for key, val in subset.items()
        )
    if isinstance(subset, list | set):
        return all(
            any(_is_subset(subitem, superitem) for superitem in superset)
            for subitem in subset
        )
    return subset == superset  # not dict, list nor set


@callback
def normalise_config(config: dict) -> tuple[str, dict, dict]:
    """Return a port/client_config/broker_config for the library."""

    config = deepcopy(config)

    config[SZ_CONFIG] = config.pop("ramses_rf")

    port_name, port_config = extract_serial_port(config.pop(SZ_SERIAL_PORT))

    remote_commands = {
        k: v.pop("commands")
        for k, v in config["known_list"].items()
        if v.get("commands")
    }

    broker_keys = (CONF_SCAN_INTERVAL, SZ_ADVANCED_FEATURES, SZ_RESTORE_CACHE)
    return (
        port_name,
        {k: v for k, v in config.items() if k not in broker_keys}
        | {SZ_PORT_CONFIG: port_config},
        {k: v for k, v in config.items() if k in broker_keys}
        | {"remotes": remote_commands},
    )


@callback
def merge_schemas(config_schema: _SchemaT, cached_schema: _SchemaT) -> _SchemaT | None:
    """Return the config schema deep merged into the cached schema."""

    if _is_subset(shrink(config_schema), shrink(cached_schema)):
        _LOGGER.info("Using the cached schema")
        return cached_schema

    merged_schema = deep_merge(config_schema, cached_schema)  # 1st takes precidence

    if _is_subset(shrink(config_schema), shrink(merged_schema)):
        _LOGGER.info("Using a merged schema")
        return merged_schema

    _LOGGER.info("Cached schema is a subset of config schema")
    return None


@callback
def schema_is_minimal(schema: dict) -> bool:
    """Return True if the schema is minimal (i.e. no optional keys)."""

    key: str
    sch: dict

    for key, sch in schema.items():
        if key in ("block_list", "known_list", "orphans_heat", "orphans_hvac"):
            continue

        try:
            _ = SCH_MINIMUM_TCS(shrink(sch))
        except vol.Invalid:
            return False

        if "zones" in sch and list(sch["zones"].values())[0]["sensor"] != key:
            return False

        return True
