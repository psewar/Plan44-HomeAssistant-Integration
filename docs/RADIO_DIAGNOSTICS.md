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
| **Packet interval** (minutes) | derived from `x-p44-packetAge` | Time between the last two packets the bridge received, measured across polls. **Unknown** until two packets have been seen, also after every Home Assistant restart. Packets closer together than the poll interval count as one. |
| **Signal strength** (dBm) | `x-p44-rssi` | Signal strength of that last packet. |
| **Repeater count** | `x-p44-repeaterCount` | Repeaters the last packet passed through; `0` = received directly. EnOcean only. |
| **Active** (Yes/No) | `active` | The bridge's own verdict whether the device is still present. |
| **Operating state** | `x-p44-opStateText` | The bridge's one-line summary, e.g. `-68dBm1 Rep., ` or `timeout, unseen`. |
| **Low battery** | binary input with `sensorFunction` 12 | The device's low-battery input. For an energy-harvesting valve it is the energy store, see below. **Unknown** while the bridge has no fresh value. Only for devices that have such an input and are not imported, because an imported device already shows the input as one of its channels. |

All of them are diagnostic entities. An imported device keeps them on its own
Home Assistant device. Any other device gets a diagnostics-only device, named
as the bridge names it. Devices learned into the bridge later appear with the
next poll. The option costs one extra web-API request per poll interval.

The timestamp is computed from the packet age the bridge reports, so the
bridge's clock does not matter. It only moves when a new packet arrives, not
with every poll.

Example values from a P44-DSB-E2 (vdcd 2.8.4.6):

| Device | Last radio packet | Interval | Signal | Repeaters | Active | Low battery | Operating state |
|---|---|---|---|---|---|---|---|
| MVA009 heating valve | 2 min ago | 10 min | −71 dBm | 1 | Yes | Normal | `-71dBm1 Rep., ` |
| MVA009 heating valve, no longer hears the bridge | 52 min ago | 60 min | −70 dBm | 1 | Yes | unknown | `-70dBm1 Rep., ` |
| MVA004 heating valve | 5 min ago | 10 min | −70 dBm | 0 | Yes | Normal | `-70dBm` |
| MVA004 heating valve, silent | unknown | unknown | unknown | unknown | No | unknown | `timeout, unseen` |
| Rocker switch, not pressed | unknown | unknown | unknown | unknown | Yes | — | `unseen` |

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

## Energy-harvesting valves

Micropelt valves power themselves from the radiator's heat and keep a reserve
in an internal store. When more energy is used than harvested over a longer
time, the valve reports it with its energy-storage bit (A5-20-06: the ES bit,
at about 25 % left; an MVA004 sets the A5-20-01 bit vdcd reads in step with it).
The bridge passes that on as the **Low battery** input. If the store keeps
draining, the valve opens to at least 50 % and stops transmitting until the
radiator has recharged it. From then on **Last radio packet** shows the
silence as well.

The input goes **unknown** when the valve has not reported within its alive
interval (40 min): vdcd then drops the value rather than keep a stale one.

Whether a valve is harvesting right now is **not available**: vdcd only writes
that bit to its log and has no property for it.

## A valve that no longer hears the bridge

An A5-20-06 valve that gets no answers from the bridge (after six attempts)
sets a radio-error bit, keeps regulating on its own and transmits only **once an
hour** from then on. The bridge still receives those packets. The valve
therefore stays active, its last radio packet is never older than about an
hour, and a two-hour alert does not fire, even though the valve no longer
follows the room controller. vdcd logs the bit (`communication ERROR`) but has
no property for it.

**Packet interval** is what shows it. Over four weeks on one installation:

- Healthy valves sent every 10 minutes (median). Their longest gaps were
  30–50 minutes, and once 98 minutes.
- Two valves that had lost the downlink sat at 60 minutes all the time.

So `numeric_state` above 45 minutes, held for 3 hours, separates the two (see
the example below). The `for` part ignores a single long gap of a healthy
valve. Because the interval is unknown again after every Home Assistant
restart, such a trigger re-arms by itself.

An **A5-20-01 valve (MVA004)** in the same situation regulates to 21 °C but
keeps its 10-minute interval, and its profile has no radio-error bit. It
cannot be told apart from a healthy one.

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
  - trigger: state
    entity_id: binary_sensor.mva009_living_room_low_battery
    to: "on"
    id: energy
  # Hourly packets for 3 h: the valve no longer hears the bridge.
  - trigger: numeric_state
    entity_id: sensor.mva009_living_room_packet_interval
    above: 45
    for: "03:00:00"
    id: downlink
  # Daily re-check of the states a Home Assistant restart leaves untriggered.
  - trigger: time
    at: "08:00:00"
    id: daily
conditions:
  - condition: or
    conditions:
      - condition: trigger
        id: [silent, unseen, inactive, energy, downlink]
      - condition: state
        entity_id: sensor.mva009_living_room_last_radio_packet
        state: unknown
        for: "02:00:00"
      - condition: state
        entity_id: binary_sensor.mva009_living_room_active
        state: "off"
      - condition: state
        entity_id: binary_sensor.mva009_living_room_low_battery
        state: "on"
actions:
  - action: notify.notify
    data:
      message: >-
        Heating valve ({{ trigger.id }}):
        {{ state_attr(trigger.entity_id, 'friendly_name')
           if trigger.entity_id else 'daily check' }}
```

Restarts are why the daily check is there. Automations attach their triggers
only once Home Assistant has started, and a `state … for` trigger reacts to a
state *change*. After a restart a valve is usually `unknown` already by then,
so the `unseen` trigger does not fire. The `state` conditions measure `for`
from the last change, so they still work after a restart once Home Assistant
has run for two hours. The `downlink` trigger needs no daily check, because the
packet interval starts out unknown after every restart.

One gap remains without templates. The `time … offset` trigger is re-armed on
start, but only for a deadline that is still ahead, and no native condition
compares a timestamp with the current time. A deadline that passes while Home
Assistant is down therefore goes unreported. With several valves, list them all
in each trigger and add `match: any` to the conditions.
