import pytest

from car_tracker.normalize.currency import to_eur


def test_eur_passthrough_ignores_rate_table():
    assert to_eur(10_000, "EUR", {}) == 10_000


def test_huf_conversion():
    rates = {"HUF": 1 / 390.0}  # ~1 EUR = 390 HUF
    assert to_eur(3_900_000, "HUF", rates) == pytest.approx(10_000, rel=1e-6)


def test_unknown_currency_raises():
    with pytest.raises(ValueError):
        to_eur(100, "CHF", {"HUF": 0.0025})
