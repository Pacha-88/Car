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
