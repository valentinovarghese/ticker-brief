#!/usr/bin/env python3
"""Hold a newly researched edition against its preserved price evidence."""

import argparse
import json
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path

from session_snapshot import SYMBOLS

ROOT = Path(__file__).parent


def validate(edition, snapshot):
    errors = []
    session = snapshot.get('session')
    if edition.get('date') != session or edition.get('data', {}).get('session') != session:
        errors.append('edition date and data session must match snapshot')
    if edition.get('data', {}).get('tickers') != snapshot.get('tickers'):
        errors.append('edition data.tickers must be copied unchanged from the snapshot')
    entries = edition.get('entries', [])
    names = [e.get('ticker') for e in entries if isinstance(e, dict)]
    if len(entries) != len(SYMBOLS) or set(names) != set(SYMBOLS) or len(set(names)) != len(names):
        errors.append('entries must contain each of the twelve tickers exactly once')
    if not edition.get('macro') or not edition.get('readthrough'):
        errors.append('market-wide analysis and read-through are required')
    if len(edition.get('quick', [])) < 2:
        errors.append('quick needs a researched market summary')
    log = edition.get('research_log', {})
    if set(log) != set(SYMBOLS):
        errors.append('research_log must cover each of the twelve tickers')
    for symbol in SYMBOLS:
        item = log.get(symbol, {})
        if item.get('outcome') not in ('dated_event', 'no_verified_event'):
            errors.append(f'{symbol}: research outcome must be dated_event or no_verified_event')
        if not item.get('checked_at_utc'):
            errors.append(f'{symbol}: missing research check time')
        else:
            try:
                checked = datetime.fromisoformat(item['checked_at_utc'].replace('Z', '+00:00'))
                if checked.tzinfo is None or checked > datetime.now(timezone.utc):
                    raise ValueError
            except ValueError:
                errors.append(f'{symbol}: invalid research check time')
        sources = item.get('sources', [])
        if item.get('outcome') == 'dated_event' and not sources:
            errors.append(f'{symbol}: dated event needs a source')
        for source in sources:
            if not re.match(r'^https://', source.get('url', '')):
                errors.append(f'{symbol}: source needs an HTTPS URL')
            try:
                event_date = date.fromisoformat(source['event_date'])
                if event_date > date.fromisoformat(session):
                    errors.append(f'{symbol}: source event date is after edition date')
            except (KeyError, ValueError, TypeError):
                errors.append(f'{symbol}: source needs a valid event_date')
        matching = next((e for e in entries if isinstance(e, dict) and e.get('ticker') == symbol), {})
        for field, minimum in (('happened', 20), ('why', 70),
                               ('priced_in', 18), ('would_change', 12)):
            prose = matching.get(field, '')
            if isinstance(prose, list):
                prose = ' '.join(prose)
            count = len(re.findall(r"\b[\w'-]+\b", re.sub(r'<[^>]*>', '', str(prose))))
            if count < minimum:
                errors.append(f'{symbol}: {field} needs at least {minimum} words')
        if len(matching.get('figures', [])) < 3:
            errors.append(f'{symbol}: at least three concrete figures required')
        analysis = matching.get('analysis', [])
        if len(analysis) < 2 or any(
                not isinstance(point, dict) or
                len(re.findall(r"\b[\w'-]+\b", point.get('body', ''))) < 28
                for point in analysis):
            errors.append(f'{symbol}: two developed analysis points required')
        if not matching.get('next_date'):
            errors.append(f'{symbol}: next date or explicit unscheduled watch required')
        if item.get('outcome') == 'dated_event' and not any(
                foot.get('url') for foot in matching.get('foot', []) if isinstance(foot, dict)):
            errors.append(f'{symbol}: dated event needs a visible source link')
    for symbol, row in snapshot.get('tickers', {}).items():
        pct = (row['close'] / row['previous_close'] - 1) * 100
        if not math.isclose(pct, row['pct'], abs_tol=0.0001):
            errors.append(f'{symbol}: close and previous close contradict pct')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    args = parser.parse_args()
    edition_path = ROOT / 'editions' / f'{args.date}.json'
    edition = json.loads(edition_path.read_text(encoding='utf-8'))
    snapshot = json.loads(args.snapshot.read_text(encoding='utf-8'))
    errors = validate(edition, snapshot)
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f'ok: researched edition {args.date} matches completed-session evidence')


if __name__ == '__main__':
    main()
