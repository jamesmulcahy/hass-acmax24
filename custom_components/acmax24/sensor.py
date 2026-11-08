"""Diagnostic sensors for AC-MAX-24 connection health."""
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
from acmax24 import ACMax24

# The counters live in the acmax24 library and change without any notify callback
# (CMD ERROR responses and reconnects don't touch an input/output), so poll them.
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    if discovery_info is None:
        return
    namespace = discovery_info["namespace"]
    matrix_name = discovery_info["matrix_name"]
    matrix = discovery_info["matrix"]
    async_add_entities(
        [
            MatrixCounterSensor(namespace, matrix_name, matrix, "command_errors", "Command Errors",
                                lambda m: m.errors, "mdi:alert-circle-outline"),
            MatrixCounterSensor(namespace, matrix_name, matrix, "reconnects", "Reconnects",
                                lambda m: m.reconnects, "mdi:lan-disconnect"),
        ],
        True,
    )


class MatrixCounterSensor(SensorEntity):
    """A monotonically increasing counter read from the ACMax24 library."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_should_poll = True

    def __init__(self, namespace: str, matrix_name: str, matrix: ACMax24, key: str, label: str, read, icon: str):
        self._matrix = matrix
        self._read = read
        self._attr_name = f"{matrix_name} {label}"
        self._attr_icon = icon
        self._attr_unique_id = f"acmax24_{namespace}_{matrix_name}_{key}".lower().replace(" ", "_")

    def update(self) -> None:
        self._attr_native_value = self._read(self._matrix)
