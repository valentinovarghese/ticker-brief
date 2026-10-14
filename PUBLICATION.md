# Daily publication runbook

The Codex automation runs at 22:00 Europe/London on weekdays, safely after
the regular US market close through UK/US daylight-saving transitions. It is
the sole scheduled edition publisher. `.github/workflows/daily-brief.yml`
is a manual source check; the five-minute news workflow is independent.

1. Clone or fast-forward a clean `main`. Check the current New York date,
   the official [NYSE calendar](https://www.nyse.com/trade/hours-calendars),
   and whether `editions/YYYY-MM-DD.json` already exists. Stop on a weekend,
   holiday, before 17:00 ET, or if an edition exists. Never overwrite one.
2. Ensure Python 3.12+ and the `tzdata` package on Windows. Run
   `python3 session_snapshot.py --date YYYY-MM-DD` (use `py` on Windows).
   It writes ignored `work/session-snapshot-YYYY-MM-DD.json`. The script
   validates a dated completed daily bar for all twelve tickers, calculates
   the prior-close return and trailing volume average, and fails atomically.
   Do not use `/quote` as the closing snapshot.
3. Research each company and the market context from dated, attributable
   sources. The live `news/index.json` is a lead list, not verified causal
   analysis. Open the underlying primary release, filing, or reputable
   reporting before using it. Record the event date and URL. If no material
   company event is verified, say that clearly, and explain what the measured
   price and volume do and do not establish. Do not assign a cause to a move
   from a headline alone. Check earnings dates anew; `research.json` is a
   research cache, not a current calendar.
4. Write one edition with the existing schema and all twelve entries. Copy
   the snapshot `session`, `source`, and `tickers` into its `data` block
   without changing values. Add a top-level `research_log` mapping each
   ticker to `checked_at_utc`, `outcome` (`dated_event` or
   `no_verified_event`), and `sources` (each source has `url` and
   `event_date`). Record a source for every dated company event. Compute
   every comparison over the full snapshot, as `CLAUDE.md` requires.
5. Run `python3 edition_gate.py --date YYYY-MM-DD --snapshot
   work/session-snapshot-YYYY-MM-DD.json`, then `python3 build.py --check`,
   then `python3 build.py`. Review every unmapped comparative claim reported
   by the checker. Verify `index.html` and `site.html` have matching hashes
   and display the new edition.
6. Stage only the new edition and generated site/research outputs. Commit,
   `git pull --rebase origin main`, then push to `main`; retry a rejected push
   after another fetch/rebase. Check the remote edition and site outputs.

If source data, research, credentials, or repository access fail, stop and
report the exact blocker. Do not publish a partial edition. This runbook
cannot guarantee that a third-party API or news source will always be up;
failing closed protects the archive when one is unavailable.
