"""Daily EUR reference rates from the European Central Bank.

Free, stable, no API key, includes HUF. Published once per TARGET business
day (no weekend/EU-holiday updates), so callers needing "today's" rate must
be prepared to fall back to the most recently stored date.

The feed's XML shape is documented at the URL below and has been stable for
years. Verified live (2026-08-28): 29 currencies including HUF, rate_date
matched the day's date.
"""

from __future__ import annotations

from datetime import date, datetime
from xml.etree import ElementTree

import httpx

ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
_NS = {"ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}


def fetch_latest_rates(client: httpx.Client | None = None) -> tuple[date, dict[str, float]]:
    """Return (rate_date, {currency: rate_to_eur}) for the ECB's latest publication."""
    owns_client = client is None
    client = client or httpx.Client(timeout=20.0)
    try:
        response = client.get(ECB_DAILY_URL)
        response.raise_for_status()
        return parse_daily_xml(response.text)
    finally:
        if owns_client:
            client.close()


def parse_daily_xml(xml_text: str) -> tuple[date, dict[str, float]]:
    """`rate_to_eur` is "1 unit of currency in EUR" — the ECB's own feed
    gives the inverse ("1 EUR = X currency"); inverted here once so the
    rest of the codebase can just multiply (see normalize/currency.py).
    """
    root = ElementTree.fromstring(xml_text)
    day_cube = root.find(".//ecb:Cube/ecb:Cube", _NS)
    if day_cube is None:
        raise ValueError("unexpected ECB feed shape: no dated Cube found")

    rate_date = datetime.strptime(day_cube.attrib["time"], "%Y-%m-%d").date()
    units_per_eur = {cube.attrib["currency"]: float(cube.attrib["rate"]) for cube in day_cube.findall("ecb:Cube", _NS)}
    rates_to_eur = {currency: 1.0 / units for currency, units in units_per_eur.items()}
    return rate_date, rates_to_eur
