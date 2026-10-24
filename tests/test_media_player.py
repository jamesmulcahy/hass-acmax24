from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_INPUT_SOURCE_LIST,
    ATTR_MEDIA_TITLE,
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_MEDIA_VOLUME_MUTED,
    DOMAIN as MP_DOMAIN,
    MediaPlayerEntityFeature,
)
from homeassistant.components.media_player.const import DATA_COMPONENT
from homeassistant.const import ATTR_ENTITY_ID, ATTR_SUPPORTED_FEATURES, STATE_ON, STATE_UNKNOWN

from custom_components.acmax24.const import DOMAIN

from .conftest import FakeACMax24, setup_platform

KITCHEN = "media_player.acmax24_kitchen"
PATIO = "media_player.acmax24_patio"
MATRIX = "media_player.acmax24_avpro_edge_ac_max_24"


async def call(hass, service, entity_id, domain=MP_DOMAIN, **data):
    await hass.services.async_call(domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True)
    await hass.async_block_till_done()


# --- Setup ---

async def test_creates_zone_and_matrix_entities(hass, matrix):
    kitchen = hass.states.get(KITCHEN)
    assert kitchen.state == STATE_ON
    assert kitchen.attributes[ATTR_INPUT_SOURCE] == "Sonos"
    assert kitchen.attributes[ATTR_INPUT_SOURCE_LIST] == ["Sonos", "TV"]
    assert kitchen.attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0.2
    assert kitchen.attributes[ATTR_MEDIA_VOLUME_MUTED] is False
    assert not kitchen.attributes[ATTR_SUPPORTED_FEATURES] & MediaPlayerEntityFeature.PLAY

    assert hass.states.get(PATIO) is not None
    assert hass.states.get(MATRIX).state == STATE_UNKNOWN


async def test_disabled_outputs_are_not_exposed(hass, fake_matrix_cls):
    with patch.dict("tests.conftest.OUTPUTS", {3: "Kitchen"}, clear=True):
        await setup_platform(hass)
    assert hass.states.get(KITCHEN) is not None
    assert hass.states.get(PATIO) is None


async def test_setup_not_ready_when_start_fails(hass, fake_matrix_cls):
    with patch.object(FakeACMax24, "start", AsyncMock(side_effect=OSError("unreachable"))):
        await setup_platform(hass)
    assert hass.states.get(KITCHEN) is None


async def test_setup_not_ready_without_initial_state(hass, fake_matrix_cls):
    with patch.object(FakeACMax24, "wait_for_initial_state", AsyncMock(return_value=False)):
        await setup_platform(hass)
    assert hass.states.get(KITCHEN) is None


# --- Commands ---

async def test_select_source(hass, matrix):
    await call(hass, "select_source", KITCHEN, source="TV")
    assert matrix.sent == ["SET OUT3 AS IN2\r\n"] * 2


async def test_select_invalid_source_is_ignored(hass, matrix):
    await call(hass, "select_source", KITCHEN, source="Nope")
    assert matrix.sent == []


async def test_matrix_select_source_applies_to_all_zones(hass, matrix):
    await call(hass, "select_source", MATRIX, source="TV")
    assert sorted(matrix.sent) == ["SET OUT3 AS IN2\r\n"] * 2 + ["SET OUT4 AS IN2\r\n"] * 2


async def test_volume_set(hass, matrix):
    await call(hass, "volume_set", KITCHEN, volume_level=0.45)
    assert matrix.sent == ["SET OUT3 VOL 45\r\n"] * 2


@pytest.mark.parametrize("service,cmd", [("volume_up", "VOL + 5"), ("volume_down", "VOL - 5")])
async def test_volume_step(hass, matrix, service, cmd):
    await call(hass, service, KITCHEN)
    assert matrix.sent == [f"SET OUT3 {cmd}\r\n"] * 2


@pytest.mark.parametrize("muted,cmd", [(True, "MUTE"), (False, "UNMUTE")])
async def test_mute(hass, matrix, muted, cmd):
    await call(hass, "volume_mute", KITCHEN, is_volume_muted=muted)
    assert matrix.sent == [f"SET OUT3 {cmd}\r\n"] * 2


# --- Push updates from the device ---

async def test_device_events_update_state(hass, matrix):
    await matrix.push("SET OUT3 VOL 60")
    await matrix.push("SET OUT3 MUTE")
    await matrix.push("OUT3 AS IN2")
    await hass.async_block_till_done()

    kitchen = hass.states.get(KITCHEN)
    assert kitchen.attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0.6
    assert kitchen.attributes[ATTR_MEDIA_VOLUME_MUTED] is True
    assert kitchen.attributes[ATTR_INPUT_SOURCE] == "TV"
    assert kitchen.attributes["icon"] == "mdi:speaker-off"


