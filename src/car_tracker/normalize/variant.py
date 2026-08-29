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

The long-range vocabulary is wider than the words Tesla uses. Sellers
write "LongRange", "Long-Range", "Long R.", a bare "LR", and German ads
say "Maximale Reichweite" outright. Measured over 621 live listings those
five spellings account for 19 of the 83 cars sitting in the catch-all
bucket, and not one of them fires on a car another keyword already
places, so none can move a correct answer.

What is deliberately NOT in here is "Dual Motor" / "Allradantrieb" on its
own. It would place ten more cars and it would be a guess: Performance is
dual-motor AWD too, so a title saying only "Dual AWD" is genuinely
ambiguous between the two, and this returns the catch-all rather than
invent a trim - the same rule colour extraction follows.

"Long Range RWD" is its own bucket, not a guess between the two: it showed
up 22 times in the first 621 real listings (it is the current single-motor
Long Range Model Y in the EU), and bucketing those as long_range_awd made
every one of them read as a below-market "deal" against the pricier AWD
baseline. The rule: both a "long range" and an RWD signal present, with no
AWD signal anywhere in the text ("Long Range Dual Motor AWD" keeps its AWD
bucket because "AWD" is right there).
"""

from __future__ import annotations

import re

LONG_RANGE_AWD = "long_range_awd"
LONG_RANGE_RWD = "long_range_rwd"
PERFORMANCE = "performance"
RWD = "rwd"
OTHER = "other"

_EXACT_CODES = {
    "lr_awd": LONG_RANGE_AWD,
    "lr_rwd": LONG_RANGE_RWD,  # unconfirmed in a live Tesla sample, but the obvious sibling of lr_awd
    "rwd": RWD,
}
# `long\s*range` covers "long range" and the unspaced "longrange"; the
# hyphenated forms are flattened to spaces before matching. `\blr\b` and
# `perf\.` are bounded so they cannot fire from inside another word.
_LONG_RANGE_RE = re.compile(r"long\s*range|maximale\s+reichweite|long\s*r\.|\blr\b")
_PERFORMANCE_RE = re.compile(r"performance|\bperf\.")
_RWD_RE = re.compile(r"rwd|rear wheel drive|standard range")
_AWD_SIGNALS = ("awd", "allrad", "dual motor", "4x4", "4wd")


def normalize_variant(text: str | None) -> str | None:
    if not text:
        return None
    lowered = text.lower().strip()
    if lowered in _EXACT_CODES:
        return _EXACT_CODES[lowered]
    # Sellers hyphenate freely - "Long-Range", "Rear-Wheel Drive" - and a
    # hyphen defeated the phrase match: a real "Long-Range Dual Motor
    # Performance AWD" fell through "long range" entirely. One separator
    # style before matching.
    lowered = lowered.replace("-", " ")

    matches: list[tuple[int, str]] = []
    performance = _PERFORMANCE_RE.search(lowered)
    if performance:
        matches.append((performance.start(), PERFORMANCE))
    long_range = _LONG_RANGE_RE.search(lowered)
    if long_range:
        matches.append((long_range.start(), LONG_RANGE_AWD))
    rwd = _RWD_RE.search(lowered)
    if rwd:
        matches.append((rwd.start(), RWD))

    if not matches:
        return OTHER
    winner = min(matches, key=lambda pair: pair[0])[1]
    # "Long Range" + an RWD signal, and nothing anywhere saying AWD: that is
    # the single-motor Long Range, a distinct trim with its own price level,
    # not a Long Range AWD with noise after it.
    if (
        winner in (LONG_RANGE_AWD, RWD)
        and long_range is not None
        and any(kind == RWD for _, kind in matches)
        and not any(signal in lowered for signal in _AWD_SIGNALS)
    ):
        return LONG_RANGE_RWD
    return winner
