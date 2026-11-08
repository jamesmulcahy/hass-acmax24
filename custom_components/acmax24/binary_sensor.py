"""Binary sensors for AC-MAX-24 input signal status and connectivity."""
import logging
from datetime import timedelta

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from acmax24 import ACMax24, Input

# Only the connectivity sensor polls; signal sensors are push-updated.
SCAN_INTERVAL = timedelta(seconds=30)

LOG: logging.Logger = logging.getLogger(__package__)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    if discovery_info is None:
        return
    from .const import DOMAIN
    namespace = discovery_info["namespace"]
    matrix_name = discovery_info["matrix_name"]
    matrix = discovery_info["matrix"]
    sensors = [
        InputSignalSensor(namespace, matrix_name, inp)
        for inp in matrix.get_enabled_inputs()
    ]
    hass.data.setdefault(DOMAIN, {})["signal_sensors"] = sensors
    async_add_entities([*sensors, MatrixConnectedSensor(namespace, matrix_name, matrix)], True)


class MatrixConnectedSensor(BinarySensorEntity):
    """Whether the websocket to the matrix is currently connected. Polled, since
    connect/disconnect don't trigger the notify callback."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = True

    def __init__(self, namespace: str, matrix_name: str, matrix: ACMax24):
        self._matrix = matrix
        self._attr_name = f"{matrix_name} Connected"
        self._attr_unique_id = f"acmax24_{namespace}_{matrix_name}_connected".lower().replace(" ", "_")

    def update(self) -> None:
        self._attr_is_on = self._matrix.connected


class InputSignalSensor(BinarySensorEntity):
    """Reports whether audio is present on an AC-MAX-24 input channel."""

    _attr_device_class = BinarySensorDeviceClass.SOUND
    _attr_should_poll = False

    def __init__(self, namespace: str, matrix_name: str, input: Input):
        self._input = input
        self._attr_name = f"{input.label} Audio"
        self._attr_unique_id = (
            f"acmax24_{namespace}_{matrix_name}_input_{input.index}_signal"
            .lower().replace(" ", "_")
        )

    @property
    def is_on(self) -> bool:
        return self._input.has_audio

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "left_channel": bool(self._input.signal_status & 1),
            "right_channel": bool(self._input.signal_status & 2),
            "signal_status": self._input.signal_status,
        }

    def notify(self):
        if self.hass is None:
            # Entity not yet attached to hass, or already torn down (e.g. platform
            # reload) while the acmax24 background thread is still delivering events.
            return
        self.schedule_update_ha_state()
