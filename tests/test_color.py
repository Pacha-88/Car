"""normalize/color.py - one colour vocabulary across sources.

The filter this feeds was structurally dead before: of 621 real listings
exactly one carried a colour, because only tesla.py ever set the field.
"""

import pytest

from car_tracker.normalize.color import color_from_autoscout24_url, normalize_color


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("white", "white"),
        ("BLACK", "black"),
        ("  Grey  ", "grey"),
        ("gray", "grey"),  # one word for one colour, or the chips split
        ("violet", "purple"),
    ],
)
def test_basic_words(raw, expected):
    assert normalize_color(raw) == expected


@pytest.mark.parametrize(
    ("paint", "expected"),
    [
        ("PEARL_WHITE_MULTI_COAT", "white"),
        ("SOLID_BLACK", "black"),
        ("MIDNIGHT_SILVER", "silver"),
        ("DEEP_BLUE_METALLIC", "blue"),
        ("ULTRA_RED", "red"),
        ("STEALTH_GREY", "grey"),
        ("QUICKSILVER", "silver"),  # no word boundary to find "silver" by
    ],
)
def test_tesla_paint_codes_land_on_the_same_words(paint, expected):
    assert normalize_color(paint) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "electric", "514pk", "unfallfrei"])
def test_anything_that_names_no_colour_is_unknown(raw):
    """Better an honest Unknown than a colour invented from a version-text
    token - this is also what keeps the URL reader from misfiring."""
    assert normalize_color(raw) is None


@pytest.mark.parametrize("raw", ["greyhound-edition", "hundred", "bordeaux", "silverstone"])
def test_a_colour_word_buried_inside_another_word_is_not_a_colour(raw):
    """Word-boundary matching, not substring: a Greyhound Edition is not a
    grey car and "hundred" is not red. QUICKSILVER is the one paint name
    that needs an explicit entry precisely because this rule is strict."""
    assert normalize_color(raw) is None


def test_separators_split_into_words_so_a_real_colour_is_still_found():
    assert normalize_color("grey-metallic") == "grey"
    assert normalize_color("PEARL_WHITE") == "white"


# --- the AutoScout24 slug --------------------------------------------------
# Shape verified across 234 live listings in six markets: 221 ended in a
# colour, 13 ended in the fuel word because no colour was recorded, none
# failed to match. The last token before "-cat_" is the whole rule.

def test_the_slug_carries_the_colour_when_one_was_recorded():
    url = "/offers/tesla-model-y-standard-range-rwd-1-hand-unfallfrei-electric-white-cat_ma51520mo75320-e83689c2-3a8e"
    assert color_from_autoscout24_url(url) == "white"


def test_a_slug_with_no_colour_ends_in_the_fuel_word():
    url = "/offers/tesla-model-3-long-range-awd-514pk-electric-cat_ma51520mo74665-abc12345-0000"
    assert color_from_autoscout24_url(url) is None


@pytest.mark.parametrize("url", ["", "/offers/nothing-like-a-listing", "https://example.com/x"])
def test_an_unrecognisable_url_yields_no_colour(url):
    assert color_from_autoscout24_url(url) is None


