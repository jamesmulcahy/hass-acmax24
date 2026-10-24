from homeassistant.const import STATE_OFF, STATE_ON

SONOS = "binary_sensor.sonos_audio"


async def test_signal_sensor_per_enabled_input(hass, matrix):
    assert hass.states.get(SONOS).state == STATE_OFF
    assert hass.states.get("binary_sensor.tv_audio") is not None
    assert hass.states.get(SONOS).attributes["device_class"] == "sound"


async def test_signal_sensor_tracks_device_events(hass, matrix):
    await matrix.push("IN1 SIG STA 2")
    await hass.async_block_till_done()
    state = hass.states.get(SONOS)
    assert state.state == STATE_ON
    assert state.attributes["left_channel"] is False
    assert state.attributes["right_channel"] is True
    assert state.attributes["signal_status"] == 2

    await matrix.push("IN1 SIG STA 0")
    await hass.async_block_till_done()
    assert hass.states.get(SONOS).state == STATE_OFF
