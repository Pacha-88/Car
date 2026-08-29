"""normalize/features.py - extras an ad says the car already has.

Someone filtering for "FSD already bought" is filtering on the most
expensive option Tesla sells, so a false positive wastes a click on a car
that has not got it. Every title below is either verbatim from the live
export or the same shape in another market's phrasing.
"""

import pytest

from car_tracker.normalize.features import has_fsd


@pytest.mark.parametrize(
    "title",
    [
        # Verbatim from the current export.
        "Performance FSD AHK USS Radar Ryzen Dual Motor AWD",
        "Long Range AWD !!FSD!!AHK!! Neues Pickerl",
        "LONG RANGE - ALL WHEEL DRIVE - FSD",
        "LR AWD FSD 19 Zoll",
        "Long Range RWD 75 kWh | FSD SUPERVISED | HW4 | SOH",
        # AutoScout24 truncates its version field mid-word.
        "Long Range AWD 75 kWh | SOH 88% | Full Self-Drivin",
        # Tesla's own names in the other two languages.
        "Model 3 mit Volles Potenzial für autonomes Fahren",
        "Model Y teljes önvezetési képesség",
    ],
)
def test_says_the_car_has_fsd(title):
    assert has_fsd(title) is True


@pytest.mark.parametrize(
    "title",
    [
        # Autopilot is standard on every car since 2019 and means nothing;
        # Enhanced Autopilot is the middle package, not FSD. 49 real titles
        # mention one of these without meaning FSD.
        "Standard Range | RWD | Pano | Enhanced Autopilot",
        "Long Range RWD PANO/LED/KAM/AUTOPILOT",
        "LONG RANGE - ALL WHEEL DRIVE - HIGHWAY AUTOPILOT",
        "RWD*ACC*Autopilot*Pano*Kamera*Leder*AHK",
        # Mentioned, and explicitly not on the car.
        "Model 3 ohne FSD",
        "Model Y kein FSD",
        "Model 3 FSD nachrüstbar",
        "Model Y FSD nélkül",
        # Rented or subscribed, not owned - all three verbatim.
        "Performance DMotor,PDC,AHK+FSD -MIETEN !",
        'RWD 58 kWh 20" Alu, AutoPilot4.0, FSD 99,- p/mnd',
        "Long Range RWD 95,9% SoH [ HW4+FSD SUPERVISED €99",
        # Nothing about it at all.
        "Model 3 Performance",
        "",
    ],
)
def test_does_not_claim_fsd(title):
    assert has_fsd(title) is False


def test_a_price_next_to_fsd_only_disqualifies_it_when_it_is_money():
    """"FSD 19 Zoll" is a set of wheels; "FSD €99" is a monthly fee.

    FSD has never sold for under four figures, so a three-digit money
    figure beside it is a recurring price - but the currency marker has to
    be there, or every wheel size would read as a subscription.
    """
    assert has_fsd("LR AWD FSD 19 Zoll") is True
    assert has_fsd("Model Y FSD 8000 EUR extra") is True
    assert has_fsd("Model Y FSD €99") is False
    assert has_fsd("Model Y FSD 99,-") is False


def test_none_and_missing_text():
    assert has_fsd(None) is False
