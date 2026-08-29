"""Registration dates that cannot be true.

Marketplace listings are typed by people, and a slipped digit in a
registration date is a common one: a real Model Y — right price, right
mileage, "Certified Pre-Owned" — arrived dated 12/2002 instead of 12/2022.
Nothing downstream questions it, so one such listing:

  * stretched the dashboard's year filter from 2017-2026 to 2002-2026,
    squeezing every real year into a third of the slider, and
  * entered the depreciation curve as a 23-year-old car worth 34.600 EUR,
    which is the single most distorting shape that curve can be given.

The car itself is real and worth tracking, so the date is dropped rather
than the listing (compare cli.is_plausible_car, which drops whole entries
that aren't cars at all). A listing with no registration date simply sits
out the age-based views.

The bounds are deliberately loose: only what is outright impossible is
refused, never merely surprising. An early US-built Model 3 imported to
Europe is unusual, not wrong.
"""

from __future__ import annotations

from datetime import date, timedelta

# First customer deliveries. Nothing of either model existed before these,
# anywhere, so an earlier registration is a typo rather than a rare find.
FIRST_DELIVERY_YEAR = {"model_3": 2017, "model_y": 2020}


def plausible_registration(
    model: str,
    *,
    first_registration: date | None,
    model_year: int | None,
    today: date | None = None,
) -> tuple[date | None, int | None]:
    """Return the pair with anything impossible replaced by None."""
    today = today or date.today()
    floor = FIRST_DELIVERY_YEAR.get(model)
    if floor is None:  # an unknown model: nothing to check it against
        return first_registration, model_year

    # A day of slack on the upper bound, because "today" is the runner's
    # date and the listing's is the market's. The scheduled run is UTC while
    # these registrations are European, and the sources give month
    # granularity (parsed to the 1st) - so on the 1st of a month, in the
    # small hours UTC, a car registered that very month would otherwise have
    # a perfectly good date thrown away.
    if first_registration is not None and not (
        floor <= first_registration.year and first_registration <= today + timedelta(days=1)
    ):
        first_registration = None
    # A model-year label can legitimately run a year ahead of the calendar
    # ("2027 model" sold in 2026); a registration date cannot.
    if model_year is not None and not (floor <= model_year <= today.year + 1):
        model_year = None
    return first_registration, model_year
