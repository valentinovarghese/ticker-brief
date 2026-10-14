#!/usr/bin/env python3
"""Select dates for the daily London-afternoon publication."""

import argparse
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from session_snapshot import HOLIDAYS, NYSE_CALENDAR


def is_session(day):
    if day.year not in HOLIDAYS:
        raise ValueError(f'NYSE holiday calendar missing for {day.year}: {NYSE_CALENDAR}')
    return day.weekday() < 5 and day.isoformat() not in HOLIDAYS[day.year]


def publication_dates(now):
    """Market report is dated today; stock edition uses the last closed NYSE day."""
    london = now.astimezone(ZoneInfo('Europe/London'))
    new_york = now.astimezone(ZoneInfo('America/New_York'))
    session = new_york.date()
    if (new_york.hour, new_york.minute) < (17, 0):
        session -= timedelta(days=1)
    while not is_session(session):
        session -= timedelta(days=1)
    return {'market_date': london.date().isoformat(),
            'stock_session': session.isoformat()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--at-utc', help='ISO UTC time for a diagnostic check')
    args = parser.parse_args()
    now = (datetime.fromisoformat(args.at_utc.replace('Z', '+00:00'))
           if args.at_utc else datetime.now(timezone.utc))
    if now.tzinfo is None:
        parser.error('--at-utc must include a UTC offset')
    print(json.dumps(publication_dates(now)))


if __name__ == '__main__':
    main()
