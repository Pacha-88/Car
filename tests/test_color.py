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
