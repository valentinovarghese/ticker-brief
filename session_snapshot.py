#!/usr/bin/env python3
"""Collect a completed US session from Twelve Data daily bars.

This writes evidence to ignored work/, never an edition. A separate researched
draft must use this exact snapshot for both its numbers and its data block.
"""

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
SYMBOLS = ('AAPL', 'AMZN', 'TSLA', 'PLTR', 'MSFT', 'GOOGL',
           'HOOD', 'NVDA', 'INTC', 'NBIS', 'MRVL', 'META')
NYSE_CALENDAR = 'https://www.nyse.com/trade/hours-calendars'
# NYSE's published 2026-28 calendar. An unknown year fails closed until its
# official calendar is checked and added; an unscheduled closure needs a
# manual override and must never silently produce a holiday edition.
HOLIDAYS = {
    2026: {'2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03',
           '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07',
           '2026-11-26', '2026-12-25'},
    2027: {'2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26',
           '2027-05-31', '2027-06-18', '2027-07-05', '2027-09-06',
           '2027-11-25', '2027-12-24'},
    2028: {'2028-01-17', '2028-02-21', '2028-04-14', '2028-05-29',
           '2028-06-19', '2028-07-04', '2028-09-04', '2028-11-23',
           '2028-12-25'},
}


def session_time(now, session):
    if session.year not in HOLIDAYS:
        raise ValueError(f'NYSE holiday calendar missing for {session.year}: {NYSE_CALENDAR}')
    if session.weekday() >= 5 or session.isoformat() in HOLIDAYS[session.year]:
        raise ValueError(f'{session} is not a regular NYSE trading day')
    ny = now.astimezone(ZoneInfo('America/New_York'))
    if session > ny.date():
        raise ValueError(f'{session} is in the future in New York')
    if session == ny.date() and (ny.hour, ny.minute) < (17, 0):
        raise ValueError(f'wait until at least 17:00 ET for the {session} completed bar')


def positive(value, name):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'invalid {name}: {value!r}') from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f'invalid {name}: {value!r}')
    return result


def fetch_series(symbol, key):
    query = urllib.parse.urlencode({
        'symbol': symbol, 'interval': '1day', 'outputsize': 260, 'apikey': key,
    })
    url = 'https://api.twelvedata.com/time_series?' + query
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                payload = json.load(response)
            if payload.get('status') == 'error':
                raise ValueError(f'Twelve Data error for {symbol}: {payload.get("message")}')
            if not isinstance(payload.get('values'), list):
                raise ValueError(f'Twelve Data returned no daily bars for {symbol}')
            return payload['values']
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 3:
                raise
            time.sleep(15 * (attempt + 1))
    raise AssertionError('unreachable')


def from_series(symbol, values, session):
    rows = sorted(values, key=lambda row: row['datetime'], reverse=True)
    matching = [i for i, row in enumerate(rows) if row['datetime'] == session]
    if len(matching) != 1:
        raise ValueError(f'{symbol}: expected exactly one {session} daily bar')
    i = matching[0]
    if i + 21 >= len(rows):
        raise ValueError(f'{symbol}: need prior close and 20 prior volume bars')
    row, previous = rows[i], rows[i + 1]
    close = positive(row.get('close'), 'close')
    open_ = positive(row.get('open'), 'open')
    high = positive(row.get('high'), 'high')
    low = positive(row.get('low'), 'low')
    volume = positive(row.get('volume'), 'volume')
    prior_close = positive(previous.get('close'), 'previous close')
    if low > min(open_, close) or high < max(open_, close) or low > high:
        raise ValueError(f'{symbol}: inconsistent OHLC bar on {session}')
    prior_volumes = [positive(bar.get('volume'), 'prior volume')
                     for bar in rows[i + 1:i + 21]]
    highs = [positive(bar.get('high'), '52-week high')
             for bar in rows[i:i + 252]]
    if len(highs) < 252:
        raise ValueError(f'{symbol}: fewer than 252 bars for 52-week high')
    return {
        'close': round(close, 5),
        'pct': round((close / prior_close - 1) * 100, 4),
        'open': round(open_, 5),
        'high': round(high, 5),
        'low': round(low, 5),
        'volume': int(volume),
        'avg_volume': round(sum(prior_volumes) / 20),
        'high_52w': round(max(highs), 5),
        'premarket_pct': None,
        'afterhours_pct': None,
        'previous_close': round(prior_close, 5),
        'bar_date': session,
        'source': 'Twelve Data daily time_series',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', help='NYSE session date, YYYY-MM-DD; defaults to today ET')
    parser.add_argument('--output', type=Path, help='evidence JSON path (default: work/session-snapshot-DATE.json)')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    ny = now.astimezone(ZoneInfo('America/New_York'))
    session = datetime.strptime(args.date, '%Y-%m-%d').date() if args.date else ny.date()
    session_time(now, session)
    key = os.environ.get('TWELVEDATA_KEY')
    if not key:
        raise SystemExit('TWELVEDATA_KEY is required')
    output = args.output or ROOT / 'work' / f'session-snapshot-{session}.json'
    if output.exists():
        raise SystemExit(f'refusing to overwrite evidence: {output}')
    quotes = {}
    for index, symbol in enumerate(SYMBOLS):
        if index:
            time.sleep(8)  # Twelve Data Basic is limited to eight credits/minute.
        quotes[symbol] = from_series(symbol, fetch_series(symbol, key), session.isoformat())
        print(f'{symbol}: completed {session} daily bar validated', flush=True)
    snapshot = {
        'session': session.isoformat(),
        'source': 'Twelve Data 1day time_series; exchange-local session',
        'source_url': 'https://twelvedata.com/docs',
        'fetched_at_utc': now.isoformat(),
        'tickers': quotes,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.tmp')
    temporary.write_text(json.dumps(snapshot, indent=2) + '\n', encoding='utf-8')
    temporary.replace(output)
    print(output, flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, urllib.error.URLError) as exc:
        print(f'snapshot unavailable: {exc}', file=sys.stderr)
        sys.exit(1)
