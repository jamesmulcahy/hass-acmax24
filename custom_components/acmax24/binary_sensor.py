"""Binary sensors for AC-MAX-24 input signal status."""
import logging

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from acmax24 import Input

LOG: logging.Logger = logging.getLogger(__package__)


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
        self.schedule_update_ha_state()
