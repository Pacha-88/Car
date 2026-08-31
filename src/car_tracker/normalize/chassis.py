"""Chassis-generation ("Legacy" vs. refresh) detection.

Both tracked models got a mid-life refresh, but under different internal
codenames: Model 3's refresh is "Highland" (international deliveries from
~late 2023), Model Y's is "Juniper" (international deliveries from ~early-
mid 2025). "Legacy" means pre-refresh for either model.

The cutover dates below started as best-effort placeholders from public
delivery-start knowledge. Checked since against 621 live listings, and
they hold: every ad that names its own generation lands on the generation
the date rule gives it - Highland at 2023-12 and 2024-08, Juniper at
2025-09 - and Model Y registrations either side of 2025-03-01 split
cleanly, legacy in January and February, Juniper from March.

"Facelift" is deliberately not a refresh hint. German ads use it for the
2021 Model 3 update (heat pump, chrome delete) as readily as for
Highland, so five of the six ads carrying the word are pre-refresh cars
from 2021 and 2023; reading it as a codename would have moved them all.

Still worth re-checking if a market is added: EU availability lagged
initial delivery announcements by weeks to months and varies by country,
and sites may express "model year" differently (registration year vs.
Tesla's own model-year label).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

LEGACY = "legacy"
MODEL_3_REFRESH = "highland"
MODEL_Y_REFRESH = "juniper"


@dataclass(frozen=True)
class ChassisCutover:
    refresh_name: str
    cutover_date: date  # first_registration on/after this date => refresh
    cutover_model_year: int  # model_year on/after this => refresh, used when no exact date is available


CUTOVERS: dict[str, ChassisCutover] = {
    "model_3": ChassisCutover(refresh_name=MODEL_3_REFRESH, cutover_date=date(2023, 10, 1), cutover_model_year=2024),
    "model_y": ChassisCutover(refresh_name=MODEL_Y_REFRESH, cutover_date=date(2025, 3, 1), cutover_model_year=2025),
}

# Some listings spell the generation out in the title. The codenames are
# exact; the "new model" phrasings were added from real ads that carried
# them as a badge ("Standard RWD Neues Modell", "RWD Plus NEW-Model") -
# sellers of refresh cars registered inside the runout window, where the
# date rule alone must guess. The phrasing could in principle appear in a
# legacy ad's sales pitch ("the new model is out, hence the price"), but
# marketplace titles are badge-strings, not sentences, and every live
# occurrence found named the car itself. "Launch series" is a trim only
# the Model Y refresh ever had.
_TITLE_HINTS: dict[str, tuple[str, ...]] = {
    MODEL_3_REFRESH: ("highland", "new model", "new-model", "neues modell", "nieuw model", "új modell", "uj modell"),
    MODEL_Y_REFRESH: (
        "juniper",
        "launch series",
        "new model",
        "new-model",
        "neues modell",
        "nieuw model",
        "új modell",
        "uj modell",
    ),
    LEGACY: ("legacy", "pre-facelift", "pre facelift"),
}


def detect_chassis(
    model: str,
    *,
    first_registration: date | None = None,
    model_year: int | None = None,
    title: str | None = None,
) -> str | None:
    """Best-effort chassis generation for `model` ("model_3" | "model_y").

    Returns "legacy", the model's refresh codename, or None if there isn't
    enough signal to tell.
    """
    if model not in CUTOVERS:
        raise ValueError(f"unknown model {model!r}, expected one of {sorted(CUTOVERS)}")
    cutover = CUTOVERS[model]

    if title:
        # Only this model's own generations. Dealer ads cross-sell ("Model 3
        # LR, auch Model Y Juniper verfügbar"), and matching every codename
        # put a Model Y chassis on a Model 3 - overriding a 2022
        # registration date that said Legacy plainly. A generation the model
        # does not have is never the answer.
        allowed = {cutover.refresh_name, LEGACY}
        lowered = title.lower()
        for generation, hints in _TITLE_HINTS.items():
            if generation in allowed and any(hint in lowered for hint in hints):
                return generation

    if first_registration is not None:
        return cutover.refresh_name if first_registration >= cutover.cutover_date else LEGACY

    if model_year is not None:
        return cutover.refresh_name if model_year >= cutover.cutover_model_year else LEGACY

    return None
