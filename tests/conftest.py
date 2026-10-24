"""Fixtures for the acmax24 integration tests.

The real acmax24 library is used for Input/Output state and event parsing; only the
network edges (websocket transport, HTTP label fetch) are replaced.
"""
from unittest.mock import patch

import pytest
from acmax24 import ACMax24
from homeassistant.setup import async_setup_component

HOST = "matrix.invalid"

# index -> label
INPUTS = {1: "Sonos", 2: "TV"}
OUTPUTS = {3: "Kitchen", 4: "Patio"}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


class FakeTransport:
    def __init__(self):
        self.sent = []

    async def start(self):
        pass

    async def send(self, message):
        self.sent.append(message)


class FakeACMax24(ACMax24):
    """ACMax24 that is pre-populated as if it had connected and fetched its config."""

    instances = []

    def __init__(self, hostname, notify_callback):
        super().__init__(hostname, notify_callback)
        self._transport = FakeTransport()
        for idx, label in INPUTS.items():
            self._inputs[idx]._label = label
            self._inputs[idx]._enabled = True
        for idx, label in OUTPUTS.items():
            out = self._outputs[idx]
            out._label = label
            out._enabled = True
            out._volume = 20
            out._input_channel = 1
        self._initial_io_config_received = True
        self._initial_labels_fetched = True
        FakeACMax24.instances.append(self)

    def update(self):
        pass

    @property
    def sent(self):
        return self._transport.sent

    async def push(self, msg):
        """Simulate a message arriving from the device websocket."""
        await self._process_event(msg + "\r\n")


@pytest.fixture
def fake_matrix_cls():
    FakeACMax24.instances = []
    with patch("custom_components.acmax24.media_player.ACMax24", FakeACMax24):
        yield FakeACMax24


async def setup_platform(hass, **extra):
    config = {"media_player": [{"platform": "acmax24", "host": HOST, **extra}]}
    assert await async_setup_component(hass, "media_player", config)
    await hass.async_block_till_done()


@pytest.fixture
async def matrix(hass, fake_matrix_cls):
    await setup_platform(hass)
    return fake_matrix_cls.instances[0]
