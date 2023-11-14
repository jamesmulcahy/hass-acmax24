"""Home Assistant Media Player for AVPro Edge AC-MAX-24 Audio Matrix"""

import logging

import voluptuous as vol
from homeassistant.components.media_player import PLATFORM_SCHEMA, MediaPlayerEntity
from homeassistant.components.media_player.const import MediaPlayerEntityFeature

from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_ENTITY_NAMESPACE,
    CONF_NAME,
    CONF_HOSTNAME,
    STATE_OFF,
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

LOG = logging.getLogger(__name__)

# TODO: Review this; is there any value in this entity at all?
SUPPORTED_AMP_FEATURES = MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF | MediaPlayerEntityFeature.SELECT_SOURCE

SUPPORTED_ZONE_FEATURES = (
    MediaPlayerEntityFeature.SELECT_SOURCE
    # MediaPlayerEntityFeature.VOLUME_MUTE
    # | SUPPORT_VOLUME_SET
    # | SUPPORT_VOLUME_STEP
    # | SUPPORT_TURN_ON
    # | SUPPORT_TURN_OFF
)

CONF_SERIAL_NUMBER = "serial_number"  # allow for true unique id
CONF_SOURCES = "sources"
CONF_ZONES = "zones"
CONF_DEFAULT_SOURCE = "default_source"

SOURCE_IDS = vol.All(vol.Coerce(int), vol.Range(min=1, max=24))
SOURCE_SCHEMA = vol.Schema(
    {vol.Required(CONF_NAME, default="Unknown Source"): cv.string}
)

ZONE_IDS = vol.All(
    vol.Coerce(int),
    vol.Any(
        vol.Range(min=1, max=24),
    ),
)

# TODO: Read this from the acmax24 api
ZONE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default="Audio Zone"): cv.string,
        vol.Optional(CONF_DEFAULT_SOURCE): cv.positive_int,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default="AVPro Edge AC-MAX-24"): cv.string,
        vol.Required(CONF_HOSTNAME): cv.string,
        vol.Optional(CONF_ENTITY_NAMESPACE, default="acmax24"): cv.string,
        vol.Required(CONF_ZONES): vol.Schema({ZONE_IDS: ZONE_SCHEMA}),
        vol.Required(CONF_SOURCES): vol.Schema({SOURCE_IDS: SOURCE_SCHEMA}),
    }
)

# schema for media player service calls
SERVICE_CALL_SCHEMA = vol.Schema({ATTR_ENTITY_ID: cv.comp_entity_ids})

MINUTES = 60

async def async_setup_platform(
    hass: HomeAssistantType, config, async_add_entities, discovery_info=None
):
    """Set up the AVPro Edge Audio Matrix platform."""
    hostname = config.get(CONF_HOSTNAME)
    namespace = config.get(CONF_ENTITY_NAMESPACE)
    entities = []
    matrix = None

    try:
        hostname = config.get(CONF_HOSTNAME)
        matrix = ACMax24(hostname)
        await matrix.start()
    except Exception:
        LOG.error(f"Error initializing ACMax24 matrix at {hostname}")
        raise PlatformNotReady

    sources = {
        # JM: sources come from here; move to pulling them from the library
        source_id: extra[CONF_NAME] for source_id, extra in config[CONF_SOURCES].items()
    }

    matrix_name = config.get(CONF_NAME)

    LOG.info(
        f"Creating zone media players for {namespace} '{matrix_name}'; sources={sources}"
    )

    # TODO: Switch to this!
    # for output in matrix.get_enabled_outputs():
    #     entities.append(
    #         ZoneMediaPlayer(
    #             namespace, matrix_name, matrix, sources, output
    #         )
    #     )
    # for zone_id, extra in config[CONF_ZONES].items():
    #     entities.append(
    #         ZoneMediaPlayer(
    #             namespace, matrix_name, matrix, sources, zone_id, extra[CONF_NAME]
    #         )
    #     )

    # Add the master Media Player for the main control unit, with references to all the zones
    entities.append(ACMax24Entity(namespace, matrix_name, matrix, sources, entities))

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

    def __init__(self, namespace, name, matrix, sources, zone_players):
        self._name = name
        self._matrix = matrix
        self._zone_players = zone_players

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
        LOG.debug("async_update() is empty")
        return

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

    # TODO: Why declare this feature, if there's nothing that happens?
    async def async_turn_on(self):
        """Turn the media player on."""
        LOG.debug(f"Turning ON amp: {self._name}")

    # TODO: Why declare this feature, if there's nothing that happens?
    async def async_turn_off(self):
        """Turn the media player off."""
        LOG.debug(f"Turning OFF amp: {self._name}")

    @property
    def icon(self):
        return "mdi:speaker"


