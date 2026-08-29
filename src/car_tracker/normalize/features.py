"""Optional extras a listing's own text says the car already has.

Only FSD for now, and only from the ad's headline - the same source the
colour vocabulary reads, and with the same rule: say nothing rather than
say something wrong. Someone filtering for "cars with FSD already bought"
is filtering on the single most expensive option Tesla sells, and a false
positive wastes a click on a car that does not have it.

The hard part is that FSD is not the only driver-assistance name in these
ads, and the others are cheaper or free:

  Autopilot            standard on every car since 2019 - means nothing
  Enhanced Autopilot   the middle package (EAP), NOT FSD
  Full Self-Driving    what we are looking for
  Volles Potenzial     Tesla's own German name for it, on German ads
  teljes önvezetés     the Hungarian phrasing

So "Autopilot" alone must never count, and neither must a mention that
says the car does NOT have it ("ohne FSD", "FSD nachrüstbar").
"""

from __future__ import annotations

import re

# The names that mean the option is on the car.
_FSD_MARKERS = (
    r"\bfsd\b",
    # "driv", not "driving": AutoScout24 truncates its version field, and a
    # real listing arrives as "... | Full Self-Drivin". Nothing else in a
    # Tesla ad reads "full self driv".
    r"full\s*self[\s-]*driv",
    r"volles?\s+potenzial",  # "Volles Potenzial für autonomes Fahren"
    r"teljes\s+önvezet",     # "teljes önvezetési képesség"
    r"teljes\s+onvezet",
)
_FSD_RE = re.compile("|".join(_FSD_MARKERS), re.I)

# ...and the ways an ad mentions it while telling you the car has not got
# it. Checked against the text immediately around the marker, so "FSD" in
# "ohne FSD" is rejected while "FSD" in "FSD + AHK" is kept.
#
# Three of the first fourteen real matches were not owned FSD at all:
#   Performance DMotor,PDC,AHK+FSD -MIETEN !          (renting)
#   RWD 58 kWh 20" Alu, AutoPilot4.0, FSD 99,- p/mnd  (99/month)
#   Long Range RWD 95,9% SoH [ HW4+FSD SUPERVISED €99 (99/month)
# One in five wrong is far too many for a filter whose whole point is
# "already paid for".
_NEGATIONS = (
    r"ohne",
    r"kein[e]?",
    r"nicht",
    r"no",
    r"without",
    r"nélkül",
    r"nelkul",
    r"nincs",
)
_NEGATED_BEFORE = re.compile(rf"(?:{'|'.join(_NEGATIONS)})[\s\-]+(?:\w+[\s\-]+){{0,2}}$", re.I)
# "nachrüstbar"/"aktivierbar" - retrofittable, i.e. buyable later, not owned.
_NOT_OWNED_AFTER = re.compile(
    r"^[\s\-]{0,3}(?:nachr(?:ü|ue|u)stbar|freischaltbar|aktivierbar|nachr(?:ü|ue|u)sten|nélkül|nelkul|nicht)",
    re.I,
)

# Renting or subscribing to it, in the languages these markets advertise in.
_SUBSCRIPTION = re.compile(
    r"mieten|miete\b|\babo\b|abonnement|subscription|p\s*/?\s*mnd|per\s+maand|/\s*mnd|monatlich|havi\b|/\s*hó",
    re.I,
)
# A money figure of three digits or fewer next to FSD is a recurring price,
# not what the option costs: FSD has never sold for under four figures. The
# currency marker is required so "FSD 19 Zoll" stays a set of wheels.
_RECURRING_PRICE = re.compile(r"€\s*\d{1,3}\b|\b\d{1,3}\s*(?:eur|€)|\b\d{1,3},-", re.I)

_WINDOW = 24


def has_fsd(text: str | None) -> bool:
    """True when the ad says this car already has Full Self-Driving."""
    if not text:
        return False
    for match in _FSD_RE.finditer(text):
        before = text[max(0, match.start() - _WINDOW) : match.start()]
        after = text[match.end() : match.end() + _WINDOW]
        if _NEGATED_BEFORE.search(before) or _NOT_OWNED_AFTER.search(after):
            continue
        if _SUBSCRIPTION.search(before) or _SUBSCRIPTION.search(after):
            continue
        if _RECURRING_PRICE.search(after):
            continue
        return True
    return False
