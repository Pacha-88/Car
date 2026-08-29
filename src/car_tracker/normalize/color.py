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

# The other two sources have no colour field at all - only the ad's own
# headline, written by a German or a Hungarian seller. Left English-only,
# every Kleinanzeigen and every Használtautó car came out colourless, and
# once Hungary was scraping properly that was about half the dashboard
# sitting in "Unknown".
#
# Stems, not whole words, because both languages inflect them - "schwarzer
# Tesla", "fehérre fóliázva". German takes the adjective endings only
# (\w* would read "aus Gründen" as green); Hungarian's suffixes are too
# many to list, so it takes any, which is safe because its colour words are
# not prefixes of common car-ad vocabulary.
_GERMAN_ENDINGS = r"(?:e|es|er|em|en|ne|nes|ner|nem|nen)?"
_GERMAN_COLORS = {
    "wei(?:ss|ß)": "white",
    "schwarz": "black",
    "silber": "silver",
    "grau": "grey",
    "blau": "blue",
    "rot": "red",
    "gr(?:ü|ue)n": "green",
    "braun": "brown",
    "beige": "beige",
    "gelb": "yellow",
    "orange": "orange",
    "gold": "gold",
    "bronze": "bronze",
    "lila": "purple",
    "violett": "purple",
}
_HUNGARIAN_COLORS = {
    "feh(?:é|e)r": "white",
    "fekete": "black",
    "ez(?:ü|u)st": "silver",
    "sz(?:ü|u)rke": "grey",
    # Accent required here, unlike the longer stems: bare "kek" sits inside
    # ordinary Hungarian plurals ("kerekek" - wheels), and reading a set of
    # wheels as a blue car is exactly the kind of invention this module
    # exists to avoid.
    "kék": "blue",
    "piros": "red",
    "v(?:ö|o)r(?:ö|o)s": "red",
    "z(?:ö|o)ld": "green",
    "barna": "brown",
    "b(?:é|e)zs": "beige",
    "s(?:á|a)rga": "yellow",
    "narancs": "orange",
    "arany": "gold",
    "bronz": "bronze",
    "lila": "purple",
}

# A leading \w*? because both languages build shades as one word -
# "dunkelblau", "tiefschwarz", "sötétkék", "világosszürke". Safe in this
# direction: a compound ENDING in a colour word is a colour. The danger is
# all on the other side, which is what the bounded German endings guard.
_LOCALISED = [
    *((rf"\b\w*?{stem}{_GERMAN_ENDINGS}\b", colour) for stem, colour in _GERMAN_COLORS.items()),
    *((rf"\b\w*?{stem}\w*", colour) for stem, colour in _HUNGARIAN_COLORS.items()),
]
_LOCALISED_RES = [(re.compile(pattern), colour) for pattern, colour in _LOCALISED]

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
    # English first so a paint code or an AutoScout24 slug is never read
    # through another language's spelling.
    earliest: tuple[int, str] | None = None
    for pattern, colour in _LOCALISED_RES:
        match = pattern.search(text)
        # Leftmost wins, the same rule normalize_variant uses: an ad titles
        # the car it is selling first and mentions everything else after.
        if match and (earliest is None or match.start() < earliest[0]):
            earliest = (match.start(), colour)
    return earliest[1] if earliest else None


_URL_TAIL_RE = re.compile(r"-([a-z0-9]+)-cat_ma\d+mo\d+-")


def color_from_autoscout24_url(url: str) -> str | None:
    """The colour AutoScout24 encodes in an offer slug, if it recorded one."""
    match = _URL_TAIL_RE.search(url or "")
    return normalize_color(match.group(1)) if match else None