async def test_zero_volume_reports_none(hass, matrix):
    await matrix.push("SET OUT3 VOL 0")
    await hass.async_block_till_done()
    assert ATTR_MEDIA_VOLUME_LEVEL not in hass.states.get(KITCHEN).attributes


async def test_unknown_input_reports_no_source(hass, matrix):
    await matrix.push("SET OUT3 AS IN0")
    await hass.async_block_till_done()
    assert ATTR_INPUT_SOURCE not in hass.states.get(KITCHEN).attributes


# --- Snapshot / restore ---

async def test_snapshot_and_restore(hass, matrix):
    await call(hass, "snapshot", MATRIX, domain=DOMAIN)
    await matrix.push("SET OUT3 AS IN2")
    await matrix.push("SET OUT3 VOL 90")
    matrix.sent.clear()

    await call(hass, "restore", MATRIX, domain=DOMAIN)

    assert {"SET OUT3 AS IN1\r\n", "SET OUT3 VOL 20\r\n", "SET OUT3 UNMUTE\r\n",
            "SET OUT4 AS IN1\r\n", "SET OUT4 VOL 20\r\n", "SET OUT4 UNMUTE\r\n"} == set(matrix.sent)


async def test_snapshot_on_zone_is_ignored(hass, matrix):
    await call(hass, "snapshot", KITCHEN, domain=DOMAIN)
    await call(hass, "restore", KITCHEN, domain=DOMAIN)
    assert matrix.sent == []


async def test_restore_without_snapshot_is_noop(hass, matrix):
    await call(hass, "restore", MATRIX, domain=DOMAIN)
    assert matrix.sent == []


# --- source_entity_map ---

@pytest.fixture
async def mapped_matrix(hass, fake_matrix_cls):
    hass.states.async_set(
        "media_player.sonos", "playing",
        {"media_title": "Song", "media_artist": "Band", "volume_level": 0.3,
         "media_position_updated_at": "2026-01-01T00:00:00+00:00"},
    )
    await setup_platform(hass, source_entity_map={"Sonos": "media_player.sonos"})
    return fake_matrix_cls.instances[0]


async def test_mapped_source_state_passthrough(hass, mapped_matrix):
    kitchen = hass.states.get(KITCHEN)
    assert kitchen.state == "playing"
    assert kitchen.attributes[ATTR_MEDIA_TITLE] == "Song"
    assert kitchen.attributes["media_artist"] == "Band"
    assert kitchen.attributes["active_source_entity_id"] == "media_player.sonos"
    assert kitchen.attributes["source_volume_level"] == 0.3
    assert kitchen.attributes[ATTR_SUPPORTED_FEATURES] & MediaPlayerEntityFeature.PLAY


async def test_mapped_source_changes_propagate(hass, mapped_matrix):
    hass.states.async_set("media_player.sonos", "paused", {"media_title": "Other"})
    await hass.async_block_till_done()
    kitchen = hass.states.get(KITCHEN)
    assert kitchen.state == "paused"
    assert kitchen.attributes[ATTR_MEDIA_TITLE] == "Other"


async def test_unmapped_source_falls_back(hass, mapped_matrix):
    await mapped_matrix.push("SET OUT3 AS IN2")
    await hass.async_block_till_done()
    kitchen = hass.states.get(KITCHEN)
    assert kitchen.state == STATE_ON
    assert "active_source_entity_id" not in kitchen.attributes
    assert not kitchen.attributes[ATTR_SUPPORTED_FEATURES] & MediaPlayerEntityFeature.PLAY


@pytest.mark.parametrize("method,service", [
    ("async_media_play", "media_play"),
    ("async_media_pause", "media_pause"),
    ("async_media_next_track", "media_next_track"),
    ("async_media_previous_track", "media_previous_track"),
])
async def test_transport_forwarded_to_source(hass, mapped_matrix, method, service):
    zone = hass.data[DATA_COMPONENT].get_entity(KITCHEN)
    with patch("homeassistant.core.ServiceRegistry.async_call", AsyncMock()) as async_call:
        await getattr(zone, method)()
    async_call.assert_awaited_once_with(MP_DOMAIN, service, {ATTR_ENTITY_ID: "media_player.sonos"})


async def test_transport_without_mapping_is_noop(hass, mapped_matrix):
    await mapped_matrix.push("SET OUT3 AS IN2")
    zone = hass.data[DATA_COMPONENT].get_entity(KITCHEN)
    with patch("homeassistant.core.ServiceRegistry.async_call", AsyncMock()) as async_call:
        await zone.async_media_play()
    async_call.assert_not_awaited()
