"""Home Assistant Media Player for AVPro Edge AC-MAX-24 Audio Matrix"""

import logging
import asyncio

import voluptuous as vol
from homeassistant.components.media_player import PLATFORM_SCHEMA, MediaPlayerEntity
from homeassistant.components.media_player.const import MediaPlayerEntityFeature

from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_ENTITY_NAMESPACE,
    CONF_NAME,
    CONF_HOST,
    STATE_ON,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import discovery, entity_platform, service
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util
from acmax24 import ACMax24
from ratelimit import limits

from .const import (
    DOMAIN,
    SERVICE_RESTORE,
    SERVICE_SNAPSHOT,
)

LOG: logging.Logger = logging.getLogger(__package__)

CONF_SOURCE_ENTITY_MAP = "source_entity_map"

SUPPORTED_AMP_FEATURES = MediaPlayerEntityFeature.SELECT_SOURCE

SUPPORTED_ZONE_FEATURES = (
    MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
)

TRANSPORT_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default="AVPro Edge AC-MAX-24"): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_ENTITY_NAMESPACE, default="acmax24"): cv.string,
        vol.Optional(CONF_SOURCE_ENTITY_MAP, default={}): {cv.string: cv.entity_id},
    }
)

# schema for media player service calls
SERVICE_CALL_SCHEMA = vol.Schema({ATTR_ENTITY_ID: cv.comp_entity_ids})

MINUTES = 60

async def async_setup_platform(
    hass: HomeAssistant, config, async_add_entities, discovery_info=None
):
    """Set up the AVPro Edge Audio Matrix platform."""
    hostname = config.get(CONF_HOST)
    namespace = config.get(CONF_ENTITY_NAMESPACE)
    source_entity_map = config.get(CONF_SOURCE_ENTITY_MAP, {})
    entities = []
    zone_players = []
    matrix = None
    matrix_entity = None

    LOG.info(f"Configuring acmax24 plugin for {namespace}, hass={hass}")

    async def notify_callback():
        LOG.debug(f"Received notify callback.  matrix_entity={matrix_entity}")
        if matrix_entity:
            matrix_entity.schedule_update_ha_state()
        for zp in zone_players:
            zp.schedule_update_ha_state()
        for sensor in hass.data.get(DOMAIN, {}).get("signal_sensors", []):
            sensor.notify()

    try:
        LOG.info("Setting up %s platform", namespace)
        matrix = ACMax24(hostname, notify_callback)
        LOG.debug("Matrix created, about to start")

        await matrix.start()
        LOG.debug("Started")

        await hass.async_add_executor_job(matrix.update)
        LOG.info("Initial update complete")
    except Exception as e:
        LOG.error(f"Error initializing ACMax24 matrix at {hostname} {e}")
        raise PlatformNotReady

    ready = await matrix.wait_for_initial_state(5)
    if not ready:
        LOG.warn("Initial state not available within timeout, not ready to start platform")
        raise PlatformNotReady

    sources = {
        source.index: source.label for source in  matrix.get_enabled_inputs()
    }

    matrix_name = config.get(CONF_NAME)

    LOG.info(
        f"Creating zone media players for {namespace} '{matrix_name}'; sources={sources}"
    )
    if source_entity_map:
        LOG.info(f"Source entity map configured: {source_entity_map}")

    for output in matrix.get_enabled_outputs():
        LOG.debug("Adding ZoneMediaPlayer for %s", output)
        zp = ZoneMediaPlayer(namespace, matrix_name, matrix, sources, output, source_entity_map)
        entities.append(zp)
        zone_players.append(zp)

    # Add the master Media Player for the main control unit, with references to all the zones
    matrix_entity = ACMax24Entity(hass, namespace, matrix_name, matrix, sources, entities)
    entities.append(matrix_entity)

    async_add_entities(entities, True)

    hass.async_create_task(
        discovery.async_load_platform(
            hass,
            "binary_sensor",
            DOMAIN,
            {"namespace": namespace, "matrix_name": matrix_name, "matrix": matrix},
            config,
        )
    )

    # setup the service calls
    platform = entity_platform.current_platform.get()

    @service.verify_domain_control(DOMAIN)
    async def async_service_call_dispatcher(service_call):
        entities = await platform.async_extract_from_service(service_call)
        if not entities:
            return

        for entity in entities:
            # TODO: Check that I only receive this for the main entity; ignore the rest?
            LOG.info(
                f"Received service call of type {service_call.service} for {entity}"
            )

            if not isinstance(entity, ACMax24Entity):
                LOG.error(f"ignoring service call for {entity}")
                continue

            # If we get here, it should definitely be an ACMax24 entity, so we cna call
            if service_call.service == SERVICE_SNAPSHOT:
                await entity.snapshot()
            elif service_call.service == SERVICE_RESTORE:
                await entity.restore()


    # register the save/restore snapshot services
    for service_call in (SERVICE_SNAPSHOT, SERVICE_RESTORE):
        hass.services.async_register(
            DOMAIN,
            service_call,
            async_service_call_dispatcher,
            schema=cv.make_entity_service_schema({}),
        )


