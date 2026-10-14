import copy
import unittest
from datetime import datetime, timezone

import edition_gate
import market_gate
import session_snapshot
import publication_calendar
import build


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

    def test_london_afternoon_uses_last_completed_session(self):
        self.assertEqual(
            publication_calendar.publication_dates(
                datetime(2026, 10, 15, 12, tzinfo=timezone.utc)),
            {'market_date': '2026-10-15', 'stock_session': '2026-10-14'})
        self.assertEqual(
            publication_calendar.publication_dates(
                datetime(2026, 11, 28, 13, tzinfo=timezone.utc)),
            {'market_date': '2026-11-28', 'stock_session': '2026-11-27'})
        self.assertEqual(
            publication_calendar.publication_dates(
                datetime(2026, 11, 27, 13, tzinfo=timezone.utc)),
            {'market_date': '2026-11-27', 'stock_session': '2026-11-25'})


class EditionGateTests(unittest.TestCase):
    def test_rejects_changed_evidence_and_missing_research(self):
        row = {'close': 102, 'previous_close': 100, 'pct': 2.0}
        snapshot = {'session': '2026-10-13', 'tickers': {s: row for s in session_snapshot.SYMBOLS}}
        entries = [{'ticker': s,
                    'happened': 'The completed session price and volume changed while no dated company event was verified in the source window today. This is a measured move, with its cause still unresolved.',
                    'why': ('The share move changes the market price of future cash flows, but the price alone cannot tell us which assumption moved. '
                            'Investors still need evidence about customer demand, margins, capital spending and competitive position before changing an estimate of intrinsic value. '
                            'Volume relative to the prior twenty sessions helps judge participation, yet it cannot identify the buyers or prove a news cause. '
                            'A later filing or company release could alter this interpretation; until then the measured tape is a signal to investigate rather than an answer.'),
                    'figures': ['Close', 'Volume', 'Range'],
                    'analysis': [{'heading': 'Demand', 'body': 'A change in demand would alter revenue expectations and therefore the cash flow available to owners over several years. A price change by itself does not measure orders or customer retention. The next company disclosure is needed to test demand directly.'},
                                 {'heading': 'Risk', 'body': 'Higher discount rates can lower the present value of distant earnings, particularly for growth businesses. The session bar does not separate that effect from company-specific news or positioning. A comparison with peers and Treasury yields would help.'}],
                    'priced_in': 'The completed close incorporates the known information at that time, but cannot show which expectation investors revised or whether the same information was already expected.',
                    'would_change': 'A dated company filing or earnings release with measurable new guidance would change this reading.',
                    'next_date': 'Next scheduled earnings date to verify.'}
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


class MarketGateTests(unittest.TestCase):
    def test_requires_all_market_categories_and_sources(self):
        item = {'headline': 'A dated market development',
                'detail': ' '.join(['Verified market facts need enough context to distinguish the current observation from a prior reading.'] * 5),
                'why': ' '.join(['The transmission to rates, currencies, earnings and risk appetite depends on the channel and timing.'] * 5),
                'watch': 'The next official release or policy decision will test this interpretation.',
                'status': 'new', 'as_of': '2026-10-14',
                'sources': [{'title': 'Official release', 'url': 'https://example.gov/release', 'published': '2026-10-14'}]}
        report = {'date': '2026-10-14', 'as_of_utc': '2026-10-14T16:00:00Z',
                  'headline': 'Market forces across the world',
                  'overview': ' '.join(['Market changes should be read across assets and countries before assigning a single cause to the twelve stocks.'] * 5),
                  'general': [{'id': key, 'label': key, 'items': [copy.deepcopy(item)]} for key in market_gate.GENERAL],
                  'international': [{'id': key, 'label': key, 'items': [copy.deepcopy(item)]} for key in market_gate.INTERNATIONAL]}
        self.assertEqual(market_gate.validate(report), [])
        html = build.render_market_report(report)
        self.assertIn('General market', html)
        self.assertIn('Wider market', html)
        self.assertIn('market-treasuries_bonds', html)
        self.assertIn('https://example.gov/release', html)
        report['general'][0]['items'][0]['sources'] = []
        self.assertIn('equities: at least one dated source required', market_gate.validate(report))


if __name__ == '__main__':
    unittest.main()
