"""Chassis-generation ("Legacy" vs. refresh) detection.

Both tracked models got a mid-life refresh, but under different internal
codenames: Model 3's refresh is "Highland" (international deliveries from
~late 2023), Model Y's is "Juniper" (international deliveries from ~early-
mid 2025). "Legacy" means pre-refresh for either model.

The cutover dates below are best-effort placeholders from public delivery-
start knowledge, NOT verified against real listing data yet (this sandbox
currently has no network access to the listing sites — see project README).
Treat them as a starting point to sanity-check once real listings come in:
actual EU market availability lagged initial delivery announcements by
weeks to months and varies by country, and sites may express "model year"
differently (registration year vs. Tesla's own model-year label).
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

# Rare but cheap to catch: some listings spell the generation out in the title.
_TITLE_HINTS: dict[str, tuple[str, ...]] = {
    MODEL_3_REFRESH: ("highland",),
    MODEL_Y_REFRESH: ("juniper",),
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
        lowered = title.lower()
        for generation, hints in _TITLE_HINTS.items():
            if any(hint in lowered for hint in hints):
                return generation

    if first_registration is not None:
        return cutover.refresh_name if first_registration >= cutover.cutover_date else LEGACY

    if model_year is not None:
        return cutover.refresh_name if model_year >= cutover.cutover_model_year else LEGACY

    return None
