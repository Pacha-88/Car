import pytest

from car_tracker.normalize.variant import normalize_variant


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Real AutoScout24 modelVersionInput strings (2026-08-28 sample).
        ("Standard Range RWD *1. Hand*unfallfrei*", "rwd"),
        ("Dual Performance Dual AWD+PANO+R-KAMERA", "performance"),
        ("Long Range AWD *20-Zoll*", "long_range_awd"),
        ("Rear-Wheel Drive", "rwd"),
        ("Some Unrecognized Trim Name", "other"),
        # Real Tesla TrimVariantCode values (2026-08-28 sample) — exact-code
        # match, since the phrase check alone would miss "LR_AWD" entirely.
        ("LR_AWD", "long_range_awd"),
        ("RWD", "rwd"),
        # Real Használtautó.hu title (2026-08-28): trim stated up front,
        # "Performance" mentioned later only as a cosmetic package name -
        # leftmost match must win, not a fixed performance-checked-first order.
        ("TESLA MODEL Y Long Range AWD (Automata) Kerámia bevonat Performance díszítésekkel", "long_range_awd"),
        (None, None),
        ("", None),
    ],
)
def test_normalize_variant(text, expected):
    assert normalize_variant(text) == expected


# --- Long Range RWD: a real trim, not a parsing accident ------------------
# 22 of the first 621 real listings were the single-motor Long Range Model Y,
# and every one was bucketed long_range_awd - reading as a below-market
# "deal" against the pricier AWD baseline.


@pytest.mark.parametrize(
    "title",
    [
        "Long Range RWD PANO/LED/KAM/AUTOPILOT",
        "Long Range RWD",
        "Premium Long Range RWD 78.1 kWh * FSD * SFEER * EY",
        "Long-Range Rear-Wheel Drive",
        "RWD Long Range 650km WLTP",
    ],
)
def test_long_range_with_an_rwd_signal_is_its_own_bucket(title):
    assert normalize_variant(title) == "long_range_rwd"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Long Range Dual Motor AWD", "long_range_awd"),  # AWD is right there
        ("Long Range AWD *20-Zoll*", "long_range_awd"),
        ("Long Range Allrad", "long_range_awd"),
        ("Long Range", "long_range_awd"),  # ambiguous -> the common case
        ("Standard Range RWD *1. Hand*", "rwd"),  # no long range at all
        ("LR_RWD", "long_range_rwd"),  # Tesla's code style, sibling of LR_AWD
    ],
)
def test_the_new_bucket_never_steals_from_the_old_ones(title, expected):
    assert normalize_variant(title) == expected


# --- spellings sellers actually use ----------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "LongRange AWD | AHK | SoH 94%",       # no space
        "Long-Range AWD 351pk 75 kWh",         # hyphen
        "Long R. AWD*GARANTIE*",               # abbreviated
        "LR 79KW",                             # the bare Tesla abbreviation
        "Dual Maximale Reichweite Dual AWD",   # German for Long Range
        "LONGRANGE DUAL-MOTOR NAVI/LED",
    ],
)
def test_the_long_range_spellings_sellers_actually_write(text):
    assert normalize_variant(text) == "long_range_awd"


def test_an_abbreviated_performance_is_still_performance():
    assert normalize_variant("Perf.*AHV*GARANTIE*") == "performance"


def test_an_abbreviated_long_range_rwd_keeps_its_own_bucket():
    """Placed as plain `rwd` before "Long R." was vocabulary, which prices a
    Long Range against the cheaper Standard Range baseline."""
    assert normalize_variant("Long R. RWD 75 kWh | FSD |") == "long_range_rwd"


def test_dual_motor_alone_is_not_a_long_range_claim():
    """Performance is dual-motor AWD too, so this is genuinely ambiguous -
    the catch-all is the honest answer, not a guess."""
    assert normalize_variant("Dual AWD ACC|Navi|Klima") == "other"
    assert normalize_variant("Model Y Allradantrieb") == "other"


def test_lr_does_not_fire_from_inside_a_word():
    assert normalize_variant("Blri Modell") == "other"
