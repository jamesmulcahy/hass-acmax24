# hass-acmax24

Home Assistant integration for the [AVPro Edge AC-MAX-24](https://avproedge.com/products/ac-max-24) Audio Matrix. If you do not have one of these devices, then this integration is likely of no use to you.

## Configuration

This is only configurable through `configuration.yaml`, but the only configuration that is necessary is the Hostname or IP of the AC-MAX-24. All other configuration is read directly from the AC-MAX-24 device. It's possible to support configuration through the UI
by implementing the "config flow" mechanism -- PRs are welcome.

To enable this integration, you'll need to install this repo into your config/custom_components directory.  Additionally, you must add the following configuration to your `configuration.yaml`.
```yaml
media_player:
  - platform: acmax24
    host: your.hostname.or.ip.here.com
```

### Source Entity Map (optional)

If your AC-MAX-24 inputs are connected to other Home Assistant media players (e.g. a streaming source per input), you can map each source label to its corresponding `media_player` entity using `source_entity_map`. The integration will then read playback state (title, artist, play/pause) directly from the mapped entity and forward transport commands to it.

```yaml
media_player:
  - platform: acmax24
    host: your.hostname.or.ip.here.com
    source_entity_map:
      "James Matrix": media_player.james_matrix
      "Jo Matrix":    media_player.jo_matrix
```

The map is defined **once per input label**, not once per zone — all zones routing to "James Matrix" automatically read from `media_player.james_matrix` with no additional configuration.

When a zone's current source is in the map:

- `state` reflects the source entity's state (`playing`, `paused`, `idle`, `off`)
- `media_title`, `media_artist`, `media_album_name`, `media_duration`, `media_position` are read from the source entity's attributes
- Play, pause, next track, and previous track controls appear and are forwarded to the source entity
- `active_source_entity_id` and `source_volume_level` are exposed as extra state attributes, which allows automations or other integrations to route volume commands to the correct entity

When a zone's source is not in the map (or `source_entity_map` is omitted entirely), all existing behaviour is unchanged: state shows as `on`, and only volume/mute/source-select controls are available.

## Behavior

This integration uses the AC-MAX-24 "uart" websocket API, in addition to the "cmd" HTTP API. I've not found a way to get the same information out of both APIs. PRs are welcome. The websocket uart is used to monitor the inputs and outputs, and their current state. The "cmd" HTTP API is used to read out the labels/names for all the inputs/outputs (this is the only state which is pulled from that API).

Each _enabled_ AC-MAX-24 output becomes a Media Player in Home Assistant. Each _enabled_ input becomes a source which is selectable
in each of the Media Player entities. All disabled outputs are ignored. Enabling or disabling outputs after the integration has started up, is not supported. It will not make Home Assistant aware of those changes. You must reload the integration to pick up any changes to enabled/disabled states.

Muting, unmuting, selecting sources, and adjusting volume (both in absolute terms, and stepping up and down) are supported by this integration. Transport controls (play, pause, next, previous) are available when a `source_entity_map` is configured and the zone's current source is mapped.

## Bugs

This is my first home assistant integration. This should not be considered "production quality" software; it has no tests, and has
only been manually tested in a single environment (my home). There are likely many bugs, but the known issues at this time are:

- The websocket API will frequently return 'CMD ERROR' in response to requests -- likely because we're not honoring the protocol correctly. As a workaround, all commands are sent twice, this usually means that one or both of the requests succeed. Unfortunately, for non-idempotetnt updates (such as volume step changes), this can mean they are applied twice.
- This appears in the logs: ```2023-11-19 22:42:35.061 ERROR (MainThread) [homeassistant.components.homekit.util] media_player.acmax24_avpro_edge_ac_max_24 does not support any media_player features```

## Limitations

- This integration assumes you're running the AC-MAX-24 in insecure mode, if you have the secure APIs enabled, then this is unlikely to work.
- The following features are not supported
  - Volume Lock/Unlock
  - EQ
  - Balance
  - Follow
