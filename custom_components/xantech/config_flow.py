"""Config flow for integration."""
# TODO: Review all this code
import logging

import voluptuous as vol
from homeassistant import config_entries, core
from homeassistant.const import CONF_TIMEOUT

from .const import (  # pylint:disable=unused-import; pylint:disable=unused-import
    CONF_EMAIL,
    CONF_TTY,
    DOMAIN,
)

LOG = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({vol.Required(CONF_TTY): str, vol.Optional(CONF_TIMEOUT): str})


async def validate_input(hass: core.HomeAssistant, data):
    """Validate the user input allows us to connect.
    Data has the keys from DATA_SCHEMA with values provided by the user.
    """

    # Return info that you want to store in the config entry.
    return {"title": data[CONF_TTY]}  # FIXME


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Flo."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    async def async_step_device(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                await self.async_set_unique_id(user_input[CONF_TTY])
                return self.async_create_entry(title=info["title"], data=user_input)
            except Exception:  # pylint: disable=broad-except
                LOG.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="device", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_import(self, user_input):
        """Handle import."""
        await self.async_set_unique_id(user_input[CONF_EMAIL])
        self._abort_if_unique_id_configured()

        return await self.async_step_user(user_input)