class ACMax24Entity(MediaPlayerEntity):
    """Representation of the entire ACMax24 matrix."""

    def __init__(self, hass, namespace, name, matrix, sources, zone_players):
        self._hass = hass
        self._name = name
        self._matrix = matrix
        self._zone_players = zone_players

        # TODO: Refactor the code that depends on these mappings; the acmax24 library can handle all this directly.
        self._source_id_to_name = sources  # [source_id]   -> source name
        self._source_name_to_id = {
            v: k for k, v in sources.items()
        }  # [source name] -> source_id

        # sort list of source names
        self._source_names = sorted(
            self._source_name_to_id.keys(), key=lambda v: self._source_name_to_id[v]
        )
        # TODO: Ideally the source order could be overridden in YAML config (e.g. TV should appear first on list).
        #       Optionally, we could just sort based on the zone number, and let the user physically wire in the
        #       order they want (doesn't work for pre-amp out channel 7/8 on some Xantech)

        self._unique_id = f"{DOMAIN}_{namespace}_{name}".lower().replace(" ", "_")

    async def async_update(self):
        """Retrieve the latest state from the amp."""
        LOG.debug("async_update scheduling executor job to refresh labels")
        try:
            await self.hass.async_add_executor_job(self._matrix.update)
        except Exception as e:
            LOG.error("async_update encountered exception %s", e)
        LOG.debug("async_update completed label refresh")

    @property
    def unique_id(self):
        """Return unique ID for this device."""
        return self._unique_id

    @property
    def name(self):
        """Return the amp's name."""
        return self._name

    @property
    def state(self):
        """Return the amp's power state."""
        return STATE_UNKNOWN

    @property
    def supported_features(self):
        """Return flag of media commands that are supported."""
        return SUPPORTED_AMP_FEATURES

    @property
    def source_list(self):
        """List of available input sources."""
        return self._source_names

    async def async_select_source(self, source):
        """Set input source for all zones."""
        if source not in self._source_name_to_id:
            LOG.warning(
                f"Selected source '{source}' not valid for {self._name}, ignoring! Sources: {self._source_name_to_id}"
            )
            return

        # set the same source for all zones
        for zone in self._zone_players:
            await zone.async_select_source(source)

    @property
    def icon(self):
        return "mdi:speaker"

    async def snapshot(self):
        """Save matrix current state."""
        LOG.info(f"Saving state snapshot for {self.name}")
        self._status_snapshot = await self._matrix.save_state()
        LOG.info(f"Saved state snapshot for {self.name}")

    async def restore(self):
        """Restore matrix saved state."""
        if self._status_snapshot:
            ## FIXME: This is an async call; how do we make that work?
            LOG.info(f"Restoring previous state for {self.name}")
            await self._matrix.restore_state(self._status_snapshot)
            self.async_schedule_update_ha_state(force_refresh=True)
            LOG.info(f"Restored previous state for {self.name}")
        else:
            LOG.warning(
                f"Restore service called for {self.name}, but no snapshot previously saved."
            )