class ZoneMediaPlayer(MediaPlayerEntity):
    """Representation of a matrix amplifier zone."""

    def __init__(self, namespace, matrix_name, matrix, sources, zone_id, zone_name):
        """Initialize new zone."""
        self._matrix = matrix
        self._matrix_name = matrix_name
        self._name = zone_name
        self._zone_id = zone_id
        self._matrix_output = matrix.get_output(zone_id)

        # FIXME: since this should be a logical media player...why is it not good enough for the user
        # specified name to represent this?  Other than it could be changed...
        self._unique_id = f"{DOMAIN}_{matrix_name}_zone_{zone_id}".lower().replace(
            " ", "_"
        )

        LOG.info(f"Creating {self.zone_info} media player")

        self._status = {}
        self._status_snapshot = None

        self._source = None
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

    @property
    def zone_info(self):
        return f"{self._matrix_name} zone {self._zone_id} ({self._name})"

    # TODO: We don't really need this; unless we use this to refresh input/output names in the API?
    async def async_update(self):
        """Retrieve the latest state."""
        try:
            LOG.debug(f"Updating {self.zone_info}")
            # TODO: Update state
            # status = await self._amp.zone_status(self._zone_id)
            # if not status:
            #     return
        except Exception as e:
            # log up to two times within a specific period to avoid saturating the logs
            @limits(calls=2, period=10 * MINUTES)
            def log_failed_zone_update(e):
                LOG.warning(f"Failed updating {self.zone_info}: {e}")

            log_failed_zone_update(e)
            return

        LOG.debug(f"{self.zone_info} status update: {status}")
        # self._status = status

        # source_id = status.get("source")
        # if source_id:
        #     source_name = self._source_id_to_name.get(source_id)
        #     if source_name:
        #         self._source = source_name
        #     else:
        #         # TODO: Remove this if we start getting IO config from the device itself.
        #         # sometimes the client may have not configured a source, but if the amplifier is set
        #         # to a source other than one defined, go ahead and dynamically create that source. This
        #         # could happen if the user changes the source through a different app or command.
        #         source_name = f"Source {source_id}"
        #         LOG.warning(
        #             f"Undefined source id {source_id} for {self.zone_info}, adding '{source_name}'!"
        #         )
        #         self._source_id_to_name[source_id] = source_name
        #         self._source_name_to_id[source_name] = source_id

    @property
    def unique_id(self):
        """Return unique ID for this device."""
        return self._unique_id

    @property
    def name(self):
        """Return the name of the zone."""
        return self._name

    @property
    def state(self):
        """Return the powered on state of the zone."""
        return STATE_ON
        # power = self._status.get("power")
        # if power is not None and power is True:
        #     return STATE_ON
        # else:
        #     return STATE_OFF

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
        # FIXME: what about when volume == 0?
        return self._matrix_output.muted

    @property
    def supported_features(self):
        """Return flag of media commands that are supported."""
        return SUPPORTED_ZONE_FEATURES

    @property
    def source(self):
        """Return the current input source of the device."""
        return self._source

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

    # TODO: Remove this?
    async def async_turn_on(self):
        """Turn the media player on."""
        LOG.debug(f"FIXME: Turning ON {self.zone_info}")
        # await self._amp.set_power(self._zone_id, True)

        # schedule a poll of the status of the zone ASAP to pickup volume levels/etc
        # self.async_schedule_update_ha_state(force_refresh=True)

    # TODO: Remove this?
    async def async_turn_off(self):
        """Turn the media player off."""
        LOG.debug(f"FIXME: Turning OFF {self.zone_info}")
        # await self._amp.set_power(self._zone_id, False)

    # TODO: Implement this in the acmax24 library
    async def async_mute_volume(self, mute):
        """Mute (true) or unmute (false) media player."""
        LOG.debug(f"FIXME: Setting mute={mute} for zone {self.zone_info}")
        #await self._amp.set_mute(self._zone_id, mute)

    # TODO: Implement this
    async def async_set_volume_level(self, volume):
        """Set volume level, range 0—1.0"""
        amp_volume = int(volume * MAX_VOLUME)
        LOG.debug(
            f"FIXME: Setting zone {self.zone_info} volume to {amp_volume} (HA volume {volume}"
        )
        # await self._amp.set_volume(self._zone_id, amp_volume)

    # TODO: Implement this
    async def async_volume_up(self):
        """Volume up the media player."""
        LOG.debug(f"FIXME: async_volume_up")
    
        # volume = self._status.get("volume")
        # if volume is None:
        #     return

        # FIXME: call the volume up API on the amp object, instead of manually increasing volume
        # reminder the volume is on the amplifier scale (0-38), not Home Assistants (1-100)
        # await self._amp.set_volume(self._zone_id, min(volume + 1, MAX_VOLUME))

    # TODO: Implement this
    async def async_volume_down(self):
        """Volume down media player."""
        LOG.debug(f"FIXME: async_volume_down")
        # volume = self._status.get("volume")
        # LOG.debug(f"FIXME: async_volume_down")
        # if volume is None:
        #     return

        # FIXME: call the volume down API on the amp object, instead of manually increasing volume
        # reminder the volume is on the amplifier scale (0-38), not Home Assistants (1-100)
        # await self._amp.set_volume(self._zone_id, max(volume - 1, 0))

    @property
    def icon(self):
        if self.is_volume_muted:
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
