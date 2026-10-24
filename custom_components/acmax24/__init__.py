"""
AVPro Edge Audio Matrix Control for Home Assistant
"""
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

PLATFORMS = ["media_player"]

CONFIG_SCHEMA = cv.platform_only_config_schema(DOMAIN)

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the AVPro Edge Ac-MAX-24 component."""
    return True
