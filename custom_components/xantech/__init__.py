"""
AVPro Edge Audio Matrix Control for Home Assistant
"""
from homeassistant.core import HomeAssistant

PLATFORMS = ["media_player"]

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the AVPro Edge Ac-MAX-24 component."""
    return True
