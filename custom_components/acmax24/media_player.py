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
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.typing import HomeAssistantType
from acmax24 import ACMax24
from ratelimit import limits

from .const import (
    DOMAIN,
    # SERVICE_JOIN,
    # SERVICE_RESTORE,
    # SERVICE_SNAPSHOT,
    # SERVICE_UNJOIN,
)

LOG: logging.Logger = logging.getLogger(__package__)

SUPPORTED_AMP_FEATURES = MediaPlayerEntityFeature.SELECT_SOURCE

SUPPORTED_ZONE_FEATURES = (
    MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default="AVPro Edge AC-MAX-24"): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_ENTITY_NAMESPACE, default="acmax24"): cv.string,
    }
)

# schema for media player service calls
SERVICE_CALL_SCHEMA = vol.Schema({ATTR_ENTITY_ID: cv.comp_entity_ids})

MINUTES = 60

async def async_setup_platform(
    hass: HomeAssistantType, config, async_add_entities, discovery_info=None
):
    """Set up the AVPro Edge Audio Matrix platform."""
    hostname = config.get(CONF_HOST)
    namespace = config.get(CONF_ENTITY_NAMESPACE)
    entities = []
    matrix = None
    matrix_entity = None

    async def notify_callback():
        if matrix_entity:
            await matrix_entity.schedule_ha_update()

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
 
    for output in matrix.get_enabled_outputs():
        LOG.debug("Adding ZoneMediaPlayer for %s", output)
        entities.append(
            # TODO: ZMP should set its own name
            ZoneMediaPlayer(
                namespace, matrix_name, matrix, sources, output
            )
        )

    # Add the master Media Player for the main control unit, with references to all the zones
    matrix_entity = ACMax24Entity(hass, namespace, matrix_name, matrix, sources, entities)
    entities.append(matrix_entity)

    async_add_entities(entities, True)

    # setup the service calls
    # platform = entity_platform.current_platform.get()

    # async def async_service_call_dispatcher(service_call):
    #     entities = await platform.async_extract_from_service(service_call)
    #     if not entities:
    #         return

    #     for entity in entities:
    #         if service_call.service == SERVICE_SNAPSHOT:
    #             await entity.async_snapshot()
    #         elif service_call.service == SERVICE_RESTORE:
    #             await entity.async_restore()

    # # register the save/restore snapshot services
    # for service_call in (SERVICE_SNAPSHOT, SERVICE_RESTORE):
    #     hass.services.async_register(
    #         DOMAIN,
    #         service_call,
    #         async_service_call_dispatcher,
    #         schema=SERVICE_CALL_SCHEMA,
    #     )


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

    async def schedule_ha_update(self):
        self.async_schedule_update_ha_state(force_refresh=True)

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


class ZoneMediaPlayer(MediaPlayerEntity):
    """Representation of a matrix amplifier zone."""

    def __init__(self, namespace, matrix_name, matrix, sources, output):
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
        """Return the powered on state of the zone."""
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
        return SUPPORTED_ZONE_FEATURES

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

    # async def async_snapshot(self):
    #     """Save zone's current state."""
    #     # TODO: Change API call
    #     self._status_snapshot = await self._amp.zone_status(self._zone_id)
    #     LOG.info(f"Saved state snapshot for {self.zone_info}")

    # async def async_restore(self):
    #     """Restore saved state."""
    #     if self._status_snapshot:
    #         await self._amp.restore_zone(self._status_snapshot)
    #         self.async_schedule_update_ha_state(force_refresh=True)
    #         LOG.info(f"Restored previous state for {self.zone_info}")
    #     else:
    #         LOG.warning(
    #             f"Restore service called for {self.zone_info}, but no snapshot previously saved."
    #         )

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
        await self._matrix.set_output_volume(self.zone_info, int(volume * 100))

    async def async_volume_up(self):
        """Volume up the media player."""
        LOG.debug(f"async_volume_up")
        await self._matrix.step_output_volume(self._zone_id, 5)

    async def async_volume_down(self):
        """Volume down media player."""
        LOG.debug(f"FIXME: async_volume_down")
        await self._matrix.step_output_volume(self._zone_id, -5)

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
