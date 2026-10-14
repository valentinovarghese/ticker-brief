import copy
import unittest
from datetime import datetime, timezone

import edition_gate
import session_snapshot


class SnapshotTests(unittest.TestCase):
    def test_completed_bar_uses_prior_close_not_quote_timestamp(self):
        rows = []
        for day in range(260, 0, -1):
            rows.append({'datetime': f'2026-01-{day:03d}', 'open': '100',
                         'high': '105', 'low': '95', 'close': '100',
                         'volume': '1000'})
        rows[0].update(datetime='2026-10-13', close='102', high='106', volume='2000')
        row = session_snapshot.from_series('AAPL', rows, '2026-10-13')
        self.assertEqual(row['pct'], 2.0)
        self.assertEqual(row['avg_volume'], 1000)
        self.assertEqual(row['high_52w'], 106)

    def test_missing_session_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'expected exactly one'):
            session_snapshot.from_series('AAPL', [{'datetime': '2026-10-12'}], '2026-10-13')

    def test_holiday_and_preclose_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'not a regular NYSE trading day'):
            session_snapshot.session_time(datetime(2026, 11, 26, 23, tzinfo=timezone.utc),
                                          datetime(2026, 11, 26).date())
        with self.assertRaisesRegex(ValueError, '17:00 ET'):
            session_snapshot.session_time(datetime(2026, 10, 13, 19, tzinfo=timezone.utc),
                                          datetime(2026, 10, 13).date())


class EditionGateTests(unittest.TestCase):
    def test_rejects_changed_evidence_and_missing_research(self):
        row = {'close': 102, 'previous_close': 100, 'pct': 2.0}
        snapshot = {'session': '2026-10-13', 'tickers': {s: row for s in session_snapshot.SYMBOLS}}
        entries = [{'ticker': s, 'happened': 'A sufficiently detailed dated company event description.',
                    'why': 'A sufficiently detailed explanation of the valuation significance.'}
                   for s in session_snapshot.SYMBOLS]
        log = {s: {'outcome': 'no_verified_event', 'checked_at_utc': '2026-10-13T21:00:00Z',
                   'sources': []} for s in session_snapshot.SYMBOLS}
        edition = {'date': '2026-10-13', 'data': copy.deepcopy(snapshot), 'entries': entries,
                   'macro': [{'dt': 'Market'}], 'readthrough': {'heading': 'Tape'},
                   'quick': ['Summary one', 'Summary two'], 'research_log': log}
        self.assertEqual(edition_gate.validate(edition, snapshot), [])
        edition['data']['tickers']['AAPL']['close'] = 103
        self.assertIn('edition data.tickers must be copied unchanged from the snapshot',
                      edition_gate.validate(edition, snapshot))


if __name__ == '__main__':
    unittest.main()
