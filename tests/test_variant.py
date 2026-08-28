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
        (None, None),
        ("", None),
    ],
)
def test_normalize_variant(text, expected):
    assert normalize_variant(text) == expected
