"""Bucket a source's trim label into the dashboard's variant filter.

Two different kinds of real input feed this:
- AutoScout24's free-text `modelVersionInput`: "Standard Range RWD *1.
  Hand*unfallfrei*", "Dual Performance Dual AWD+PANO+R-KAMERA", "Long Range
  AWD *20-Zoll*", "Rear-Wheel Drive". Sources vary in how much they annotate
  beyond the trim itself (accident history, wheel size) — the phrase check
  below only looks for the trim keywords, everything else is noise.
- Tesla's own `TrimVariantCode`: short codes, confirmed real values "LR_AWD"
  and "RWD" (2026-08-28 sample). Checked first, as an exact match, since
  they're unambiguous where the phrase check would miss them entirely
  ("lr_awd" doesn't contain the substring "long range"). No confirmed
  Performance example seen yet — falls through to the phrase check, which
  only catches it if the literal word "Performance" is present (Tesla often
  keeps it as an English loanword even in a German TrimName, but that's
  unverified).

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

_EXACT_CODES = {
    "lr_awd": LONG_RANGE_AWD,
    "rwd": RWD,
}


def normalize_variant(text: str | None) -> str | None:
    if not text:
        return None
    lowered = text.lower().strip()
    if lowered in _EXACT_CODES:
        return _EXACT_CODES[lowered]
    if "performance" in lowered:
        return PERFORMANCE
    if "long range" in lowered:
        return LONG_RANGE_AWD
    if "rwd" in lowered or "rear-wheel drive" in lowered or "standard range" in lowered:
        return RWD
    return OTHER