# --- German and Hungarian ad headlines ------------------------------------
# Two of the four sources have no colour field at all: Kleinanzeigen and
# Használtautó carry only the seller's own headline. English-only, that
# meant every car from either of them was colourless - and once Hungary
# scraped properly, about half the dashboard sat in "Unknown".


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # German, including the adjective endings and the compound shades
        # that car ads are actually written in. Two rows that used to sit
        # here asserted misreadings as correct: "*LEDER/Weiss*" (white
        # LEATHER - the audit found the actual car's colour field says
        # black) and "rote Bremssättel" (a Performance's red CALIPERS).
        # Both now live in the part-guard tests below, expecting None.
        ("ModelY LongRange Dual AWD Schwarz Schwarz Steuer", "black"),
        ("Model 3 schwarz, Sportpaket", "black"),
        ("Model 3 dunkelblau metallic", "blue"),
        ("Model Y tiefschwarz", "black"),
        ("Model Y hellgrau", "grey"),
        ("Model 3 perlweiss", "white"),
        ("Tesla Model Y Performance Silber", "silver"),
        # Hungarian
        ("Tesla Model Y fehér", "white"),
        ("MODEL 3 fekete, garanciával", "black"),
        ("Model Y szürke metál", "grey"),
        ("MODEL 3 kék", "blue"),
        ("Model Y ezüst színben", "silver"),
        ("Model 3 vörös", "red"),
        ("Model Y sötétkék", "blue"),
        ("Model 3 világosszürke", "grey"),
    ],
)
def test_reads_a_colour_out_of_a_german_or_hungarian_headline(title, expected):
    assert normalize_color(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        # The traps. "Gründen" is not green: German stems take adjective
        # endings only, never any suffix.
        "Model Y aus Gründen zu verkaufen",
        "Tesla Model 3 Rotation der Reifen inklusive",
        # "kerekek" (wheels) ends in a bare "kek", which is why the
        # Hungarian blue insists on its accent.
        "Model Y mit vier Kerekek",
        # Real headlines from the live export that name no colour.
        "TESLA MODEL Y RWD (Automata) GARANCIA/95%-OS AKKU /LFP/60Kwh!",
        "TESLA MODEL Y Long Range AWD (Automata) Kerámia bevonat Performance díszítésekkel",
        "Model Y Long Range AWD Autopilot",
        "Tesla Model 3 Standard Range Plus Bj 2021",
    ],
)
def test_does_not_invent_a_colour(title):
    assert normalize_color(title) is None


def test_english_still_wins_over_another_language_s_spelling():
    """Tesla paint codes and AutoScout24 slugs must not be re-read."""
    assert normalize_color("PEARL_WHITE_MULTI_COAT") == "white"
    assert normalize_color("MIDNIGHT_SILVER") == "silver"
    assert normalize_color("quicksilver") == "silver"


# --- a colour can belong to the cabin instead of the paint ----------------
# Three real headlines in the export said white and meant the seats. Two of
# them were mislabelled by the English vocabulary that predates this work,
# so the trap was already live; reading German and Hungarian widened it.


@pytest.mark.parametrize(
    "title",
    [
        # Verbatim from the current export.
        "Tesla Model Y Long Range AWD*Ryzen*White Interior*AHK*",
        "Model 3 Performance AWD - weißes Interieur",
        "Standard Range RWD Plus 57,5kWh *WEISSES LEDER*",
        # The same shape in the other spellings.
        "Model Y schwarze Ledersitze",
        "Model 3 Leder schwarz",
        "Model Y fekete bőrbelső",
        "Model 3 schwarzer Innenraum",
    ],
)
def test_a_colour_that_names_the_cabin_is_not_the_car_s_colour(title):
    assert normalize_color(title) is None


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # Attached directly means the cabin; separated means a list of two
        # facts about the car, the first of which is its colour.
        ("Model Y weiß mit schwarzem Leder", "white"),
        ("Model Y weiß, Lederausstattung", "white"),
        ("Model Y fehér, bőr belső", "white"),
    ],
)
def test_a_colour_listed_beside_the_upholstery_is_still_the_car_s(title, expected):
    assert normalize_color(title) == expected


def test_the_leftmost_colour_wins_across_both_vocabularies():
    """Running English to exhaustion first let a later English word beat an
    earlier German one - which is how "White Interior" outranked the paint."""
    assert normalize_color("Model Y fehér, Black Package") == "white"


@pytest.mark.parametrize(
    "title",
    [
        # All from the live export's classification audit. White LEATHER
        # in a black car, exported as a white car, because the guard did
        # not know "/" as a separator; "Innen Weiß" (white inside), where
        # the bare adverb was missing from the vocabulary; and a
        # Performance's red CALIPERS read as a red car - the case that
        # widened the cabin guard into a part guard.
        "Performance Dual AWD*LEDER/Weiss*21Zoll*",
        "Performance FSD Innen Weiß",
        "Model Y rote Bremssättel",
        "Model 3 fekete tető, vonóhorog",
        "Long Range AWD Black Roof",
    ],
)
def test_a_part_s_colour_is_not_the_car_s(title):
    assert normalize_color(title) is None


def test_a_part_s_colour_does_not_hide_the_car_s_own():
    """The guard must skip the part and keep reading: a black-roofed white
    car is still a white car."""
    assert normalize_color("fekete tetős fehér Model Y") == "white"
    assert normalize_color("Model 3 weiß, rote Bremssättel") == "white"
