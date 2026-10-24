# Radio diagnostics for wireless devices

A battery-powered or energy-harvesting EnOcean device that stops transmitting
can go unnoticed for weeks. digitalSTROM keeps showing zone values, and a
heating valve that loses its radio link falls back to regulating on its own
built-in sensor. The room is still heated, just no longer controlled. The
bridge knows when it last heard from each device. This option brings that into
Home Assistant.

## Turning it on

Open **Settings → Devices & Services → plan44 → Configure** and enable
**Radio diagnostics for wireless devices**. It needs the web API user and
password (see [Configuration](CONFIGURATION.md#web-api-for-importing-devices)).
Saving reloads the entry.

## What you get

Every device the bridge tracks radio packets for gets the entities below,
**whether or not it is imported**. That covers all EnOcean devices, and also
ELDAT and ZF devices where present. The bridge has the packet-age property only
on radio devices, so that property alone decides which devices get them.

| Entity | Bridge property | Meaning |
|---|---|---|
| **Last radio packet** (timestamp) | `x-p44-packetAge` | When the bridge last received a packet from the device. **Unknown** while it has received none since the bridge (vdcd) started. |
| **Signal strength** (dBm) | `x-p44-rssi` | Signal strength of that last packet. |
| **Repeater count** | `x-p44-repeaterCount` | Repeaters the last packet passed through; `0` = received directly. EnOcean only. |
| **Active** (Yes/No) | `active` | The bridge's own verdict whether the device is still present. |
| **Operating state** | `x-p44-opStateText` | The bridge's one-line summary, e.g. `-68dBm1 Rep., ` or `timeout, unseen`. |

All of them are diagnostic entities. An imported device keeps them on its own
Home Assistant device. Any other device gets a diagnostics-only device, named
as the bridge names it. Devices learned into the bridge later appear with the
next poll. The option costs one extra web-API request per poll interval.

The timestamp is computed from the packet age the bridge reports, so the
bridge's clock does not matter. It only moves when a new packet arrives, not
with every poll.

Example values from a P44-DSB-E2 (vdcd 2.8.4.6):

| Device | Last radio packet | Signal | Repeaters | Active | Operating state |
|---|---|---|---|---|---|
| MVA009 heating valve | 2 min ago | −71 dBm | 1 | Yes | `-71dBm1 Rep., ` |
| MVA004 heating valve | 5 min ago | −70 dBm | 0 | Yes | `-70dBm` |
| MVA004 heating valve, silent | unknown | unknown | unknown | No | `timeout, unseen` |
| Rocker switch, not pressed | unknown | unknown | unknown | Yes | `unseen` |

## What "Active" does and does not tell you

vdcd marks a device inactive only after four of its alive-sign intervals have
passed without a packet, and only for profiles that define one:

- **A5-20-01 valves** (e.g. Micropelt MVA004) go inactive after about
  2 h 40 min without a packet.
- **A5-20-06 valves** (e.g. Micropelt MVA009, MVA005) have no alive check at
  all. The bridge keeps them **active however long they are silent**. For
  these, only **Last radio packet** shows the problem.
- **Rocker switches, contacts and motion sensors** often transmit only when
  something happens. For them, an old or unknown last packet is normal.

So for heating valves, watch **Last radio packet** rather than **Active**.

**Summer mode:** while the digitalSTROM climate control is idle, vdcd sets
A5-20-06 valves to an 8-hour wake cycle. In heating mode they report every 2, 5
or 10 minutes. An alert threshold of a few hours therefore fires in summer.
Pause such an alert outside the heating season, or use a longer threshold
then.

## Example: alert when a valve stops transmitting

This example uses native triggers and conditions only (templates appear only in
the message):

```yaml
alias: Heating valve stopped transmitting
mode: queued
triggers:
  # Fires 2 h after the last packet unless a newer packet arrives first.
  - trigger: time
    at:
      - entity_id: sensor.mva009_living_room_last_radio_packet
        offset: "02:00:00"
    id: silent
  # No packet at all since the bridge (re)started.
  - trigger: state
    entity_id: sensor.mva009_living_room_last_radio_packet
    to: unknown
    for: "02:00:00"
    id: unseen
  - trigger: state
    entity_id: binary_sensor.mva009_living_room_active
    to: "off"
    id: inactive
  # Daily re-check of the states a Home Assistant restart leaves untriggered.
  - trigger: time
    at: "08:00:00"
    id: daily
conditions:
  - condition: or
    conditions:
      - condition: trigger
        id: [silent, unseen, inactive]
      - condition: state
        entity_id: sensor.mva009_living_room_last_radio_packet
        state: unknown
        for: "02:00:00"
      - condition: state
        entity_id: binary_sensor.mva009_living_room_active
        state: "off"
actions:
  - action: notify.notify
    data:
      message: >-
        Heating valve silent ({{ trigger.id }}):
        {{ state_attr(trigger.entity_id, 'friendly_name')
           if trigger.entity_id else 'daily check' }}
```

Restarts are why the daily check is there. Automations attach their triggers
only once Home Assistant has started, and a `state … for` trigger reacts to a
state *change*. After a restart a valve is usually `unknown` already by then,
so the `unseen` trigger does not fire. The `state` conditions measure `for` from the last change, so
they still work after a restart once Home Assistant has run for two hours.

One gap remains without templates. The `time … offset` trigger is re-armed on
start, but only for a deadline that is still ahead, and no native condition
compares a timestamp with the current time. A deadline that passes while Home
Assistant is down therefore goes unreported. With several valves, list them all
in each trigger and add `match: any` to the conditions.
