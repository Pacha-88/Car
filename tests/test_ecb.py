from datetime import date

import pytest

from car_tracker.fx.ecb import parse_daily_xml

# Shape of the real feed (https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml),
# trimmed to a few currencies. Structural regression test, independent of
# network access.
SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
	<gesmes:subject>Reference rates</gesmes:subject>
	<gesmes:Sender>
		<gesmes:name>European Central Bank</gesmes:name>
	</gesmes:Sender>
	<Cube>
		<Cube time='2026-08-27'>
			<Cube currency='USD' rate='1.0854'/>
			<Cube currency='HUF' rate='391.23'/>
			<Cube currency='CHF' rate='0.9312'/>
		</Cube>
	</Cube>
</gesmes:Envelope>
"""


def test_parses_rate_date():
    rate_date, _ = parse_daily_xml(SAMPLE_XML)
    assert rate_date == date(2026, 8, 27)


def test_inverts_to_rate_to_eur():
    _, rates = parse_daily_xml(SAMPLE_XML)
    assert rates["HUF"] == pytest.approx(1 / 391.23)
    assert rates["USD"] == pytest.approx(1 / 1.0854)


def test_missing_cube_raises():
    with pytest.raises(ValueError):
        parse_daily_xml("<root></root>")
