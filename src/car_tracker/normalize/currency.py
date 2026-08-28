"""Currency conversion — pure logic only.

Resolving *which* day's rate to use (e.g. falling back to the last
published rate over a weekend, since the ECB does not publish on
weekends/EU holidays) is the fx-fetching layer's job, not this module's.
"""

from __future__ import annotations

EUR = "EUR"

# Which currency a listing in a given country is priced in. Every supported
# market except Hungary is eurozone; add here as coverage grows rather than
# assuming EUR everywhere.
_NON_EUR_COUNTRIES: dict[str, str] = {"HU": "HUF"}


def market_currency(country: str) -> str:
    return _NON_EUR_COUNTRIES.get(country, EUR)


def to_eur(amount: float, currency: str, rates_to_eur: dict[str, float]) -> float:
    """Convert `amount` in `currency` to EUR.

    `rates_to_eur` maps currency code -> "1 unit of that currency in EUR",
    the inverse of the ECB's native "1 EUR = X currency" convention (see
    fx/ecb.py, which does that inversion once at ingestion so every reader
    downstream can just multiply).
    """
    if currency == EUR:
        return amount
    if currency not in rates_to_eur:
        raise ValueError(f"no EUR rate available for currency {currency!r}")
    return amount * rates_to_eur[currency]
