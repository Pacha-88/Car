"""Bucket a source's free-text trim string into the dashboard's variant filter.

Real examples this is built against (AutoScout24 `modelVersionInput`):
"Standard Range RWD *1. Hand*unfallfrei*", "Dual Performance Dual AWD+PANO+
R-KAMERA", "Long Range AWD *20-Zoll*", "Rear-Wheel Drive". Sources vary in
how much they annotate beyond the trim itself (accident history, wheel size,
etc.) — this only looks for the trim keywords, everything else is noise.

Known gap: a handful of markets/years sold a "Long Range RWD" variant, which
this buckets as "long_range_awd" (checking "long range" before drivetrain)
since AWD is by far the common case — will misclassify that specific
combination if it shows up in real data.
"""

from __future__ import annotations

LONG_RANGE_AWD = "long_range_awd"
PERFORMANCE = "performance"
RWD = "rwd"
OTHER = "other"


def normalize_variant(text: str | None) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    if "performance" in lowered:
        return PERFORMANCE
    if "long range" in lowered:
        return LONG_RANGE_AWD
    if "rwd" in lowered or "rear-wheel drive" in lowered or "standard range" in lowered:
        return RWD
    return OTHER
