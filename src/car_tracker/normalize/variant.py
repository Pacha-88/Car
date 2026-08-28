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

Matching is leftmost-wins, not fixed-priority: a real Használtautó.hu title,
"TESLA MODEL Y Long Range AWD (Automata) Kerámia bevonat Performance
díszítésekkel...", states the actual trim ("Long Range AWD") up front and
only mentions "Performance" later as a cosmetic add-on package name — an
earlier fixed-priority version of this function checked for "performance"
unconditionally first and misclassified it. Real ad titles put the actual
trim near the start, so whichever keyword appears earliest is trusted.

Known gap: a handful of markets/years sold a "Long Range RWD" variant, which
this still buckets as "long_range_awd" whenever "long range" appears before
any RWD-signalling phrase, since AWD is by far the common case — will
misclassify that specific combination if it shows up in real data.
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
_RWD_PHRASES = ("rwd", "rear-wheel drive", "standard range")


def normalize_variant(text: str | None) -> str | None:
    if not text:
        return None
    lowered = text.lower().strip()
    if lowered in _EXACT_CODES:
        return _EXACT_CODES[lowered]

    matches: list[tuple[int, str]] = []
    performance_idx = lowered.find("performance")
    if performance_idx != -1:
        matches.append((performance_idx, PERFORMANCE))
    long_range_idx = lowered.find("long range")
    if long_range_idx != -1:
        matches.append((long_range_idx, LONG_RANGE_AWD))
    for phrase in _RWD_PHRASES:
        idx = lowered.find(phrase)
        if idx != -1:
            matches.append((idx, RWD))
            break

    if not matches:
        return OTHER
    return min(matches, key=lambda pair: pair[0])[1]
