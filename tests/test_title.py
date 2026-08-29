"""normalize/title.py and the composed titles that feed it."""

import pytest

from car_tracker.normalize.title import ensure_title, model_display_name
from car_tracker.sources.autoscout24 import _compose_title as autoscout24_title
from car_tracker.sources.tesla import _compose_title as tesla_title


@pytest.mark.parametrize(("model", "expected"), [("model_y", "Model Y"), ("model_3", "Model 3")])
def test_model_display_name(model, expected):
    assert model_display_name(model) == expected


def test_ensure_title_keeps_anything_the_seller_wrote():
    assert ensure_title("Long Range AWD *1. Hand*", model="model_y") == "Long Range AWD *1. Hand*"


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_ensure_title_names_the_model_when_the_ad_says_nothing(empty):
    """Which is what the marketplaces themselves show for those ads - it
    invents no detail, it just stops the card reading "Untitled"."""
    assert ensure_title(empty, model="model_y") == "Tesla Model Y"


def test_autoscout24_prefers_the_sellers_own_trim_line():
    item = {"vehicle": {"modelVersionInput": "Long Range AWD 79kWh", "make": "Tesla", "model": "Model Y"}}
    assert autoscout24_title(item, model="model_y") == "Long Range AWD 79kWh"


def test_autoscout24_falls_back_to_make_and_model_when_the_trim_line_is_blank():
    """A real card: the seller left the version field empty, so this source
    stored no title at all and the dashboard rendered "Untitled". The
    response still says what the car is."""
    item = {"vehicle": {"modelVersionInput": None, "make": "Tesla", "model": "Model 3", "modelGroup": "Model 3"}}
    assert autoscout24_title(item, model="model_3") == "Tesla Model 3"


def test_autoscout24_survives_a_card_with_no_vehicle_block_at_all():
    assert autoscout24_title({}, model="model_y") == "Tesla Model Y"


def test_tesla_composes_from_the_structured_pieces():
    item = {"TrimName": "Long Range AWD", "Year": 2022, "PAINT": ["MIDNIGHT_SILVER"]}
    assert tesla_title(item, model="model_y") == "Model Y · Long Range AWD · 2022 · Midnight Silver"


def test_no_source_can_produce_an_empty_title():
    """The guarantee the dashboard relies on."""
    for composed in (autoscout24_title({}, model="model_y"), tesla_title({}, model="model_3")):
        assert ensure_title(composed, model="model_y").strip()