class ZoneMediaPlayer(MediaPlayerEntity):
    """Representation of a matrix amplifier zone."""

    def __init__(self, namespace, matrix_name, matrix, sources, output, source_entity_map=None):
        """Initialize new zone."""
        self._matrix = matrix
        self._matrix_name = matrix_name
        self._name = output.label
        self._output = output
        # TODO: Rename to output_id
        self._zone_id = output.index
        self._matrix_output = matrix.get_output(output.index)

        self._unique_id = f"{DOMAIN}_{matrix_name}_zone_{output.index}".lower().replace(
            " ", "_"
        )

        LOG.info(f"Creating {self.zone_info} media player")

        self._status = {}
        self._status_snapshot = None

        self._source = None # xxx UPDATE THIS # TODO:
        self._source_id_to_name = sources  # [source_id]   -> source name
        self._source_name_to_id = {
            v: k for k, v in sources.items()
        }  # [source name] -> source_id

        # sort list of source names
        self._source_names = sorted(
            self._source_name_to_id.keys(), key=lambda v: self._source_name_to_id[v]
        )

        # source label -> HA entity_id map (e.g. {"James Matrix": "media_player.james_matrix"})
        self._source_entity_map = source_entity_map or {}

    async def async_added_to_hass(self):
        """Subscribe to source entity state changes once added to HA."""
        if not self._source_entity_map:
            return

        entity_ids = list(self._source_entity_map.values())

        @callback
        def _handle_source_state_change(event):
            changed_entity_id = event.data.get("entity_id")
            if self._current_source_entity_id() == changed_entity_id:
                self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(self.hass, entity_ids, _handle_source_state_change)
        )

    def _current_source_entity_id(self):
        """Return the HA entity_id for the zone's current source, or None if unmapped."""
        current_source = self.source
        if current_source is None:
            return None
        return self._source_entity_map.get(current_source)

    def _source_attr(self, attr):
        """Return an attribute from the current source entity's state, or None."""
        entity_id = self._current_source_entity_id()
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if not state:
            return None
        return state.attributes.get(attr)

    @property
    def zone_info(self):
        return f"{self._matrix_name} zone {self._zone_id} ({self._name})"

    async def async_update(self):
        pass

    @property
    def unique_id(self):
        """Return unique ID for this device."""
        return self._unique_id

    @property
    def name(self):
        """Return the name of the zone."""
        return self._output.label

    @property
    def state(self):
        """Return zone state from the mapped source entity, falling back to STATE_ON."""
        entity_id = self._current_source_entity_id()
        if entity_id:
            source_state = self.hass.states.get(entity_id)
            if source_state:
                return source_state.state
        return STATE_ON

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        v = self._matrix_output.volume
        if v < 1:
            return None
        else:
            return v / 100

    @property
    def is_volume_muted(self):
        """Boolean if output is currently muted."""
        return self._matrix_output.muted

    @property
    def supported_features(self):
        """Return flag of media commands that are supported."""
        features = SUPPORTED_ZONE_FEATURES
        if self._current_source_entity_id() is not None:
            features |= TRANSPORT_FEATURES
        return features

    @property
    def media_title(self):
        return self._source_attr("media_title")

    @property
    def media_artist(self):
        return self._source_attr("media_artist")

    @property
    def media_album_name(self):
        return self._source_attr("media_album_name")

    @property
    def media_duration(self):
        return self._source_attr("media_duration")

    @property
    def media_position(self):
        return self._source_attr("media_position")

    @property
    def media_position_updated_at(self):
        val = self._source_attr("media_position_updated_at")
        if val is None:
            return None
        if hasattr(val, "isoformat"):
            return val
        return dt_util.parse_datetime(val)

    @property
    def entity_picture(self):
        entity_id = self._current_source_entity_id()
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if not state:
            return None
        return state.attributes.get("entity_picture")

    @property
    def extra_state_attributes(self):
        """Expose source entity id and source volume for dual-volume command routing."""
        attrs = {}
        entity_id = self._current_source_entity_id()
        if entity_id:
            attrs["active_source_entity_id"] = entity_id
            source_state = self.hass.states.get(entity_id)
            if source_state:
                attrs["source_volume_level"] = source_state.attributes.get("volume_level")
        return attrs

    @property
    def source(self):
        """Return the current input source of the device."""
        input = None
        try:
            input = self._matrix.get_input(self._matrix_output.input_channel)
        except IndexError:
            pass

        if input:
            return input.label
        else:
            return None

    @property
    def source_list(self):
        """List of available input sources."""
        return self._source_names

    async def async_select_source(self, source):
        """Set input source."""
        if source not in self._source_name_to_id:
            LOG.warning(
                f"Selected source '{source}' not valid for {self.zone_info}, ignoring! Sources: {self._source_name_to_id}"
            )
            return

        source_id = self._source_name_to_id[source]
        LOG.info(f"Switching {self.zone_info} to source {source_id} ({source})")
        await self._matrix.change_input_for_output(self._zone_id, source_id)

    # Note: When HA mutates the attributes, it immediately re-reads them -- but typically we haven't seen
    # the update before it does, so it then takes another refresh cycle before it is observed.  There may be
    # an element of the HA API I'm misunderstanding, but if not, then one option to address this is to track
    # when we've sent a command, and not seen an update yet, and then wait briefly in the accessor functions
    # for an update to arrive, before we return the current state
    async def async_mute_volume(self, mute):
        """Mute (true) or unmute (false) media player."""
        LOG.debug(f"Setting mute={mute} for zone {self.zone_info}")
        await self._matrix.mute_output(self._zone_id, mute)

    async def async_set_volume_level(self, volume):
        """Set volume level, range 0—1.0"""
        LOG.debug(f"Setting zone {self.zone_info} volume to {volume}")
        await self._matrix.set_output_volume(self._zone_id, int(volume * 100))

    async def async_volume_up(self):
        """Volume up the media player."""
        LOG.debug(f"async_volume_up")
        await self._matrix.step_output_volume(self._zone_id, 5)

    async def async_volume_down(self):
        """Volume down media player."""
        LOG.debug(f"FIXME: async_volume_down")
        await self._matrix.step_output_volume(self._zone_id, -5)

    async def _call_source_service(self, service_name):
        """Call a media_player service on the current source entity."""
        entity_id = self._current_source_entity_id()
        if not entity_id:
            LOG.warning(f"No source entity mapped for {self.zone_info}, cannot call {service_name}")
            return
        await self.hass.services.async_call(
            "media_player",
            service_name,
            {ATTR_ENTITY_ID: entity_id},
        )

    async def async_media_play(self):
        await self._call_source_service("media_play")

    async def async_media_pause(self):
        await self._call_source_service("media_pause")

    async def async_media_next_track(self):
        await self._call_source_service("media_next_track")

    async def async_media_previous_track(self):
        await self._call_source_service("media_previous_track")

    @property
    def icon(self):
        if self._output.muted:
            return "mdi:speaker-off"
        return "mdi:speaker"

    # For similar implementation details, see:
    #   https://github.com/home-assistant/core/blob/dev/homeassistant/components/snapcast/media_player.py
    # See also grouped from mini media player (which would need some support for this component):
    #   https://github.com/kalkih/mini-media-player#speaker-group-object
    #
    # TODO:
    #  - implementation should only allow a single group at a time (for simplicity)
    #  - forward all calls to volume/source select calls to all other peers in the group
    #  - calling any method on a grouped zone that is not a master should do what? ignore? remove from group? apply to all in group?
    # #  - should slave group volume adjustments be relative to previous setting or absolutely mirror the master? (downsides to both, but possibly relative is most user friendly)

    # async def async_join(self, master_zone_id, add_zones):
    #     """Join several zones into a group which is controlled/coordinated by a master zone.
    #     All volume/mute/source options to the master zone apply to all zones."""
    #     if not add_zones:
    #         return
    #     LOG.info(f"Adding {self._amp_name} zones {add_zones} to group")
    #     # FIXME: implement

    # async def async_unjoin(self, remove_zones):
    #     """Remove a set of zones from the group (including master will delete the group)"""
    #     if not remove_zones:
    #         return
    #     LOG.info(f"Removing {self._amp_name} zones {remove_zones} from group")
    #     # FIXME: implement
