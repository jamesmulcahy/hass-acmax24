# hass-acmax24

Home Assistant integration for the [AVPro Edge AC-MAX-24](https://avproedge.com/products/ac-max-24) Audio Matrix. If you do not have one of these devices, then this integration is likely of no use to you.

## Configuration

This is only configurable through `configuration.yaml`, but the only configuration that is necessary is the Hostname or IP of the AC-MAX-24. All other configuration is read directly from the AC-MAX-24 device. It's possible to support configuration through the UI
by implementing the "config flow" mechanism -- PRs are welcome.

To enable this integration, you'll need to install this repo into your config/custom_components directory.  Additionally, you must add the following configuration to your `configuration.yaml`.
```
media_player:
  - platform: acmax24
    host: your.hostname.or.ip.here.com
```

## Behavior

This integration uses the AC-MAX-24 "uart" websocket API, in addition to the "cmd" HTTP API. I've not found a way to get the same information out of both APIs. PRs are welcome. The websocket uart is used to monitor the inputs and outputs, and their current state. The "cmd" HTTP API is used to read out the labels/names for all the inputs/outputs (this is the only state which is pulled from that API).

Each _enabled_ AC-MAX-24 output becomes a Media Player in Home Assistant. Each _enabled_ intput becomes a source which is selectable
in each of the Media Player entities. All disabled outputs are ignored. Enabling or disabling outputs after the integration has started up, is not supported. It will not make Home Assistant aware of those changes. You must reload the integration to pick up any changes to enabled/disabled states.

Muting, Unmuting, Selecting Sources, and adjusting volume (both in absolute terms, and stepping up and down) are supported by this integration.

## Bugs

This is my first home assistant integration. This should not be considered "production quality" software; it has no tests, and has
only been manually tested in a single environment (my home). There are likely many bugs, but the known issues at this time are:

- The websocket API will frequently return 'CMD ERROR' in response to requests -- likely because we're not honoring the protocol correctly. As a workaround, all commands are sent twice, this usually means that one or both of the requests succeed. Unfortunately, for non-idempotetnt updates (such as volume step changes), this can mean they are applied twice.

## Limitations

- This integration assumes you're running the AC-MAX-24 in insecure mode, if you have the secure APIs enabled, then this is unlikely to work.
- The following features are not supported
  - Volume Lock/Unlock
  - EQ
  - Balance
  - Follow
