from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_component import async_update_entity

ERRORS = "sensor.avpro_edge_ac_max_24_command_errors"
RECONNECTS = "sensor.avpro_edge_ac_max_24_reconnects"
CONNECTED = "binary_sensor.avpro_edge_ac_max_24_connected"


async def test_diagnostic_entities_created(hass, matrix):
    registry = er.async_get(hass)
    for entity_id in (ERRORS, RECONNECTS, CONNECTED):
        assert hass.states.get(entity_id) is not None, entity_id
        assert registry.async_get(entity_id).entity_category == EntityCategory.DIAGNOSTIC

    assert hass.states.get(ERRORS).state == "0"
    assert hass.states.get(ERRORS).attributes["state_class"] == "total_increasing"
    assert hass.states.get(RECONNECTS).state == "0"
    assert hass.states.get(CONNECTED).attributes["device_class"] == "connectivity"


async def test_command_errors_counted(hass, matrix):
    await matrix.push("CMD ERROR")
    await matrix.push("CMD ERROR")
    await async_update_entity(hass, ERRORS)
    assert hass.states.get(ERRORS).state == "2"


async def test_reconnects_reported(hass, matrix):
    matrix._transport.reconnects = 3
    await async_update_entity(hass, RECONNECTS)
    assert hass.states.get(RECONNECTS).state == "3"


async def test_connected_tracks_socket(hass, matrix):
    matrix._transport.socket = None
    await async_update_entity(hass, CONNECTED)
    assert hass.states.get(CONNECTED).state == STATE_OFF

    matrix._transport.socket = object()
    await async_update_entity(hass, CONNECTED)
    assert hass.states.get(CONNECTED).state == STATE_ON
