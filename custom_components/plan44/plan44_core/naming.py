"""Display names for channels imported from the bridge.

vdcd names a sensor channel after its full description, value range and unit
included — ``"Temperature, -40.0..62.4 °C"`` or ``"Acceleration X,
-24.52..25.69 m/s2"``. Shown as-is, Home Assistant renders that as
"MultiSensorGarageRec Temperature, -40.0..62.4 °C": the range means nothing to
a user, and the unit is already displayed next to the value.

Only the *displayed* name is cleaned. The subentry keeps exactly what the bridge
reported, so existing installations pick this up on their next start, their
entity IDs stay as registered, and the original text is never lost.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

# ", <min>..<max>" optionally followed by a unit, anchored at the end — so a
# comma that belongs to the actual name ("Room, north") is left alone.
_RANGE_SUFFIX = re.compile(r",\s*-?\d+(?:\.\d+)?\.\.-?\d+(?:\.\d+)?(?:\s+\S.*)?\s*$")


def display_name(name: str) -> str:
    """Strip a trailing value range (and its unit) from a bridge channel name."""
    base = _RANGE_SUFFIX.sub("", name).strip()
    # A name that is nothing but a range has no better form; keep it.
    return base or name.strip()


def display_names(names: Sequence[str]) -> list[str]:
    """Clean one device's channel names without letting two of them collide.

    Channels whose names differ only in their range ("Temperature, 0..50 °C"
    and "Temperature, -40..120 °C") would both become "Temperature" and be
    indistinguishable in the UI. Those keep their original names; every other
    channel is cleaned. The comparison ignores case, because Home Assistant
    derives entity IDs case-insensitively.
    """
    cleaned = [display_name(n) for n in names]
    counts = Counter(c.casefold() for c in cleaned)
    return [
        c if counts[c.casefold()] == 1 else n.strip()
        for n, c in zip(names, cleaned, strict=True)
    ]
