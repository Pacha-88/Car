"""One colour vocabulary for every source.

The dashboard's colour filter was structurally dead: of 621 real listings
exactly one carried a colour, because only tesla.py ever set the field and
only when Tesla's response happened to include a paint code. The filter
offered "Unknown" for 620 cars and "Black" for one.

Two different shapes feed this:

- AutoScout24 has no colour field at all, but its offer URLs are built as
  `{make}-{model}-{version text}-{fuel}-{colour}-cat_ma…mo…-{uuid}`, so the
  last token before `-cat_` is the colour when one is recorded and the fuel
  word itself when none is. Verified across 234 live listings in six
  markets: 221 ended in a colour (white, black, grey, blue, red, silver),
  13 ended in "electric", and none failed to match the shape.
- Tesla's own paint codes ("PEARL_WHITE_MULTI_COAT", "MIDNIGHT_SILVER").

Both land on the same basic words, which is what makes the filter usable -
a chip row split between "Black" and "Solid_black" would be no better than
none. Anything this cannot place returns None and shows as Unknown rather
than inventing a colour; that also makes the function its own guard against
a stray version-text token being read as a colour.
"""

from __future__ import annotations

import re

# Ordered: the first base word found wins, so a compound paint name lands on
# the colour it is a shade of ("midnight silver" -> silver).
BASE_COLORS = (
    "white",
    "black",
    "silver",
    "grey",
    "gray",
    "blue",
    "red",
    "green",
    "brown",
    "beige",
    "yellow",
    "orange",
    "gold",
    "bronze",
    "purple",
    "violet",
)

_ALIASES = {"gray": "grey", "violet": "purple"}

# Paint names that spell a colour without a word boundary to find it by.
# Matching on bare substrings instead would be worse than missing these:
# "red" alone is inside plenty of words that are not colours. Extend this
# as new one-word names turn up.
_WHOLE_NAMES = {"quicksilver": "silver"}


def normalize_color(raw: str | None) -> str | None:
    """A basic colour word, or None when the text names no colour."""
    if not raw:
        return None
    text = re.sub(r"[_\-]+", " ", raw.strip().lower())
    if text in _WHOLE_NAMES:
        return _WHOLE_NAMES[text]
    for base in BASE_COLORS:
        if re.search(rf"\b{base}\b", text):
            return _ALIASES.get(base, base)
    return None


_URL_TAIL_RE = re.compile(r"-([a-z0-9]+)-cat_ma\d+mo\d+-")


def color_from_autoscout24_url(url: str) -> str | None:
    """The colour AutoScout24 encodes in an offer slug, if it recorded one."""
    match = _URL_TAIL_RE.search(url or "")
    return normalize_color(match.group(1)) if match else None
