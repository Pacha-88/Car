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
        # that car ads are actually written in.
        ("Performance Dual AWD*LEDER/Weiss*21Zoll*", "white"),
        ("ModelY LongRange Dual AWD Schwarz Schwarz Steuer", "black"),
        ("Model 3 schwarzer Innenraum", "black"),
        ("Model Y rote Bremssättel", "red"),
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
