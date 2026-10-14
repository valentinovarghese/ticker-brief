#!/usr/bin/env python3
"""Validate the daily cross-market report before it reaches the site."""

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
GENERAL = ('equities', 'treasuries_bonds', 'credit', 'currencies',
           'crypto', 'commodities', 'housing', 'us_policy')
INTERNATIONAL = ('uk', 'euro_area', 'china', 'japan', 'other_world')


def words(value):
    return len(re.findall(r"\b[\w'-]+\b", re.sub(r'<[^>]+>', '', str(value))))


def validate(report):
    errors = []
    try:
        report_date = date.fromisoformat(report['date'])
        updated = datetime.fromisoformat(report['as_of_utc'].replace('Z', '+00:00'))
        if updated.tzinfo is None or updated.date() != report_date or updated > datetime.now(timezone.utc):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return ['invalid report date or UTC update time']
    if words(report.get('headline', '')) < 4:
        errors.append('report needs a substantive headline')
    if words(report.get('overview', '')) < 55:
        errors.append('overview needs at least 55 words of market synthesis')
    for field, required in (('general', GENERAL), ('international', INTERNATIONAL)):
        categories = report.get(field, [])
        if not isinstance(categories, list):
            errors.append(f'{field} must be a list')
            continue
        ids = [c.get('id') for c in categories if isinstance(c, dict)]
        if len(ids) != len(set(ids)) or not set(required).issubset(ids):
            errors.append(f'{field} must cover each required category exactly once')
        for category in categories:
            if not isinstance(category, dict):
                errors.append(f'{field}: invalid category')
                continue
            cid = category.get('id', '?')
            if not category.get('label') or not category.get('items'):
                errors.append(f'{cid}: label and at least one item required')
            for item in category.get('items', []):
                if words(item.get('headline', '')) < 3:
                    errors.append(f'{cid}: short headline')
                if words(item.get('detail', '')) < 35 or words(item.get('why', '')) < 30:
                    errors.append(f'{cid}: detail and why need substantive explanation')
                if words(item.get('watch', '')) < 8:
                    errors.append(f'{cid}: watch needs a concrete next test')
                if item.get('status') not in ('new', 'carry_forward'):
                    errors.append(f'{cid}: status must be new or carry_forward')
                try:
                    observed = date.fromisoformat(item['as_of'])
                    if observed > report_date:
                        raise ValueError
                except (KeyError, TypeError, ValueError):
                    errors.append(f'{cid}: invalid as_of date')
                sources = item.get('sources', [])
                if not sources:
                    errors.append(f'{cid}: at least one dated source required')
                for source in sources:
                    if not str(source.get('url', '')).startswith('https://'):
                        errors.append(f'{cid}: source URL must be HTTPS')
                    if not source.get('title'):
                        errors.append(f'{cid}: source title required')
                    try:
                        published = date.fromisoformat(source['published'])
                        if published > report_date:
                            raise ValueError
                    except (KeyError, TypeError, ValueError):
                        errors.append(f'{cid}: invalid source published date')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True)
    args = parser.parse_args()
    path = ROOT / 'market' / f'{args.date}.json'
    report = json.loads(path.read_text(encoding='utf-8'))
    if report.get('date') != args.date:
        raise SystemExit('market filename and report date differ')
    errors = validate(report)
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f'ok: market report {args.date} covers general and international markets')


if __name__ == '__main__':
    main()
