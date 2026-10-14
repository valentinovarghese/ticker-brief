# Daily publication runbook

The Codex automation runs daily at 22:00 Europe/London, after the regular
US market close through UK/US daylight-saving transitions. It publishes a
dated Market report every calendar day, including weekends and US market
holidays. On eligible trading days it also publishes the researched
twelve-ticker edition after 17:00 ET. It is the sole scheduled publisher.
`.github/workflows/daily-brief.yml` is a manual source check; the
five-minute news workflow is independent.

1. Clone or fast-forward a clean `main`. Check the current New York date,
   the official [NYSE calendar](https://www.nyse.com/trade/hours-calendars),
   and whether today's market report and stock edition exist. On a weekend
   or holiday, publish only the Market report. Never overwrite a prior
   day's report or any stock edition. If today's Market report was drafted
   before the US close, refresh that same day's report after the close.
2. Research and write `market/YYYY-MM-DD.json` with the schema in
   `market_gate.py`. Cover every General market category (equities,
   Treasuries and bonds, credit, currencies, crypto, commodities, housing,
   US policy)
   and Wider market category (UK, euro area, China, Japan, other world).
   Each item needs a dated event or observation, its meaning for readers,
   a concrete next test, and a direct source link. Mark older but still
   relevant items `carry_forward`, give their actual observation dates,
   and replace stale items when better evidence is available. Include
   other regions or assets when a material story warrants them. Avoid
   generic headlines, undated market direction, unsupported causal claims
   and padding. On weekends or holidays, explain when a market is closed
   and cover fresh policy, earnings or international developments; do not
   manufacture a US closing move.
3. On an eligible trading day after 17:00 ET, ensure Python 3.12+ and the
   `tzdata` package on Windows. Run
   `python3 session_snapshot.py --date YYYY-MM-DD` (use `py` on Windows).
   It writes ignored `work/session-snapshot-YYYY-MM-DD.json`. The script
   validates a dated completed daily bar for all twelve tickers, calculates
   the prior-close return and trailing volume average, and fails atomically.
   Do not use `/quote` as the closing snapshot.
4. Research each company and the market context from dated, attributable
   sources. The live `news/index.json` is a lead list, not verified causal
   analysis. Open the underlying primary release, filing, or reputable
   reporting before using it. Record the event date and URL. If no material
   company event is verified, say that clearly, and explain what the measured
   price and volume do and do not establish. Do not assign a cause to a move
   from a headline alone. Check earnings dates anew; `research.json` is a
   research cache, not a current calendar.
5. Write one edition with the existing schema and all twelve entries. Copy
   the snapshot `session`, `source`, and `tickers` into its `data` block
   without changing values. Add a top-level `research_log` mapping each
   ticker to `checked_at_utc`, `outcome` (`dated_event` or
   `no_verified_event`), and `sources` (each source has `url` and
   `event_date`). Record a source for every dated company event. Compute
   every comparison over the full snapshot, as `CLAUDE.md` requires.
   The editorial bar is the long-form reference: clear event and figures,
   developed valuation and risk analysis, what may already be priced in,
   what would change the reading, next date, and visible source links.
   `edition_gate.py` enforces minimum depth but a passing word count is
   not sufficient editorial review.
6. Run `python3 market_gate.py --date YYYY-MM-DD` and, on a trading day,
   `python3 edition_gate.py --date YYYY-MM-DD --snapshot
   work/session-snapshot-YYYY-MM-DD.json`. Then run `python3 build.py --check`,
   then `python3 build.py`. Review every unmapped comparative claim reported
   by the checker. Verify `index.html` and `site.html` have matching hashes
   and display the Market report and, if applicable, new stock edition.
   Re-read source dates, figures, and the rendered page before committing.
7. Stage only the new report, eligible stock edition, and generated
   site/research outputs. Commit,
   `git pull --rebase origin main`, then push to `main`; retry a rejected push
   after another fetch/rebase. Check the remote report, eligible edition,
   site outputs and live deployment.

If source data, research, credentials, or repository access fail, stop and
report the exact blocker. Do not publish a partial report or edition. This runbook
cannot guarantee that a third-party API or news source will always be up;
failing closed protects the archive when one is unavailable.
